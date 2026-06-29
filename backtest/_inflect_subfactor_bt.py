# -*- coding: utf-8 -*-
"""Step3a — 미사용 인플렉션 서브팩터(op_margin/rev_accel/cfo)를 보너스항으로 추가 BT.
production-faithful(recent_ca). 저장 z 사용, 재생성 불필요. 표본(상관)+BT 동시."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
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
# 표본: 서브팩터 가용성·분포
cov={k:0 for k in ['rev_accel_z','op_margin_z','cfo_growth_z']}
tot=0
for dt in dates[::20]:
    for r in ar[dt]:
        tot+=1
        for k in cov:
            if r.get(k) is not None and abs(r.get(k) or 0)>1e-9: cov[k]+=1
print("[표본] 서브팩터 비결측 비율:", {k:f'{v/tot*100:.0f}%' for k,v in cov.items()})
def runbt(sub, bonus):
    reg=calc_reg(sub)
    t=TurboSimulator({d:ar[d] for d in sub},sub,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True
    for d in sub:
        tkn=t._preextracted[d][0]; fd={x['ticker']:x for x in ar[d]}
        base=lambda tk: 0.2*(fd[tk].get('overheat_pen')or 0)+0.05*(fd[tk].get('mom_10_z')or 0)+0.06*(fd[tk].get('vol_low_z')or 0)-0.3*(fd[tk].get('recent_ca')or 0)
        add=lambda tk: sum(w*(fd[tk].get(k)or 0) for k,w in bonus.items()) if bonus else 0
        t._overlay_pre[d]=np.array([base(tk)+add(tk) for tk in tkn])
    t._cached_key=None; t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:]);flat=list(t._cached_flat)
    r=_run_regime_inner(flat,flat,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    return r.get('calmar',0),r.get('cagr',0)*100,r.get('mdd',0)*100
segs=[('전체',dates[0],dates[-1]),('19-21',dates[0],'20211231'),('22-23약세','20220101','20231231'),('24-26','20240101',dates[-1])]
def show(nm,bonus):
    o=[runbt([d for d in dates if lo<=d<=hi],bonus) for _,lo,hi in segs]
    print(f"  {nm:26s} 전체{o[0][0]:>5.2f} 19-21 {o[1][0]:>5.2f} 약세 {o[2][0]:>5.2f} 24-26 {o[3][0]:>6.2f} MDD{o[0][2]:>6.1f}%")
print(f"\n[Step3a BT: 인플렉션 서브팩터 보너스]\n  {'config':26s} {'전체':>7s} {'19-21':>8s} {'약세':>7s} {'24-26':>8s}")
show('baseline', None)
for k in ['op_margin_z','rev_accel_z','cfo_growth_z']:
    for w in [0.05,0.10]:
        show(f'+{k} ×{w}', {k:w})
