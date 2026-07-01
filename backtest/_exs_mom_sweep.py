# -*- coding: utf-8 -*-
"""진입/이탈/슬롯(E/X/S) + 모멘텀타입 재최적화. production-faithful(recent_ca 주입, overheat0.2, 저장growth).
E/X/S는 12m 캐시 1회 후 재사용(빠름). 모멘텀은 타입별 재캐시. top후보 WF(3블록)+LOWO."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ=os.path.dirname(os.path.dirname(os.path.abspath(__file__))); RC=0.3
def ba(s):
    r=s.pct_change(fill_method=None);ev=r[(r<-0.33)|(r>0.45)];s2=s.copy()
    for d,rt in ev.items():
        f=1+rt
        if 0.02<abs(f)<50:s2.loc[s2.index<d]*=f
    return s2
prices=pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_2017*_20260*.parquet')))[-1]).replace(0,np.nan).apply(ba)
kc=pd.read_parquet(os.path.join(PROJ,'data_cache','kospi_yf.parquet')).iloc[:,0];m20=kc.rolling(20).mean();m80=kc.rolling(80).mean()
def calc_reg(ds):
    reg={};md=True;stk=0;ss=None
    for d in ds:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(m80.get(ts,np.nan)):reg[d]=md;continue
        s=bool(m20[ts]>m80[ts])
        if s==ss:stk+=1
        else:stk=1;ss=s
        if stk>=5 and md!=s:md=s
        reg[d]=md
    return reg
G3=('rev_z','oca_z','gp_growth_z',0.4,0.4,0.2)
ar_all={};dall=[]
for f in sorted(glob.glob(os.path.join(PROJ,'state','ranking_*.json'))):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102':ar_all[dt]=json.load(open(f,encoding='utf-8'))['rankings'];dall.append(dt)
dall=sorted(dall)
def patch(t,sd):
    for date,arr in t._overlay_pre.items():
        if arr is None:continue
        rk=sd.get(date)
        if rk is None:continue
        for j,s in enumerate(rk):
            if s.get('recent_ca'):arr[j]-=RC*float(s['recent_ca'])
def make(sub,exclude=None):
    sd={d:[r for r in ar_all[d] if not exclude or r['ticker'] not in exclude] for d in sub}
    t=TurboSimulator(sd,sub,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True
    patch(t,sd)
    return t
def run(t,sub,E,X,S,mom='12m'):
    t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,mom,*G3[:3],*G3[3:])
    f=list(t._cached_flat);reg=calc_reg(sub)
    r=_run_regime_inner(f,f,0,X,S,E,X,S,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    return r.get('calmar',0),r.get('mdd',0),r.get('total',0)
# ── 1. E/X/S 스윕 (12m 고정, 캐시 1회) ──
t=make(dall)
base=run(t,dall,3,6,3)
print(f"[baseline E3X6S3 12m] Calmar {base[0]:.3f} MDD {base[1]:.1f}% 누적 {base[2]:.0f}%\n")
print("[E/X/S 스윕 — Calmar (Δ vs base) / MDD]")
res=[]
for E in [2,3,4,5]:
    for X in [4,5,6,8]:
        if X<E: continue
        for S in [3,4,5]:
            c=run(t,dall,E,X,S)
            res.append((E,X,S,c[0],c[1],c[2]))
res.sort(key=lambda z:-z[3])
print(f"  {'E/X/S':>8} {'Calmar':>7} {'Δ':>7} {'MDD':>6} {'누적%':>8}")
for E,X,S,cal,mdd,tot in res[:12]:
    star=' ★현행' if (E,X,S)==(3,6,3) else ''
    print(f"  {E}/{X}/{S:>3} {cal:>7.3f} {cal-base[0]:>+7.3f} {mdd:>6.1f} {tot:>8.0f}{star}")
# 사용자 예시 5/6/5 명시
for e,x,s in [(3,6,3),(5,6,5),(5,6,3),(5,8,5)]:
    c=run(t,dall,e,x,s)
    print(f"  ▶ {e}/{x}/{s}: Calmar {c[0]:.3f} (Δ{c[0]-base[0]:+.3f}) MDD {c[1]:.1f}%")
# ── 2. 모멘텀 타입 스윕 (E3X6S3 고정) ──
print("\n[모멘텀 타입 스윕 — E3X6S3 고정]")
for mom in ['6m','6m-1m','12m','12m-1m']:
    c=run(t,dall,3,6,3,mom)
    star=' ★현행' if mom=='12m' else ''
    print(f"  {mom:>7}: Calmar {c[0]:.3f} (Δ{c[0]-base[0]:+.3f}) MDD {c[1]:.1f}% 누적 {c[2]:.0f}%{star}")
print("\n[완료]")
