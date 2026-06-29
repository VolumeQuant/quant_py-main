# -*- coding: utf-8 -*-
"""직교화 sleeve — 선행성장을 V/Q/G/M에 회귀 후 잔차(순수증분)로 sleeve. raw vs 직교화 + production 블렌드.
같은 state 유니버스. ★fwd=look-ahead."""
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
cache=pickle.load(open(P+'/backtest/_earn_cache.pkl','rb'))
ar={};dts=[]
for f in sorted(glob.glob(P+'/state/ranking_*.json')):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102': ar[dt]=json.load(open(f,encoding='utf-8'))['rankings'];dts.append(dt)
dts=sorted(dts);win=[d for d in tdays if dts[0]<=d<=dts[-1]]
def reg_s(ds):
    reg={};md=True;stk=0;ss=None
    for d in ds:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md;continue
        s=bool(ma20[ts]>ma80[ts]);stk=stk+1 if s==ss else 1;ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
reg=reg_s(win)
def ttm(t,d):
    dd=cache.get(t);s=dd.get('ni') or dd.get('ni2') if dd else None
    if s is None: return None
    v=s[1][s[0]<=np.datetime64(pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]))];return v[-4:].sum() if len(v)>=4 else None
def zn(a):
    a=np.array(a,float);m=np.nanmean(a);s=np.nanstd(a) or 1;return (a-m)/s
rb=[];seen=set()
for d in win:
    if d in ar and d[:6] not in seen: seen.add(d[:6]);rb.append(d)
# 리밸런스일별: raw fwd top / orth fwd top
raw_set={};orth_set={}
for d in rb:
    i=tdi[d];d1=tdays[min(i+250,len(tdays)-1)];rows=[]
    for x in ar[d]:
        t=x['ticker']
        if t not in pcol or not(parr[i,pcol[t]]>0): continue
        e0=ttm(t,d);e1=ttm(t,d1)
        if not(e0 and e0>0 and e1 is not None): continue
        rows.append((t,e1/e0-1,x.get('value_s')or 0,x.get('quality_s')or 0,x.get('growth_s')or 0,x.get('mom_12m_s')or x.get('momentum_s')or 0))
    if len(rows)<20: raw_set[d]=[];orth_set[d]=[];continue
    df=pd.DataFrame(rows,columns=['t','fwd','V','Q','G','M'])
    fz=zn(df['fwd'])
    X=np.column_stack([np.ones(len(df)),zn(df['V']),zn(df['Q']),zn(df['G']),zn(df['M'])])
    beta,_,_,_=np.linalg.lstsq(X,fz,rcond=None); resid=fz-X@beta
    df['rawz']=fz;df['orth']=resid
    raw_set[d]=df.sort_values('rawz',ascending=False).head(15)['t'].tolist()
    orth_set[d]=df.sort_values('orth',ascending=False).head(15)['t'].tolist()
def sleeve_rets(picks):
    held=[];out=[];prev=None
    for d in win:
        r=0.0
        if held and prev:
            rs=[parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1 for t in held if parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0]
            r=float(np.mean(rs)) if rs else 0.0
        out.append(r)
        if not reg.get(d,True): held=[]
        elif d in picks: held=picks[d]
        prev=d
    return pd.Series(out,index=win)
# production
G3=('rev_z','oca_z','gp_growth_z',0.4,0.4,0.2);regp=reg_s(dts)
t=TurboSimulator({d:ar[d] for d in dts},dts,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True
for d in dts:
    tkn=t._preextracted[d][0];fd={x['ticker']:x for x in ar[d]}
    t._overlay_pre[d]=np.array([0.2*(fd[tk].get('overheat_pen')or 0)+0.05*(fd[tk].get('mom_10_z')or 0)+0.06*(fd[tk].get('vol_low_z')or 0)-0.3*(fd[tk].get('recent_ca')or 0) for tk in tkn])
t._cached_key=None;t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:]);flat=list(t._cached_flat)
rp=_run_regime_inner(flat,flat,0,6,3,3,6,3,regp,dts,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(dts),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
prod=pd.Series(rp['_daily_rets'],index=dts)
raw=sleeve_rets(raw_set);orth=sleeve_rets(orth_set)
def met(a):
    a=np.array(a);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    sh=a.mean()/(a.std() or 1)*np.sqrt(252);dn=a[a<0];so=a.mean()/(dn.std() or 1)*np.sqrt(252)
    return cagr,mdd,(cagr/abs(mdd) if mdd<0 else 0),sh,so
idx=prod.index.intersection(raw.index)
pp,rr,oo=prod[idx],raw[idx],orth[idx]
print(f"  {'전략(state유니버스)':20s}{'CAGR':>7s}{'MDD':>8s}{'Calmar':>7s}{'Sharpe':>7s}{'상관(vs prod)':>13s}")
for nm,x in [('production',pp),('raw 선행성장',rr),('직교화 선행성장',oo)]:
    c,m,cal,sh,so=met(x);cor=x.corr(pp) if nm!='production' else 0
    print(f"  {nm:20s}{c:>6.0f}%{m:>7.1f}%{cal:>7.2f}{sh:>7.2f}{cor:>+12.3f}")
print("\n[블렌드: production + 직교화sleeve]")
for w in [0,0.1,0.2,0.3,0.5]:
    c,m,cal,sh,so=met((1-w)*pp+w*oo); print(f"  +{int(w*100):>2}% 직교sl: Calmar {cal:.2f} Sharpe {sh:.2f} MDD {m:.1f}%")
