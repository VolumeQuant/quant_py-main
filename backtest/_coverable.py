# -*- coding: utf-8 -*-
"""sleeve 조회불가(NTM 미커버) 종목 매수제외 테스트 — production 중 커버종목만 매수. ★NTM 245=현재커버 프록시."""
import sys, io, os, glob, json, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
kc=pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:,0];ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
G3=('rev_z','oca_z','gp_growth_z',0.4,0.4,0.2)
# NTM 커버 종목 (현재 245, 프록시)
c=sqlite3.connect(P+'/kr_eps_momentum/eps_momentum_data_kr.db')
cover=set(r[0][:6] for r in c.execute("SELECT DISTINCT ticker FROM ntm_screening"))
print(f"NTM 커버 종목 {len(cover)}개 (프록시). 제주(080220) 커버? {'080220' in cover}  디바이스(187870)? {'187870' in cover}")
ar={};dates=[]
for f in sorted(glob.glob(P+'/state/ranking_*.json')):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102': ar[dt]=json.load(open(f,encoding='utf-8'))['rankings'];dates.append(dt)
dates=sorted(dates)
def calc_reg(ds):
    reg={};md=True;stk=0;ss=None
    for d in ds:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md;continue
        s=bool(ma20[ts]>ma80[ts]);stk=stk+1 if s==ss else 1;ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
orig_g={d:[(r.get('growth_s')or 0.0) for r in ar[d]] for d in dates}
def runbt(sub, coveronly):
    reg=calc_reg(sub)
    # 커버 안 된 종목 growth_s = -9 (사실상 제외) → 랭킹서 밀림
    for d in sub:
        og=orig_g[d]
        for j,r in enumerate(ar[d]):
            r['growth_s']= (-9.0 if (coveronly and r['ticker'] not in cover) else og[j])
    t=TurboSimulator({d:ar[d] for d in sub},sub,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True
    for d in sub:
        tkn=t._preextracted[d][0];fd={x['ticker']:x for x in ar[d]}
        t._overlay_pre[d]=np.array([0.2*(fd[tk].get('overheat_pen')or 0)+0.05*(fd[tk].get('mom_10_z')or 0)+0.06*(fd[tk].get('vol_low_z')or 0)-0.3*(fd[tk].get('recent_ca')or 0) for tk in tkn])
    t._cached_key=None;t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:]);flat=list(t._cached_flat)
    res=_run_regime_inner(flat,flat,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    a=np.asarray(res['_daily_rets'],float);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    cal=res.get('calmar',0);sh=a.mean()/(a.std() or 1)*np.sqrt(252)
    for d in sub:
        for j,r in enumerate(ar[d]): r['growth_s']=orig_g[d][j]
    return cal,cagr,mdd,sh
segs=[('전체',dates[0],dates[-1]),('19-21',dates[0],'20211231'),('22-23약세','20220101','20231231'),('24-26','20240101',dates[-1])]
print(f"\n  {'config':18s}{'전체Cal':>8s}{'CAGR':>7s}{'MDD':>8s}{'Sharpe':>7s}  구간별Cal(19-21/약세/24-26)")
for nm,co in [('baseline(전부매수)',False),('커버종목만 매수',True)]:
    o=[runbt([d for d in dates if lo<=d<=hi],co) for _,lo,hi in segs]
    print(f"  {nm:18s}{o[0][0]:>8.2f}{o[0][1]:>6.0f}%{o[0][2]:>7.1f}%{o[0][3]:>7.2f}   {o[1][0]:.2f}/{o[2][0]:.2f}/{o[3][0]:.2f}")
