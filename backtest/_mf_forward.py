# -*- coding: utf-8 -*-
"""멀티팩터에 선행성장 팩터 추가 (look-ahead 상한) — production 가중에 W×fwd_growth_z 가산, W sweep.
완벽신호로도 production(4.24) 개선되나? 안 되면 = 기존 팩터가 이미 잡음."""
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
tdays=[d.strftime('%Y%m%d') for d in prices.index]; tdi={d:i for i,d in enumerate(tdays)}
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
def ttm_at(t,d):
    dd=cache.get(t)
    if dd is None: return None
    s=dd.get('ni') or dd.get('ni2')
    if s is None: return None
    v=s[1][s[0]<=np.datetime64(pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]))]
    return v[-4:].sum() if len(v)>=4 else None
# fwd 12m 실현 이익성장 z (look-ahead) — 일별 단면
fwz={}
for d in dates:
    i=tdi.get(d); d1=tdays[min(i+250,len(tdays)-1)] if i is not None else d
    vals={}
    for r in ar[d]:
        e0=ttm_at(r['ticker'],d); e1=ttm_at(r['ticker'],d1)
        vals[r['ticker']]= (e1/e0-1) if (e0 and e0>0 and e1 is not None) else None
    v=np.array([x for x in vals.values() if x is not None])
    if len(v)>=20:
        m,s=np.median(v),((np.percentile(v,84)-np.percentile(v,16))/2) or 1
        fwz[d]={tk:float(np.clip((x-m)/s,-3,3)) if x is not None else 0.0 for tk,x in vals.items()}
    else: fwz[d]={}
def runbt(sub,W):
    reg=calc_reg(sub)
    t=TurboSimulator({d:ar[d] for d in sub},sub,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True
    for d in sub:
        tkn=t._preextracted[d][0]; fd={x['ticker']:x for x in ar[d]}; fz=fwz.get(d,{})
        t._overlay_pre[d]=np.array([0.2*(fd[tk].get('overheat_pen')or 0)+0.05*(fd[tk].get('mom_10_z')or 0)+0.06*(fd[tk].get('vol_low_z')or 0)-0.3*(fd[tk].get('recent_ca')or 0)+W*fz.get(tk,0.0) for tk in tkn])
    t._cached_key=None; t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:]);flat=list(t._cached_flat)
    r=_run_regime_inner(flat,flat,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    a=np.asarray(r['_daily_rets'],float);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return r.get('calmar',0),cagr,mdd
segs=[('전체',dates[0],dates[-1]),('19-21',dates[0],'20211231'),('22-23약세','20220101','20231231'),('24-26','20240101',dates[-1])]
def show(W):
    o=[runbt([d for d in dates if lo<=d<=hi],W) for _,lo,hi in segs]
    tag='baseline' if W==0 else f'+선행성장z ×{W}'
    print(f"  {tag:22s} 전체{o[0][0]:>5.2f} 19-21 {o[1][0]:>5.2f} 약세 {o[2][0]:>5.2f} 24-26 {o[3][0]:>6.2f} MDD{o[0][2]:>6.1f}%")
print(f"[멀티팩터 + 선행성장 팩터 (look-ahead 상한)]\n  {'config':22s} {'전체':>7s} {'19-21':>8s} {'약세':>7s} {'24-26':>8s}")
for W in [0,0.05,0.10,0.20,0.35]:
    show(W)

# === 선행성장을 G 팩터에 블렌딩 (별도 얹기 아님) ===
def zday(d, valmap):
    v=np.array([x for x in valmap.values() if x is not None and not np.isnan(x)])
    if len(v)<10: return {k:0.0 for k in valmap}
    m,s=v.mean(),v.std() or 1
    return {k:((x-m)/s if (x is not None and not np.isnan(x)) else 0.0) for k,x in valmap.items()}
orig_g={d:{r['ticker']:(r.get('growth_s')or 0.0) for r in ar[d]} for d in dates}
def runbt_G(sub,f,into='G'):
    reg=calc_reg(sub)
    # growth_s를 블렌드로 교체 (into='G') 또는 value에 (into='V')
    for d in sub:
        fz=fwz.get(d,{})
        if into=='G':
            blend={r['ticker']: (1-f)*orig_g[d][r['ticker']] + f*fz.get(r['ticker'],0.0) for r in ar[d]}
            zb=zday(d,blend)
            for r in ar[d]: r['growth_s']=zb[r['ticker']]
    t=TurboSimulator({d:ar[d] for d in sub},sub,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True
    for d in sub:
        tkn=t._preextracted[d][0]; fd={x['ticker']:x for x in ar[d]}; fz=fwz.get(d,{})
        vadd=lambda tk: (f*fz.get(tk,0.0)) if into=='V' else 0.0  # V에 넣을 땐 value쪽 가산
        t._overlay_pre[d]=np.array([0.2*(fd[tk].get('overheat_pen')or 0)+0.05*(fd[tk].get('mom_10_z')or 0)+0.06*(fd[tk].get('vol_low_z')or 0)-0.3*(fd[tk].get('recent_ca')or 0)+vadd(tk) for tk in tkn])
    t._cached_key=None; t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:]);flat=list(t._cached_flat)
    res=_run_regime_inner(flat,flat,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    a=np.asarray(res['_daily_rets'],float);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    cal=res.get('calmar',0)
    for d in sub:  # 복원
        for rr in ar[d]: rr['growth_s']=orig_g[d][rr['ticker']]
    return cal,cagr,mdd
def showG(f,into):
    o=[runbt_G([d for d in dates if lo<=d<=hi],f,into) for _,lo,hi in segs]
    print(f"  {into}블렌드 f={f:<4}      전체{o[0][0]:>5.2f} 19-21 {o[1][0]:>5.2f} 약세 {o[2][0]:>5.2f} 24-26 {o[3][0]:>6.2f}")
print(f"\n[선행성장을 G 팩터에 블렌딩 (제대로)]\n  {'config':22s} {'전체':>7s} {'19-21':>8s} {'약세':>7s} {'24-26':>8s}")
for f in [0.1,0.2,0.3,0.5]:
    showG(f,'G')
