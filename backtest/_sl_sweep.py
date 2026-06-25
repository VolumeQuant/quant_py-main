# -*- coding: utf-8 -*-
"""개선포인트② SL/트레일링 재검토 (EXIT_RANK=6 환경). production-faithful harness, 현재 state.
baseline(None) vs SL/TS 여러값. 전체+WF. 느린출혈 잡으면서 승자 안 깎나."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices = pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
kc=pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:,0];ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
G3=('rev_z','oca_z','gp_growth_z',0.4,0.4,0.2)
def calc_reg(ds):
    reg={};md=True;stk=0;ss=None
    for d in ds:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md;continue
        s=bool(ma20[ts]>ma80[ts]);stk=stk+1 if s==ss else 1;ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
ar={};dates=[]
for f in sorted(glob.glob(P+'/state/ranking_*.json')):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102': ar[dt]=json.load(open(f,encoding='utf-8'))['rankings'];dates.append(dt)
dates=sorted(dates)
def runbt(sub, sl=None, ts=None):
    reg=calc_reg(sub)
    t=TurboSimulator({d:ar[d] for d in sub},sub,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True
    for d in sub:
        tkn=t._preextracted[d][0]; fd={x['ticker']:x for x in ar[d]}
        t._overlay_pre[d]=np.array([0.2*(fd[tk].get('overheat_pen')or 0)+0.05*(fd[tk].get('mom_10_z')or 0)
                                    +0.06*(fd[tk].get('vol_low_z')or 0)-0.3*(fd[tk].get('recent_ca')or 0) for tk in tkn])
    t._cached_key=None; t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:]);flat=list(t._cached_flat)
    r=_run_regime_inner(flat,flat,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),
                        None,None,None,None,stop_loss_o=sl,trailing_stop_o=ts,stop_loss_d=None,trailing_stop_d=None)
    return r.get('calmar',0),r.get('cagr',0)*100,r.get('mdd',0)*100
segs=[('전체',dates[0],dates[-1]),('19-21',dates[0],'20211231'),('22-23약세','20220101','20231231'),('24-26','20240101',dates[-1])]
def line(nm,sl,ts):
    out=[]
    for _,lo,hi in segs:
        sub=[d for d in dates if lo<=d<=hi]; out.append(runbt(sub,sl,ts))
    mdd_full=out[0][2]
    print(f"  {nm:16s} Cal전체 {out[0][0]:>5.2f}  19-21 {out[1][0]:>5.2f}  약세 {out[2][0]:>5.2f}  24-26 {out[3][0]:>6.2f}  MDD {mdd_full:>6.1f}%  CAGR {out[0][1]:.0f}%")
print(f"[개선포인트② SL/TS 재검토] {dates[0]}~{dates[-1]}\n")
print(f"  {'config':16s} {'Cal전체':>9s}  {'19-21':>7s}  {'약세':>6s}  {'24-26':>7s}  {'MDD':>8s}")
line('baseline(없음)',None,None)
line('SL -10%',-0.10,None)
line('SL -15%',-0.15,None)
line('SL -20%',-0.20,None)
line('TS -8%',None,-0.08)
line('TS -15%',None,-0.15)
line('SL-15+TS-15',-0.15,-0.15)
