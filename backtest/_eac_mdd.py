# -*- coding: utf-8 -*-
"""약세장 게이트=현금 검증 — 2022-23 boost/cash 비율 + EAC의 전체 MDD·최대낙폭 시점."""
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
reg=calc_reg(dates)
# 2022-23 boost/defense 비율
b2=sum(1 for d in dates if '20220101'<=d<='20231231' and reg[d]); c2=sum(1 for d in dates if '20220101'<=d<='20231231' and not reg[d])
print(f"[2022-23] boost(매수) {b2}일 / defense(현금) {c2}일 = 현금비율 {c2/(b2+c2)*100:.0f}%")
print(f"[전체] boost {sum(reg.values())}일 / defense {sum(1 for v in reg.values() if not v)}일")
def eac(t,base_ts):
    d=cache.get(t)
    if d is None or 'op' not in d: return None
    op=d['op'][1][d['op'][0]<=np.datetime64(base_ts)]
    rev=d['rev'][1][d['rev'][0]<=np.datetime64(base_ts)] if 'rev' in d else None
    if len(op)<6: return None
    dnow=op[-4:].sum()-op[-5:-1].sum(); dprev=op[-5:-1].sum()-op[-6:-2].sum()
    floor=abs(rev[-4:].sum())*0.02 if (rev is not None and len(rev)>=4) else 1
    return (dnow-dprev)/max(abs(op[-5:-1].sum()),floor,1)
eacz={}
for dt in dates:
    ts=pd.Timestamp(dt[:4]+'-'+dt[4:6]+'-'+dt[6:]); vals={r['ticker']:eac(r['ticker'],ts) for r in ar[dt]}
    v=np.array([x for x in vals.values() if x is not None])
    if len(v)>=20:
        m,s=np.median(v),((np.percentile(v,84)-np.percentile(v,16))/2) or 1
        eacz[dt]={tk:float(np.clip((x-m)/s,-3,3)) if x is not None else 0.0 for tk,x in vals.items()}
    else: eacz[dt]={}
def run(W):
    t=TurboSimulator({d:ar[d] for d in dates},dates,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True
    for d in dates:
        tkn=t._preextracted[d][0]; fd={x['ticker']:x for x in ar[d]}; ez=eacz.get(d,{})
        t._overlay_pre[d]=np.array([0.2*(fd[tk].get('overheat_pen')or 0)+0.05*(fd[tk].get('mom_10_z')or 0)+0.06*(fd[tk].get('vol_low_z')or 0)-0.3*(fd[tk].get('recent_ca')or 0)+W*max(ez.get(tk,0.0),0) for tk in tkn])
    t._cached_key=None; t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:]);flat=list(t._cached_flat)
    r=_run_regime_inner(flat,flat,0,6,3,3,6,3,reg,dates,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(dates),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    a=np.asarray(r['_daily_rets'],float);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);dd=(eq-peak)/peak
    ti=int(dd.argmin());pi=int(np.argmax(eq[:ti+1]))
    return r.get('calmar',0),r.get('cagr',0)*100,dd.min()*100,dates[pi],dates[ti]
for W in [0,0.05,0.10]:
    cal,cagr,mdd,pk,tr=run(W)
    print(f"  EAC ×{W}: 전체Calmar {cal:.2f} CAGR {cagr:.0f}% MDD {mdd:.1f}% (최대낙폭 {pk}~{tr})")
