# -*- coding: utf-8 -*-
"""교집합 엄선 — production 엘리트(wr-rank<=Y) 중 선행성장 상위 K. 둘 다 높은 고확신 종목. ★fwd=look-ahead."""
import sys, io, os, glob, json, pickle
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
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
    dd=cache.get(t);s=dd.get('ni') or dd.get('ni2') if dd else None
    if s is None: return None
    v=s[1][s[0]<=np.datetime64(pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]))];return v[-4:].sum() if len(v)>=4 else None
rb=[];seen=set()
for d in win:
    if d in ar and d[:6] not in seen: seen.add(d[:6]);rb.append(d)
def metrics(a):
    a=np.array(a);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100
    n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100;sh=a.mean()/(a.std() or 1)*np.sqrt(252);dn=a[a<0];so=a.mean()/(dn.std() or 1)*np.sqrt(252)
    return cagr,mdd,(cagr/abs(mdd) if mdd<0 else 0),sh,so
def sim(Y,K):
    rbset={}
    for d in rb:
        i=tdi[d];d1=tdays[min(i+250,len(tdays)-1)]
        elig=[]
        for x in ar[d]:
            if x.get('rank',99)>Y: continue
            t=x['ticker']
            if t not in pcol or not(parr[i,pcol[t]]>0): continue
            e0=ttm(t,d);e1=ttm(t,d1)
            if e0 and e0>0 and e1 is not None: elig.append((t,e1/e0-1))
        elig.sort(key=lambda z:-z[1]); rbset[d]=[t for t,_ in elig[:K]]
    held=[];daily=[];prev=None
    for d in win:
        r=0.0
        if held and prev:
            rs=[parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1 for t in held if parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0]
            r=float(np.mean(rs)) if rs else 0.0
        daily.append(r)
        if not reg.get(d,True): held=[]
        elif d in rbset: held=rbset[d]
        prev=d
    return metrics(daily)
print("[교집합 엄선: production rank<=Y 중 선행성장 top K] production=CAGR110 MDD-26 Cal4.24 Sh2.06\n")
print(f"  {'config':16s}{'CAGR':>7s}{'MDD':>8s}{'Calmar':>7s}{'Sharpe':>7s}{'Sortino':>8s}")
for Y,K in [(6,3),(10,3),(10,5),(20,5),(20,3),(30,5),(30,10)]:
    c,m,cal,sh,so=sim(Y,K); print(f"  Y{Y} K{K} (월리밸)   {c:>6.0f}%{m:>7.1f}%{cal:>7.2f}{sh:>7.2f}{so:>8.2f}")
