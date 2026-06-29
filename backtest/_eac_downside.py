# -*- coding: utf-8 -*-
"""Step3c clean — 성장꺼짐 하방페널티: 고후행성장 & 이익감속(EAC<0) → 성장×배수. (스태그네이션 함정 회피)"""
import sys, io, os, glob, json, pickle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
kc=pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:,0];ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
G3=('rev_z','oca_z','gp_growth_z',0.4,0.4,0.2)
cache=pickle.load(open(P+'/backtest/_earn_cache.pkl','rb'))
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
orig_g={dt:[(r.get('growth_s')or 0.0) for r in ar[dt]] for dt in dates}
def eac(t,base_ts):
    d=cache.get(t)
    if d is None or 'op' not in d: return None
    op=d['op'][1][d['op'][0]<=np.datetime64(base_ts)]
    rev=d['rev'][1][d['rev'][0]<=np.datetime64(base_ts)] if 'rev' in d else None
    if len(op)<6: return None
    dnow=op[-4:].sum()-op[-5:-1].sum(); dprev=op[-5:-1].sum()-op[-6:-2].sum()
    floor=abs(rev[-4:].sum())*0.02 if (rev is not None and len(rev)>=4) else 1
    return (dnow-dprev)/max(abs(op[-5:-1].sum()),floor,1)
eacv={}
for dt in dates:
    ts=pd.Timestamp(dt[:4]+'-'+dt[4:6]+'-'+dt[6:])
    eacv[dt]={r['ticker']:eac(r['ticker'],ts) for r in ar[dt]}
def setpen(Wpen,gthr,ethr):
    for dt in dates:
        og=orig_g[dt]; ev=eacv[dt]
        for j,r in enumerate(ar[dt]):
            g=og[j]; z=ev.get(r['ticker'])
            r['growth_s']= g*Wpen if (g>gthr and z is not None and z<ethr) else g
def runbt(sub):
    reg=calc_reg(sub)
    t=TurboSimulator({d:ar[d] for d in sub},sub,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True
    for d in sub:
        tkn=t._preextracted[d][0]; fd={x['ticker']:x for x in ar[d]}
        t._overlay_pre[d]=np.array([0.2*(fd[tk].get('overheat_pen')or 0)+0.05*(fd[tk].get('mom_10_z')or 0)+0.06*(fd[tk].get('vol_low_z')or 0)-0.3*(fd[tk].get('recent_ca')or 0) for tk in tkn])
    t._cached_key=None; t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:]);flat=list(t._cached_flat)
    r=_run_regime_inner(flat,flat,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    return r.get('calmar',0),r.get('cagr',0)*100,r.get('mdd',0)*100
segs=[('전체',dates[0],dates[-1]),('19-21',dates[0],'20211231'),('22-23약세','20220101','20231231'),('24-26','20240101',dates[-1])]
def show(nm,Wpen,gthr,ethr):
    setpen(Wpen,gthr,ethr); cnt=sum(1 for dt in dates for j,r in enumerate(ar[dt]) if orig_g[dt][j]>gthr and (eacv[dt].get(r['ticker']) or 9)<ethr)
    o=[runbt([d for d in dates if lo<=d<=hi]) for _,lo,hi in segs]
    print(f"  {nm:30s} 전체{o[0][0]:>5.2f} 19-21 {o[1][0]:>5.2f} 약세 {o[2][0]:>5.2f} 24-26 {o[3][0]:>6.2f} (발동{cnt})")
print(f"[Step3c clean: 성장꺼짐 하방페널티]\n  {'config':30s} {'전체':>7s} {'19-21':>8s} {'약세':>7s} {'24-26':>8s}")
show('baseline',1.0,99,-99)
show('g>1.0 & EAC<-0.5 ×0.5',0.5,1.0,-0.5)
show('g>1.0 & EAC<0 ×0.5',0.5,1.0,0.0)
show('g>0.5 & EAC<-0.3 ×0.4',0.4,0.5,-0.3)
