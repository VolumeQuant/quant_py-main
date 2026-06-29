# -*- coding: utf-8 -*-
"""production vs 선행성장 sleeve 다지표 비교 — Sharpe/Sortino/Calmar/연도별/상관/결합. Calmar 단일 불안정 보완."""
import sys, io, os, glob, json, pickle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(prices.columns)};parr=prices.values
tdays=[d.strftime('%Y%m%d') for d in prices.index];tdi={d:i for i,d in enumerate(tdays)}
kc=pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:,0];ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
cache=pickle.load(open(P+'/backtest/_earn_cache.pkl','rb'));tks=list(cache.keys())
win=[d for d in tdays if '20190102'<=d<='20260624']
def reg_s(ds):
    reg={};md=True;stk=0;ss=None
    for d in ds:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md;continue
        s=bool(ma20[ts]>ma80[ts]);stk=stk+1 if s==ss else 1;ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
# production 일별수익
ar={};pdates=[]
for f in sorted(glob.glob(P+'/state/ranking_*.json')):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102': ar[dt]=json.load(open(f,encoding='utf-8'))['rankings'];pdates.append(dt)
pdates=sorted(pdates);regp=reg_s(pdates);G3=('rev_z','oca_z','gp_growth_z',0.4,0.4,0.2)
t=TurboSimulator({d:ar[d] for d in pdates},pdates,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True
for d in pdates:
    tkn=t._preextracted[d][0];fd={x['ticker']:x for x in ar[d]}
    t._overlay_pre[d]=np.array([0.2*(fd[tk].get('overheat_pen')or 0)+0.05*(fd[tk].get('mom_10_z')or 0)+0.06*(fd[tk].get('vol_low_z')or 0)-0.3*(fd[tk].get('recent_ca')or 0) for tk in tkn])
t._cached_key=None;t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:]);flat=list(t._cached_flat)
rp=_run_regime_inner(flat,flat,0,6,3,3,6,3,regp,pdates,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(pdates),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
prod=pd.Series(rp['_daily_rets'],index=pdates)
# sleeve 일별수익 (순수 선행성장 N20)
reg=reg_s(win)
def ttm(t_,d):
    dd=cache.get(t_);s=dd.get('ni') or dd.get('ni2') if dd else None
    if s is None: return None
    v=s[1][s[0]<=np.datetime64(pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]))];return v[-4:].sum() if len(v)>=4 else None
rb=[];seen=set()
for d in win:
    if d[:6] not in seen: seen.add(d[:6]);rb.append(d)
rbset={}
for d in rb:
    i=tdi[d];d1=tdays[min(i+250,len(tdays)-1)];cand=[]
    for tk in tks:
        if tk not in pcol: continue
        p0=parr[i,pcol[tk]]
        if not(p0>0): continue
        e0=ttm(tk,d);e1=ttm(tk,d1)
        if e0 and e0>0 and e1 is not None: cand.append((tk,e1/e0-1))
    if len(cand)>=30:
        a=pd.DataFrame(cand,columns=['t','fwd']).sort_values('fwd',ascending=False);rbset[d]=a.head(20)['t'].tolist()
held=[];sl=[];prev=None
for d in win:
    r=0.0
    if held and prev:
        rs=[parr[tdi[d],pcol[tk]]/parr[tdi[prev],pcol[tk]]-1 for tk in held if parr[tdi[prev],pcol[tk]]>0 and parr[tdi[d],pcol[tk]]>0]
        r=float(np.mean(rs)) if rs else 0.0
    sl.append(r)
    if not reg.get(d,True): held=[]
    elif d in rbset: held=rbset[d]
    prev=d
sleeve=pd.Series(sl,index=win)
def metrics(s):
    a=s.values;eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100
    n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100;sh=a.mean()/(a.std() or 1)*np.sqrt(252)
    dn=a[a<0];so=a.mean()/(dn.std() or 1)*np.sqrt(252)
    cal=cagr/abs(mdd) if mdd<0 else 0;wr=(a>0).mean()*100
    return cagr,mdd,cal,sh,so,wr
idx=prod.index.intersection(sleeve.index)
p,s=prod[idx],sleeve[idx];combo=0.5*p+0.5*s
print(f"  {'전략':16s}{'CAGR':>7s}{'MDD':>8s}{'Calmar':>7s}{'Sharpe':>7s}{'Sortino':>8s}{'승률':>6s}")
for nm,x in [('production',p),('선행성장 sleeve',s),('50:50 결합',combo)]:
    c,m,cal,sh,so,wr=metrics(x); print(f"  {nm:16s}{c:>6.0f}%{m:>7.1f}%{cal:>7.2f}{sh:>7.2f}{so:>8.2f}{wr:>5.0f}%")
print(f"\n  [상관] production vs sleeve 일별: {p.corr(s):+.3f}")
print("\n=== 연도별 수익률 (안정성) ===")
for y in ['2019','2020','2021','2022','2023','2024','2025','2026']:
    py=[i for i in idx if i[:4]==y]
    if len(py)<30: continue
    rp_=(np.prod([1+p[i] for i in py])-1)*100; rs_=(np.prod([1+s[i] for i in py])-1)*100; rc_=(np.prod([1+combo[i] for i in py])-1)*100
    print(f"  {y}: prod {rp_:>+6.0f}% / sleeve {rs_:>+6.0f}% / 결합 {rc_:>+6.0f}%")
