# -*- coding: utf-8 -*-
"""확신 가중 — production 일별 3슬롯 유지, 보유 중 sleeve가 확인(선행성장 top M)한 종목 비중↑. vs 동일가중."""
import sys, io, os, glob, json, pickle
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(prices.columns)};parr=prices.values
tdays=[d.strftime('%Y%m%d') for d in prices.index];tdi={d:i for i,d in enumerate(tdays)}
kc=pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:,0];ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
cache=pickle.load(open(P+'/backtest/_earn_cache.pkl','rb'))
ar={};dts=[];rankmap={}
for f in sorted(glob.glob(P+'/state/ranking_*.json')):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102':
        rs=json.load(open(f,encoding='utf-8'))['rankings'];ar[dt]=rs;dts.append(dt);rankmap[dt]={x['ticker']:x.get('rank',99) for x in rs}
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
# 일별 선행성장 확인집합 (top M 광범위) — 매일 계산 비싸니 월별 캐시 후 일별 carry
confirm={}
cur=set();curm=None
for d in dts:
    if d[:6]!=curm:
        curm=d[:6];i=tdi[d];d1=tdays[min(i+250,len(tdays)-1)];fg=[]
        for t in cache:
            if t not in pcol or not(parr[i,pcol[t]]>0): continue
            e0=ttm(t,d);e1=ttm(t,d1)
            if e0 and e0>0 and e1 is not None: fg.append((t,e1/e0-1))
        fg.sort(key=lambda z:-z[1]); cur=set(t for t,_ in fg[:100])
    confirm[d]=cur
def sim(conf_w):
    # 매일 rank<=3 보유, 확인종목 가중 conf_w vs 미확인 1
    held=[];daily=[];prev=None;pw={}
    for d in dts:
        ret=0.0
        if held and prev:
            num=0;den=0
            for t in held:
                if t in pcol and parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0:
                    w=pw.get(t,1.0); num+=w*(parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1); den+=w
            ret=num/den if den>0 else 0.0
        daily.append(ret)
        if not reg.get(d,True): held=[];pw={}
        else:
            held=[x['ticker'] for x in sorted(ar[d],key=lambda z:z.get('rank',99))[:3]]
            cf=confirm.get(d,set()); pw={t:(conf_w if t in cf else 1.0) for t in held}
        prev=d
    a=np.array(daily);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    sh=a.mean()/(a.std() or 1)*np.sqrt(252);dn=a[a<0];so=a.mean()/(dn.std() or 1)*np.sqrt(252)
    return cagr,mdd,(cagr/abs(mdd) if mdd<0 else 0),sh,so
print("[확신가중: production 3슬롯, 확인종목 비중↑]\n")
print(f"  {'확인비중':12s}{'CAGR':>7s}{'MDD':>8s}{'Calmar':>7s}{'Sharpe':>7s}{'Sortino':>8s}")
for w in [1.0,1.5,2.0,2.5,3.0,5.0,10.0]:
    c,m,cal,sh,so=sim(w);tag='동일가중(baseline)' if w==1.0 else f'확인×{w}'
    print(f"  {tag:12s}{c:>6.0f}%{m:>7.1f}%{cal:>7.2f}{sh:>7.2f}{so:>8.2f}")
