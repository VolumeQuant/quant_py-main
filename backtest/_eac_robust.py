# -*- coding: utf-8 -*-
"""EAC ×0.10 견고성 — 연도별 WF + LOWO(최다 rank<=3 종목 제외). 과적합(2026/SK하이닉스 집중)인지 결판."""
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
ar={};dates=[];nm={}
for f in sorted(glob.glob(P+'/state/ranking_*.json')):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102':
        rs=json.load(open(f,encoding='utf-8'))['rankings']; ar[dt]=rs; dates.append(dt)
        for x in rs: nm[x['ticker']]=x['name']
dates=sorted(dates); reg=calc_reg(dates)
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
def run(sub,W,excl=None):
    arx={d:[r for r in ar[d] if r['ticker']!=excl] for d in sub} if excl else {d:ar[d] for d in sub}
    t=TurboSimulator(arx,sub,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True
    for d in sub:
        tkn=t._preextracted[d][0]; fd={x['ticker']:x for x in arx[d]}; ez=eacz.get(d,{})
        t._overlay_pre[d]=np.array([0.2*(fd[tk].get('overheat_pen')or 0)+0.05*(fd[tk].get('mom_10_z')or 0)+0.06*(fd[tk].get('vol_low_z')or 0)-0.3*(fd[tk].get('recent_ca')or 0)+W*max(ez.get(tk,0.0),0) for tk in tkn])
    t._cached_key=None; t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:]);flat=list(t._cached_flat)
    r=_run_regime_inner(flat,flat,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    return r.get('calmar',0)
print("=== 연도별 WF (baseline vs EAC×0.10) ===")
for y in ['2019','2020','2021','2022','2023','2024','2025','2026']:
    sub=[d for d in dates if d[:4]==y]
    if len(sub)<30: continue
    b=run(sub,0); e=run(sub,0.10); print(f"  {y}: base {b:>5.2f} / EAC {e:>5.2f}  Δ{e-b:>+5.2f}")
print("\n=== LOWO (rank<=3 최다종목 제외, 전체) ===")
cnt={}
for d in dates:
    for r in ar[d]:
        if r.get('rank',99)<=3: cnt[r['ticker']]=cnt.get(r['ticker'],0)+1
top=sorted(cnt,key=lambda t:-cnt[t])[:5]
bF=run(dates,0); eF=run(dates,0.10); print(f"  [전체] base {bF:.2f} / EAC {eF:.2f}  Δ{eF-bF:+.2f}")
for t in top:
    print(f"  -{nm.get(t,t)[:9]:9s}: base {run(dates,0,t):.2f} / EAC {run(dates,0.10,t):.2f}  Δ{run(dates,0.10,t)-run(dates,0,t):+.2f}")
