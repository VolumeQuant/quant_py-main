# -*- coding: utf-8 -*-
"""게이트3 BT — 과열캡 저점면제. production-faithful(recent_ca). baseline vs 순수면제 vs 회복확인면제."""
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
def exempt_flag(t,base_ts,confirm):
    d=cache.get(t)
    if d is None: return False
    s=d.get('ni') or d.get('ni2')
    if s is None: return False
    v=s[1][s[0]<=np.datetime64(base_ts)]
    if len(v)<8: return False
    ttm=v[-4:].sum(); N=min(12,len(v)); norm=v[-N:].mean()*4
    if norm<=0 or ttm/norm>=0.7: return False  # 저점 아님
    if confirm:  # 회복확인: 최신분기>직전분기 AND 직전>전전 (2분기 연속 순차개선)
        if not(len(v)>=3 and v[-1]>v[-2] and v[-2]>v[-3]): return False
    return True
# 면제 플래그 사전계산
def build_exempt(confirm):
    fl={}
    for dt in dates:
        ts=pd.Timestamp(dt[:4]+'-'+dt[4:6]+'-'+dt[6:])
        fl[dt]=set(r['ticker'] for r in ar[dt] if (r.get('overheat_pen') or 0)<0 and exempt_flag(r['ticker'],ts,confirm))
    return fl
def runbt(sub, exfl):
    reg=calc_reg(sub)
    t=TurboSimulator({d:ar[d] for d in sub},sub,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True
    for d in sub:
        tkn=t._preextracted[d][0]; fd={x['ticker']:x for x in ar[d]}; ex=exfl.get(d,set()) if exfl else set()
        t._overlay_pre[d]=np.array([0.2*(0 if tk in ex else (fd[tk].get('overheat_pen')or 0))+0.05*(fd[tk].get('mom_10_z')or 0)
                                    +0.06*(fd[tk].get('vol_low_z')or 0)-0.3*(fd[tk].get('recent_ca')or 0) for tk in tkn])
    t._cached_key=None; t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:]);flat=list(t._cached_flat)
    r=_run_regime_inner(flat,flat,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    return r.get('calmar',0),r.get('cagr',0)*100,r.get('mdd',0)*100
segs=[('전체',dates[0],dates[-1]),('19-21',dates[0],'20211231'),('22-23약세','20220101','20231231'),('24-26','20240101',dates[-1])]
def show(nm,exfl):
    o=[runbt([d for d in dates if lo<=d<=hi],exfl) for _,lo,hi in segs]
    print(f"  {nm:22s} 전체{o[0][0]:>5.2f} 19-21 {o[1][0]:>5.2f} 약세 {o[2][0]:>5.2f} 24-26 {o[3][0]:>6.2f} MDD{o[0][2]:>6.1f}%")
print(f"[게이트3: 과열캡 저점면제 BT]\n  {'config':22s} {'전체':>7s} {'19-21':>8s} {'약세':>7s} {'24-26':>8s}")
show('baseline', None)
exn=build_exempt(False); print(f"  (순수면제 발동 {sum(len(v) for v in exn.values())}건)")
show('순수 저점면제', exn)
exc=build_exempt(True); print(f"  (회복확인면제 발동 {sum(len(v) for v in exc.values())}건)")
show('회복확인 저점면제', exc)
