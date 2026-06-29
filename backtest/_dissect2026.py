# -*- coding: utf-8 -*-
"""2026 해부 — 밸류틸트 이득이 robust(광범위)인가 소수종목 artifact인가. 멈춤규칙 판정."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ=os.path.dirname(os.path.dirname(os.path.abspath(__file__)));RC=0.3
def ba(s):
    r=s.pct_change(fill_method=None);ev=r[(r<-0.33)|(r>0.45)];s2=s.copy()
    for d,rt in ev.items():
        f=1+rt
        if 0.02<abs(f)<50:s2.loc[s2.index<d]*=f
    return s2
prices=pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_2017*_20260*.parquet')))[-1]).replace(0,np.nan).apply(ba)
kc=pd.read_parquet(os.path.join(PROJ,'data_cache','kospi_yf.parquet')).iloc[:,0];ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
def calc_reg(ds):
    reg={};md=True;stk=0;ss=None
    for d in ds:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)):reg[d]=md;continue
        s=bool(ma20[ts]>ma80[ts])
        if s==ss:stk+=1
        else:stk=1;ss=s
        if stk>=5 and md!=s:md=s
        reg[d]=md
    return reg
G3=('rev_z','oca_z','gp_growth_z',0.4,0.4,0.2)
ar_all={};dall=[]
for f in sorted(glob.glob(os.path.join(PROJ,'state','ranking_*.json'))):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20260101':ar_all[dt]=json.load(open(f,encoding='utf-8'))['rankings'];dall.append(dt)
dall=sorted(dall)
# 종목명 맵
nm={}
for d in dall:
    for r in ar_all[d]: nm[r['ticker']]=r.get('name',r['ticker'])
def patch(t,sd):
    for date,arr in t._overlay_pre.items():
        if arr is None:continue
        rk=sd.get(date)
        if rk is None:continue
        for j,s in enumerate(rk):
            if s.get('recent_ca'):arr[j]-=RC*float(s['recent_ca'])
def make(sub,exclude=None):
    sd={d:[r for r in ar_all[d] if not exclude or r['ticker'] not in exclude] for d in sub}
    t=TurboSimulator(sd,sub,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True;patch(t,sd);return t
def fl(t,w):
    t._ensure_cache(w[0]/100,w[1]/100,w[2]/100,w[3]/100,0.4,20,'12m',*G3[:3],*G3[3:]);return list(t._cached_flat)
BASE=(15,0,55,30);VAL=(20,0,55,25)
reg=calc_reg(dall)
def run(t,sub,w):
    f=fl(t,w);r=_run_regime_inner(f,f,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    return r.get('calmar',0),r.get('mdd',0),r.get('total',0)
tF=make(dall)
b=run(tF,dall,BASE);v=run(tF,dall,VAL)
print(f"2026 ({dall[0]}~{dall[-1]} {len(dall)}일) — 밸류틸트 V20G55M25 전체적용 vs base")
print(f"  base:  Calmar {b[0]:.2f}  MDD {b[1]:.1f}%  누적 {b[2]:.0f}%")
print(f"  tilt:  Calmar {v[0]:.2f}  MDD {v[1]:.1f}%  누적 {v[2]:.0f}%   (Δ누적 {v[2]-b[2]:+.0f}%p)")
# LOWO: 후보 종목 제거하며 tilt-base Δ누적 변화
cands=['000660','080220','005930','033100','042700','039030','187870','131290','031330','353200','058610','025560','095340']
print(f"\n[LOWO] 종목 제거 시 (tilt 누적 − base 누적). 제거로 Δ가 크게 줄면 그 종목이 이득의 주범")
base_gap=v[2]-b[2]
print(f"  (제거없음) tilt−base = {base_gap:+.0f}%p")
rows=[]
for tk in cands:
    t=make(dall,exclude={tk});bb=run(t,dall,BASE)[2];vv=run(t,dall,VAL)[2]
    rows.append((tk,vv-bb))
for tk,gap in sorted(rows,key=lambda x:x[1]):
    print(f"  −{nm.get(tk,tk)[:10]:<10}({tk}): tilt−base = {gap:+6.0f}%p   (이득 {base_gap-gap:+.0f}%p 감소)")
print("\n[완료]")
