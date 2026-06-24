# -*- coding: utf-8 -*-
"""baseline state/(시총1000억+) vs state_1jo/(1조+) 고정config BT.
일별 수익률로 자산곡선 → 연도별 Calmar/MDD/수익 + 전체 MDD 발생 시점(peak~trough 날짜)."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def ba(s):
    r = s.pct_change(fill_method=None); ev = r[(r < -0.33) | (r > 0.45)]; s2 = s.copy()
    for d, rt in ev.items():
        f = 1 + rt
        if 0.02 < abs(f) < 50: s2.loc[s2.index < d] *= f
    return s2
prices = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_2017*_202606*.parquet')))[-1]).replace(0,np.nan).apply(ba)
kc = pd.read_parquet(os.path.join(PROJ,'data_cache','kospi_yf.parquet')).iloc[:,0]
ma20=kc.rolling(20).mean(); ma80=kc.rolling(80).mean()
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
G3=('rev_z','oca_z','gp_growth_z',0.4,0.4,0.2)
def load(folder):
    ar,dates={}, []
    for f in sorted(glob.glob(os.path.join(PROJ,folder,'ranking_*.json'))):
        dt=os.path.basename(f)[8:16]
        if dt.isdigit() and len(dt)==8 and dt>='20190102': ar[dt]=json.load(open(f,encoding='utf-8'))['rankings']; dates.append(dt)
    return ar,sorted(dates)
def runbt(folder, sub, reg):
    ar,_=load(folder)
    t=TurboSimulator({d:ar[d] for d in sub}, sub, prices, overheat_w=0.2); t._use_overlay=True; t._use_stored_growth=True
    t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:])
    flat=list(t._cached_flat)
    r=_run_regime_inner(flat,flat,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    return r
def metrics_from_rets(rets):
    a=np.asarray(rets,dtype=float); n=len(a)
    if n==0: return 0,0,0
    eq=np.cumprod(1+a); cagr=(eq[-1]**(252/max(n,1))-1)*100
    peak=np.maximum.accumulate(eq); dd=(eq-peak)/peak; mdd=dd.min()*100
    cal=(cagr/abs(mdd)) if mdd<0 else 0
    return cal, cagr, mdd
def dd_window(dates, rets):
    a=np.asarray(rets,dtype=float); eq=np.cumprod(1+a); peak=np.maximum.accumulate(eq)
    dd=(eq-peak)/peak; ti=int(dd.argmin())
    pi=int(np.argmax(eq[:ti+1]))  # peak index before trough
    return dates[pi], dates[ti], dd[ti]*100
# --- run ---
_,dB=load('state'); _,dJ=load('state_1jo')
common=sorted(set(dB)&set(dJ)); reg=calc_reg(common)
print(f"[공통 {common[0]}~{common[-1]} {len(common)}일] 고정config V15Q0G55M30 12m E3X6S3\n")
rB=runbt('state',common,reg); rJ=runbt('state_1jo',common,reg)
retB=rB['_daily_rets']; retJ=rJ['_daily_rets']
print(f"  {'':12s}{'Calmar':>8s}{'CAGR':>8s}{'MDD':>8s}")
cB=metrics_from_rets(retB); cJ=metrics_from_rets(retJ)
print(f"  baseline1000억 {cB[0]:>7.2f}{cB[1]:>7.0f}%{cB[2]:>7.1f}%")
print(f"  1조+         {cJ[0]:>7.2f}{cJ[1]:>7.0f}%{cJ[2]:>7.1f}%\n")
# 연도별 분해
yrs=sorted(set(d[:4] for d in common))
print(f"  {'연도':6s}{'base Cal':>9s}{'base MDD':>9s}{'1조 Cal':>9s}{'1조 MDD':>9s}{'base수익':>9s}{'1조수익':>9s}")
for y in yrs:
    idx=[i for i,d in enumerate(common) if d[:4]==y]
    rb=[retB[i] for i in idx]; rj=[retJ[i] for i in idx]
    mb=metrics_from_rets(rb); mj=metrics_from_rets(rj)
    tb=(np.prod([1+x for x in rb])-1)*100; tj=(np.prod([1+x for x in rj])-1)*100
    print(f"  {y:6s}{mb[0]:>9.2f}{mb[1+1]:>8.1f}%{mj[0]:>9.2f}{mj[1+1]:>8.1f}%{tb:>8.1f}%{tj:>8.1f}%")
# 전체 MDD 발생 시점
pB,trB,ddB=dd_window(common,retB); pJ,trJ,ddJ=dd_window(common,retJ)
print(f"\n  최대낙폭 시점:")
print(f"    baseline: {pB}~{trB}  {ddB:.1f}%")
print(f"    1조+    : {pJ}~{trJ}  {ddJ:.1f}%")
