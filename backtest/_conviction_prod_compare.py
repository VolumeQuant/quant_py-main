# -*- coding: utf-8 -*-
"""★production 확신가중(선행PER<20 자격 + 기대성장비례 k2cap5) vs 동일가중 정면비교.
look-ahead 상한(미래실적 proxy), 매일갱신, 전지표+기간별. 사용자 '얼마나 좋아?' 답."""
import sys, io, os, glob, json, pickle
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(prices.columns)};parr=prices.values
tdays=[d.strftime('%Y%m%d') for d in prices.index];tdi={d:i for i,d in enumerate(tdays)}
kc=pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:,0];ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
cache=pickle.load(open(P+'/backtest/_earn_cache.pkl','rb'))
mc=pd.read_parquet(sorted(glob.glob(P+'/data_cache/market_cap_ALL_*.parquet'))[-1])
sh={t:mc.loc[t,'상장주식수'] for t in mc.index}
ar={};dts=[]
for f in sorted(glob.glob(P+'/state/ranking_*.json')):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102' and dt in tdi:
        ar[dt]=json.load(open(f,encoding='utf-8'))['rankings'];dts.append(dt)
dts=sorted(dts)
reg={};md=True;stk=0;ss=None
for d in dts:
    ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
    if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md;continue
    s=bool(ma20[ts]>ma80[ts]);stk=stk+1 if s==ss else 1;ss=s
    if stk>=5 and md!=s: md=s
    reg[d]=md
def ttm(t,d):
    dd=cache.get(t);s=dd.get('ni') if dd else None
    if s is None: return None
    v=s[1][s[0]<=np.datetime64(pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]))];return v[-4:].sum() if len(v)>=4 else None
# 일별 held top3의 grow·fwd_per 미리계산 (look-ahead)
gw={};fp={}
for d in dts:
    i=tdi[d];d1=tdays[min(i+250,len(tdays)-1)]
    held=[x['ticker'] for x in sorted(ar[d],key=lambda z:z.get('rank',99))[:3]]
    for t in held:
        p0=parr[i,pcol[t]] if t in pcol else None
        e0=ttm(t,d);e1=ttm(t,d1)
        if p0 and p0>0 and e0 and e0>0 and e1 and e1>0 and t in sh and sh[t]>0:
            gw[(d,t)]=e1/e0; fp[(d,t)]=(p0*sh[t])/(e1*1e8)
def metrics(daily):
    a=np.array(daily);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100
    n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100;cal=cagr/abs(mdd) if mdd<0 else 0
    sh_=a.mean()/(a.std() or 1)*np.sqrt(252);dn=a[a<0].std() or 1;so=a.mean()/dn*np.sqrt(252)
    return cal,cagr,mdd,sh_,so
def wfun_prod(d,t,K,CAP,GATE):
    g=gw.get((d,t));f=fp.get((d,t))
    if g is None or f is None or f>=GATE: return 1.0
    return min(1.0+K*max(g-1.0,0.0),CAP)
def sim(wf,lo=None,hi=None):
    held=[];daily=[];prev=None;pw={}
    for d in dts:
        inseg=(lo is None) or (lo<=d<=hi);ret=0.0
        if held and prev and inseg:
            num=0;den=0
            for t in held:
                if t in pcol and parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0:
                    w=pw.get(t,1.0);num+=w*(parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1);den+=w
            ret=num/den if den>0 else 0.0
        if inseg: daily.append(ret)
        if not reg.get(d,True): held=[];pw={}
        else:
            held=[x['ticker'] for x in sorted(ar[d],key=lambda z:z.get('rank',99))[:3]]
            pw={t:wf(d,t) for t in held}
        prev=d
    return metrics(daily)
segs=[('전체',None,None),('19-21',dts[0],'20211231'),('22-23약세','20220101','20231231'),('24-26','20240101',dts[-1])]
eq=lambda d,t:1.0
prod=lambda d,t:wfun_prod(d,t,2.0,5.0,20.0)
print("[동일가중 vs production 확신가중(선행PER<20 + 기대성장비례 k2cap5) — look-ahead 상한]\n")
print(f"  {'전략':24s}{'Calmar':>8s}{'CAGR':>7s}{'MDD':>8s}{'Sharpe':>8s}{'Sortino':>8s}")
for nm,wf in [('동일가중(기존)',eq),('production 확신가중',prod)]:
    m=sim(wf);print(f"  {nm:24s}{m[0]:>8.2f}{m[1]:>6.0f}%{m[2]:>7.1f}%{m[3]:>8.2f}{m[4]:>8.2f}")
print(f"\n  [기간별 Calmar]      {'전체':>8s}{'19-21':>8s}{'약세':>8s}{'24-26':>8s}")
for nm,wf in [('동일가중',eq),('production',prod)]:
    vals=[sim(wf,lo,hi)[0] for _,lo,hi in segs];print(f"  {nm:18s}"+"".join(f"{v:>8.2f}" for v in vals))
print(f"\n  [참고 — cap 민감도]  {'Calmar':>8s}{'CAGR':>7s}{'MDD':>8s}")
for cap in [2,3,5,8]:
    m=sim(lambda d,t,c=cap:wfun_prod(d,t,2.0,c,20.0));print(f"  cap{cap} (k2,gate20)     {m[0]:>8.2f}{m[1]:>6.0f}%{m[2]:>7.1f}%")
