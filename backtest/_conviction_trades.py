# -*- coding: utf-8 -*-
"""확신가중(×2) 실제 매매종목 + 누적수익 + 확인종목(비중↑) 기여."""
import sys, io, os, glob, json, pickle
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(prices.columns)};parr=prices.values
tdays=[d.strftime('%Y%m%d') for d in prices.index];tdi={d:i for i,d in enumerate(tdays)}
kc=pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:,0];ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
cache=pickle.load(open(P+'/backtest/_earn_cache.pkl','rb'))
NM=json.load(open(P+'/kr_eps_momentum/ticker_info_cache.json',encoding='utf-8'))
def nm(t):
    for k in (t,t+'.KS',t+'.KQ'):
        if k in NM: return NM[k].get('shortName',t)
    return t
ar={};dts=[]
for f in sorted(glob.glob(P+'/state/ranking_*.json')):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102': ar[dt]=json.load(open(f,encoding='utf-8'))['rankings'];dts.append(dt)
dts=sorted(dts)
def reg_s():
    reg={};md=True;stk=0;ss=None
    for d in dts:
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
CW=2.0; held=[];daily=[];prev=None;pw={};hold_days={};conf_days={}
for d in dts:
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
        held=[x['ticker'] for x in sorted(ar[d],key=lambda z:z.get('rank',99))[:3]]
        cf=confirm.get(d,set());pw={t:(CW if t in cf else 1.0) for t in held}
        for t in held:
            hold_days[t]=hold_days.get(t,0)+1
            if t in cf: conf_days[t]=conf_days.get(t,0)+1
    prev=d
a=np.array(daily);eq=np.cumprod(1+a)
print(f"=== 확신가중×2 누적성과 (2019-01~2026-06) ===")
print(f"  누적수익 {(eq[-1]-1)*100:,.0f}%  (원금 1 → {eq[-1]:,.0f}배)  CAGR {(eq[-1]**(252/len(a))-1)*100:.0f}%")
print(f"\n=== 가장 많이 보유한 종목 top12 (확인=비중2배 받은 날) ===")
top=sorted(hold_days,key=lambda t:-hold_days[t])[:12]
print(f"  {'종목':12s}{'보유일':>6s}{'확인일(비중2배)':>14s}")
for t in top:
    print(f"  {nm(t)[:12]:12s}{hold_days[t]:>6}{conf_days.get(t,0):>12}")
print(f"\n=== 최근 보유 (2026, 확인=★비중2배) ===")
for d in [dd for dd in dts if dd>='20260601'][::3]:
    h=[x['ticker'] for x in sorted(ar[d],key=lambda z:z.get('rank',99))[:3]] if reg.get(d) else []
    cf=confirm.get(d,set())
    s=' / '.join((('★' if t in cf else '')+nm(t)[:8]) for t in h) if h else '현금'
    print(f"  {d}: {s}")
