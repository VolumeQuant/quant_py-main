# -*- coding: utf-8 -*-
"""lumpiness 권위 재검증 — _corpoff_compare.py harness 그대로(adj 가격 + recent_ca 오버레이).
현재 state(lumpiness ON) vs lumpiness un-apply(flagged growth /0.3) baseline."""
import sys, io, os, glob, json, pickle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices = pd.read_parquet(sorted(glob.glob(P + '/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
kc = pd.read_parquet(P + '/data_cache/kospi_yf.parquet').iloc[:, 0]; ma20=kc.rolling(20).mean(); ma80=kc.rolling(80).mean()
G3 = ('rev_z','oca_z','gp_growth_z',0.4,0.4,0.2)
def calc_reg(ds):
    reg={};md=True;stk=0;ss=None
    for d in ds:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md;continue
        s=bool(ma20[ts]>ma80[ts]); stk=stk+1 if s==ss else 1; ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
ar={};dates=[]
for f in sorted(glob.glob(os.path.join(P,'state','ranking_*.json'))):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102': ar[dt]=json.load(open(f,encoding='utf-8'))['rankings'];dates.append(dt)
dates=sorted(dates)
stored_g={dt:[(r.get('growth_s')or 0.0) for r in ar[dt]] for dt in dates}
tks=pickle.load(open(P+'/_lump_tickers.pkl','rb'));qser={}
for tk in tks:
    p=os.path.join(P,'data_cache',f'fs_dart_{tk}.parquet')
    if not os.path.exists(p): continue
    d=pd.read_parquet(p);q=d[(d['공시구분']=='q')&(d['계정']=='매출액')].copy()
    q['rcept_dt']=pd.to_datetime(q['rcept_dt'],errors='coerce');q=q.dropna(subset=['rcept_dt']).sort_values('rcept_dt')
    if len(q)>=8: qser[tk]=(q['rcept_dt'].values,q['값'].astype(float).values)
def flagged(tk,ts):
    s=qser.get(tk)
    if s is None: return False
    v=s[1][s[0]<=np.datetime64(ts)]
    if len(v)<8 or (v[-8:]<=0).any(): return False
    l4=v[-4:];return l4.min()/l4.max()<0.25
fl={dt:set(r['ticker'] for r in ar[dt] if flagged(r['ticker'],pd.Timestamp(dt[:4]+'-'+dt[4:6]+'-'+dt[6:]))) for dt in dates}
def setg(mode):
    for dt in dates:
        sg=stored_g[dt]
        for j,r in enumerate(ar[dt]):
            g=sg[j]
            if mode=='base' and r['ticker'] in fl[dt]: g=g/0.3
            r['growth_s']=g
def runbt(sub):
    reg=calc_reg(sub)
    t=TurboSimulator({d:ar[d] for d in sub},sub,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True
    for d in sub:  # recent_ca 오버레이 (그들 harness 정합)
        tkn=t._preextracted[d][0]; fd={x['ticker']:x for x in ar[d]}
        t._overlay_pre[d]=np.array([0.2*(fd[tk].get('overheat_pen')or 0)+0.05*(fd[tk].get('mom_10_z')or 0)
                                    +0.06*(fd[tk].get('vol_low_z')or 0)-0.3*(fd[tk].get('recent_ca')or 0) for tk in tkn])
    t._cached_key=None; t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:]);flat=list(t._cached_flat)
    r=_run_regime_inner(flat,flat,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    return r.get('calmar',0),r.get('cagr',0)*100,r.get('mdd',0)*100
print(f"[권위 재검증: adj가격+recent_ca 오버레이] {dates[0]}~{dates[-1]} {len(dates)}일\n")
print(f"  {'구간':10s}{'base Cal':>9s}{'lump Cal':>9s}{'ΔCal':>7s}{'base MDD':>10s}{'lump MDD':>10s}")
for nm,lo,hi in [('전체',dates[0],dates[-1]),('19-21',dates[0],'20211231'),('22-23약세','20220101','20231231'),('24-26','20240101',dates[-1])]:
    sub=[d for d in dates if lo<=d<=hi]
    setg('base');b=runbt(sub); setg('lump');l=runbt(sub)
    print(f"  {nm:10s}{b[0]:>9.3f}{l[0]:>9.3f}{l[0]-b[0]:>+7.3f}{b[2]:>9.1f}%{l[2]:>9.1f}%")
