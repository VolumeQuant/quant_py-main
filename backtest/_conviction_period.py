# -*- coding: utf-8 -*-
"""확신가중 스위트스팟 기간별 — 최적 비중이 19-21/22-23약세/24-26에서 일관적인가(robust) vs 한 기간 artifact."""
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
dts=sorted(dts)
reg={};md=True;stk=0;ss=None
for d in dts:
    ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
    if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md;continue
    s=bool(ma20[ts]>ma80[ts]);stk=stk+1 if s==ss else 1;ss=s
    if stk>=5 and md!=s: md=s
    reg[d]=md
def ttm(t,d):
    dd=cache.get(t);s=(dd.get('ni') or dd.get('ni2')) if dd else None
    if s is None: return None
    v=s[1][s[0]<=np.datetime64(pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]))];return v[-4:].sum() if len(v)>=4 else None
confirm={};cur=set();curm=None
for d in dts:
    if d[:6]!=curm:
        curm=d[:6];i=tdi[d];d1=tdays[min(i+250,len(tdays)-1)];fg=[]
        for t in cache:
            if t not in pcol or not(parr[i,pcol[t]]>0): continue
            e0=ttm(t,d);e1=ttm(t,d1)
            if e0 and e0>0 and e1 is not None: fg.append((t,e1/e0-1))
        fg.sort(key=lambda z:-z[1]);cur=set(t for t,_ in fg[:100])
    confirm[d]=cur
def sim(CW, lo, hi):
    held=[];daily=[];prev=None;pw={}
    for d in dts:
        if not(lo<=d<=hi):
            # 경계 밖이어도 포지션 carry 위해 상태만 갱신, 수익은 미집계
            if not reg.get(d,True): held=[];pw={}
            else:
                cand=[x['ticker'] for x in sorted(ar[d],key=lambda z:z.get('rank',99))][:3]
                held=cand;cf=confirm.get(d,set());pw={t:(CW if t in cf else 1.0) for t in held}
            prev=d;continue
        ret=0.0
        if held and prev:
            num=0;den=0
            for t in held:
                if t in pcol and parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0:
                    w=pw.get(t,1.0);num+=w*(parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1);den+=w
            ret=num/den if den>0 else 0.0
        daily.append(ret)
        if not reg.get(d,True): held=[];pw={}
        else:
            cand=[x['ticker'] for x in sorted(ar[d],key=lambda z:z.get('rank',99))][:3]
            held=cand;cf=confirm.get(d,set());pw={t:(CW if t in cf else 1.0) for t in held}
        prev=d
    a=np.array(daily);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100
    n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return cagr/abs(mdd) if mdd<0 else 0
segs=[('전체',dts[0],dts[-1]),('19-21',dts[0],'20211231'),('22-23약세','20220101','20231231'),('24-26',('20240101'),dts[-1])]
print("[확신가중 스위트스팟 — 기간별 Calmar]\n")
print(f"  {'비중':6s}"+"".join(f"{nm:>10s}" for nm,_,_ in segs))
for cw in [1.0,1.5,2.0,2.5,3.0,5.0,10.0]:
    print(f"  {('×'+str(cw)):6s}"+"".join(f"{sim(cw,lo,hi):>10.2f}" for _,lo,hi in segs))
print("\n각 기간 최적비중:")
for nm,lo,hi in segs:
    best=max([1.0,1.5,2.0,2.5,3.0,5.0,10.0],key=lambda c:sim(c,lo,hi))
    print(f"  {nm:10s} → ×{best}")
