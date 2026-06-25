# -*- coding: utf-8 -*-
"""약세장(22-23)에서 ×10이 왜 좋나 — 보유일수(소표본)·확인종목수·확인 vs 미확인 수익 격차."""
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
def diag(lo,hi,label):
    hold=0;cash=0;ncf=[];cf_ret=[];un_ret=[];prev=None;held=[]
    for d in dts:
        if held and prev and lo<=d<=hi:
            cf=confirm.get(prev,set())
            for t in held:
                if t in pcol and parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0:
                    r=parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1
                    (cf_ret if t in cf else un_ret).append(r)
        if lo<=d<=hi:
            if reg.get(d,True): hold+=1
            else: cash+=1
        if not reg.get(d,True): held=[]
        else:
            held=[x['ticker'] for x in sorted(ar[d],key=lambda z:z.get('rank',99))][:3]
            if lo<=d<=hi and held: ncf.append(sum(1 for t in held if t in confirm.get(d,set())))
        prev=d
    print(f"[{label}]  보유일 {hold} / 현금일 {cash} (현금비율 {cash/(hold+cash)*100:.0f}%)")
    print(f"   보유시 3슬롯 중 확인종목 평균 {np.mean(ncf):.2f}개" if ncf else "   -")
    cr=np.mean(cf_ret)*100 if cf_ret else 0;ur=np.mean(un_ret)*100 if un_ret else 0
    print(f"   ★확인종목 일평균 {cr:+.3f}% (n={len(cf_ret)}) vs 미확인 {ur:+.3f}% (n={len(un_ret)})  격차 {cr-ur:+.3f}%p")
diag('20220101','20231231','22-23 약세장')
diag('20240101',dts[-1],'24-26 강세장')
diag('20190102','20211231','19-21')
