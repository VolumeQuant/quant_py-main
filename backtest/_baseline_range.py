# -*- coding: utf-8 -*-
"""baseline state/ Calmar을 날짜범위별로 — 2.71(0624) vs 0616 vs 0531. 최근폭락 기여 확인."""
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
ar={}; dates=[]
for f in sorted(glob.glob(os.path.join(PROJ,'state','ranking_*.json'))):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102':
        ar[dt]=json.load(open(f,encoding='utf-8'))['rankings']; dates.append(dt)
dates=sorted(dates)
def runbt(sub):
    reg=calc_reg(sub)
    t=TurboSimulator({d:ar[d] for d in sub}, sub, prices, overheat_w=0.2); t._use_overlay=True; t._use_stored_growth=True
    t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:])
    flat=list(t._cached_flat)
    r=_run_regime_inner(flat,flat,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    a=np.asarray(r['_daily_rets'],float); eq=np.cumprod(1+a); peak=np.maximum.accumulate(eq); dd=(eq-peak)/peak
    n=len(a); cagr=(eq[-1]**(252/max(n,1))-1)*100; mdd=dd.min()*100; cal=cagr/abs(mdd) if mdd<0 else 0
    ti=int(dd.argmin()); pi=int(np.argmax(eq[:ti+1]))
    return cal,cagr,mdd,sub[pi],sub[ti]
for cut in ['20260531','20260616','20260624']:
    sub=[d for d in dates if d<=cut]
    cal,cagr,mdd,pk,tr=runbt(sub)
    print(f"  ~{cut} ({len(sub)}일): Calmar {cal:.2f}  CAGR {cagr:.0f}%  MDD {mdd:.1f}%  (최대낙폭 {pk}~{tr})")
