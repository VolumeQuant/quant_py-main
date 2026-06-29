# -*- coding: utf-8 -*-
"""계절옷 ON vs OFF 연도별 깔끔 비교 (2026-06-29, 개인봇 보고용).
계절옷 = 봄(드로다운>10% AND 6개월 시장수익>0)엔 밸류틸트 V25G45M30, 아니면 현행 V15G55M30.
production-faithful(recent_ca ON)."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECENT_CA_W = 0.3
def ba(s):
    r = s.pct_change(fill_method=None); ev = r[(r < -0.33) | (r > 0.45)]; s2 = s.copy()
    for d, rt in ev.items():
        f = 1 + rt
        if 0.02 < abs(f) < 50: s2.loc[s2.index < d] *= f
    return s2
prices = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_2017*_20260*.parquet')))[-1]).replace(0,np.nan).apply(ba)
kc = pd.read_parquet(os.path.join(PROJ,'data_cache','kospi_yf.parquet')).iloc[:,0]
ma20=kc.rolling(20).mean(); ma80=kc.rolling(80).mean()
roll_high=kc.rolling(252,min_periods=60).max(); dd_series=1-kc/roll_high
mom126=kc/kc.shift(126)-1
def calc_reg(ds):
    reg={}; md=True; stk=0; ss=None
    for d in ds:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md; continue
        s=bool(ma20[ts]>ma80[ts])
        if s==ss: stk+=1
        else: stk=1; ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
def is_spring(d):
    ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
    dd=dd_series.get(ts,np.nan); mm=mom126.get(ts,np.nan)
    return bool(pd.notna(dd) and dd>0.10 and pd.notna(mm) and mm>0)
G3=('rev_z','oca_z','gp_growth_z',0.4,0.4,0.2)
ar_all={}; dall=[]
for f in sorted(glob.glob(os.path.join(PROJ,'state','ranking_*.json'))):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102':
        ar_all[dt]=json.load(open(f,encoding='utf-8'))['rankings']; dall.append(dt)
dall=sorted(dall)
def patch_ca(t, sd):
    for date, arr in t._overlay_pre.items():
        if arr is None: continue
        rk=sd.get(date)
        if rk is None: continue
        for j,s in enumerate(rk):
            if s.get('recent_ca'): arr[j]-=RECENT_CA_W*float(s['recent_ca'])
def make(sub):
    sd={d:ar_all[d] for d in sub}
    t=TurboSimulator(sd, sub, prices, overheat_w=0.2); t._use_overlay=True; t._use_stored_growth=True
    patch_ca(t,sd); return t
def flat_of(t,w):
    t._ensure_cache(w[0]/100,w[1]/100,w[2]/100,w[3]/100,0.4,20,'12m',*G3[:3],*G3[3:]); return list(t._cached_flat)
BASE=(15,0,55,30); SPRING=(25,0,45,30)
def res(t,sub,reg,on):
    fb=flat_of(t,BASE)
    if on:
        fv=flat_of(t,SPRING); off=[ (fv[i] if is_spring(sub[i]) else fb[i]) for i in range(len(sub)) ]
    else: off=fb
    r=_run_regime_inner(fb,off,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    return r.get('calmar',0),r.get('mdd',0),r.get('total',0)

print("계절옷 = 봄(회복기)엔 밸류틸트, 아니면 현행 | ON vs OFF\n")
# 전체
tF=make(dall); rF=calc_reg(dall)
off=res(tF,dall,rF,False); on=res(tF,dall,rF,True)
nspring=sum(1 for d in dall if is_spring(d))
print(f"[전체 7.4년] 봄 발동 {nspring}일 / {len(dall)}일")
print(f"  OFF(현행): Calmar {off[0]:.2f}  MDD {off[1]:.1f}%  누적 {off[2]:.0f}%")
print(f"  ON(계절옷): Calmar {on[0]:.2f}  MDD {on[1]:.1f}%  누적 {on[2]:.0f}%  (Δ Calmar {on[0]-off[0]:+.2f})")
# 연도별
print("\n[연도별] (봄발동일 / OFF Calmar → ON Calmar)")
for y in ['2019','2020','2021','2022','2023','2024','2025','2026']:
    sub=[d for d in dall if d[:4]==y]
    if len(sub)<20: continue
    t=make(sub); reg=calc_reg(sub)
    o=res(t,sub,reg,False); n=res(t,sub,reg,True)
    ns=sum(1 for d in sub if is_spring(d))
    tag='봄無' if ns==0 else f'봄{ns}일'
    print(f"  {y} ({tag:>6}): OFF {o[0]:5.2f} → ON {n[0]:5.2f}  Δ{n[0]-o[0]:+.2f}  | 수익 OFF {o[2]:+.0f}% ON {n[2]:+.0f}%")
print("\n[완료]")
