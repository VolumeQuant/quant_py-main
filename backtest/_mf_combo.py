# -*- coding: utf-8 -*-
"""선행성장+모멘텀+저변동성 결합 멀티팩터 sleeve vs production. ★fwd=look-ahead 상한. 광범위 817 유니버스."""
import sys, io, os, glob, pickle
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(prices.columns)};parr=prices.values
tdays=[d.strftime('%Y%m%d') for d in prices.index];tdi={d:i for i,d in enumerate(tdays)}
kc=pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:,0];ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
cache=pickle.load(open(P+'/backtest/_earn_cache.pkl','rb')); tks=list(cache.keys())
win=[d for d in tdays if '20190102'<=d<='20260624']
def reg_s():
    reg={};md=True;stk=0;ss=None
    for d in win:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md;continue
        s=bool(ma20[ts]>ma80[ts]);stk=stk+1 if s==ss else 1;ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
reg=reg_s()
def ttm(t,d):
    dd=cache.get(t); s=dd.get('ni') or dd.get('ni2') if dd else None
    if s is None: return None
    v=s[1][s[0]<=np.datetime64(pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]))]
    return v[-4:].sum() if len(v)>=4 else None
def zn(a):
    a=np.array(a,float);m=np.nanmean(a);s=np.nanstd(a) or 1;return np.clip((a-m)/s,-3,3)
# 월 첫 거래일
rb=[];seen=set()
for d in win:
    if d[:6] not in seen: seen.add(d[:6]);rb.append(d)
# 리밸런스일별 팩터 사전계산
fac={}
for d in rb:
    i=tdi[d]; d1=tdays[min(i+250,len(tdays)-1)]
    cand=[]
    for t in tks:
        if t not in pcol: continue
        p0=parr[i,pcol[t]]; pm=parr[i-250,pcol[t]] if i>=250 else np.nan
        if not(p0>0) or not(pm>0): continue
        e0=ttm(t,d); e1=ttm(t,d1)
        if e0 is None or e0<=0 or e1 is None: continue
        col=parr[max(0,i-60):i,pcol[t]]; rr=np.diff(col)/col[:-1] if len(col)>5 else None
        vol=np.nanstd(rr) if rr is not None and len(rr)>3 else np.nan
        cand.append((t,e1/e0-1,p0/pm-1,vol))
    if len(cand)<30: fac[d]=None; continue
    arr=pd.DataFrame(cand,columns=['t','fwd','mom','vol'])
    arr['zf']=zn(arr['fwd']);arr['zm']=zn(arr['mom']);arr['zv']=zn(-arr['vol'].fillna(arr['vol'].median()))
    fac[d]=arr
def sim(wf,wm,wv,N=20):
    rbset={d:fac[d] for d in rb if fac[d] is not None}
    held=[];daily=[];prev=None
    for d in win:
        ret=0.0
        if held and prev:
            rs=[parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1 for t in held if parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0]
            ret=float(np.mean(rs)) if rs else 0.0
        daily.append(ret)
        if not reg.get(d,True): held=[]
        elif d in rbset:
            a=rbset[d].copy(); a['sc']=wf*a['zf']+wm*a['zm']+wv*a['zv']
            held=a.sort_values('sc',ascending=False).head(N)['t'].tolist()
        prev=d
    x=np.array(daily);eq=np.cumprod(1+x);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(x);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return (cagr/abs(mdd) if mdd<0 else 0),cagr,mdd
print("[결합 멀티팩터 sleeve] production=4.24 (CAGR~110 MDD-26)\n")
print(f"  {'fwd/mom/vol 가중':22s}{'Calmar':>8s}{'CAGR':>7s}{'MDD':>8s}")
for nm,(wf,wm,wv) in [('선행만 1/0/0',(1,0,0)),('선행+모멘 .6/.4/0',(.6,.4,0)),('선행+모멘 .5/.5/0',(.5,.5,0)),
                      ('선+모+저변동 .4/.3/.3',(.4,.3,.3)),('.5/.3/.2',(.5,.3,.2)),('.4/.4/.2',(.4,.4,.2)),('선행+저변동 .6/0/.4',(.6,0,.4))]:
    cal,cagr,mdd=sim(wf,wm,wv)
    print(f"  {nm:22s}{cal:>8.2f}{cagr:>6.0f}%{mdd:>7.1f}%")
