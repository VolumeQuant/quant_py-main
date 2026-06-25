# -*- coding: utf-8 -*-
"""확인(confirm) 정의 비교 — CW=3 고정, '확인'을 어떻게 정의할지만 바꿔 백테스트.
A) cross-sectional 상위N  B) 절대컷 X  C) 연속가중(비율비례). look-ahead 상한, 매일갱신, 풀지표."""
import sys, io, os, glob, json, pickle
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(prices.columns)};parr=prices.values
tdays=[d.strftime('%Y%m%d') for d in prices.index];tdi={d:i for i,d in enumerate(tdays)}
tdn=np.array([np.datetime64(pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])) for d in tdays])
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
ttm_series={}
for t,dd in cache.items():
    s=dd.get('ni') or dd.get('ni2')
    if s is None: continue
    qd=np.asarray(s[0]);qv=np.asarray(s[1],float);o=np.argsort(qd);qd=qd[o];qv=qv[o]
    c4=np.array([qv[max(0,k-3):k+1].sum() if k>=3 else np.nan for k in range(len(qv))])
    idx=np.searchsorted(qd,tdn,side='right')-1
    ser=np.where(idx>=3,c4[np.clip(idx,0,len(c4)-1)],np.nan);ttm_series[t]=ser
tks=[t for t in ttm_series if t in pcol]
SER=np.vstack([ttm_series[t] for t in tks]);PX=np.vstack([parr[:,pcol[t]] for t in tks])
ti={t:j for j,t in enumerate(tks)}
# 일별: 각 종목 grow(=TTM(d+250)/TTM(d)) + topN set
growmap={};topset={}
for d in dts:
    i=tdi[d];d1=min(i+250,len(tdays)-1)
    e0=SER[:,i];e1=SER[:,d1];px=PX[:,i];ok=(e0>0)&np.isfinite(e1)&(px>0)
    g=np.where(ok,e1/e0,np.nan)
    growmap[d]={tks[j]:g[j] for j in range(len(tks)) if ok[j]}
    gg=np.where(ok,e1/e0-1,-np.inf);top=np.argsort(-gg)[:100];topset[d]=set(tks[j] for j in top if ok[j])
def metrics(daily):
    a=np.array(daily);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100
    n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100;cal=cagr/abs(mdd) if mdd<0 else 0
    return cal,cagr,mdd
def wfun_xsec(t,d,CW): return CW if t in topset[d] else 1.0
def wfun_abs(t,d,CW,X):
    g=growmap[d].get(t); return CW if (g is not None and np.isfinite(g) and g>=X) else 1.0
def wfun_cont(t,d,lo,hi):
    g=growmap[d].get(t); return float(np.clip(g,lo,hi)) if (g is not None and np.isfinite(g)) else 1.0
def sim(wfun):
    held=[];daily=[];prev=None;pw={}
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
            held=[x['ticker'] for x in sorted(ar[d],key=lambda z:z.get('rank',99))][:3]
            pw={t:wfun(t,d) for t in held}
        prev=d
    return metrics(daily)
CW=3.0
print(f"[확인 정의 비교 — CW={CW} 고정, look-ahead 상한, 매일갱신]\n")
print(f"  {'확인 정의':28s}{'Calmar':>8s}{'CAGR':>7s}{'MDD':>8s}")
rows=[('동일가중(baseline)', lambda t,d:1.0)]
rows.append((f'A) cross-sec 상위100 →×{CW:.0f}', lambda t,d:wfun_xsec(t,d,CW)))
for X in [1.0,1.1,1.2,1.3,1.5,2.0]:
    rows.append((f'B) 절대컷 {X:.1f}x →×{CW:.0f}', (lambda X: lambda t,d:wfun_abs(t,d,CW,X))(X)))
for lo,hi in [(0.5,3.0),(1.0,3.0),(0.5,5.0)]:
    rows.append((f'C) 연속 clip[{lo},{hi}]', (lambda lo,hi: lambda t,d:wfun_cont(t,d,lo,hi))(lo,hi)))
for nm,wf in rows:
    cal,cagr,mdd=sim(wf);print(f"  {nm:28s}{cal:>8.2f}{cagr:>6.0f}%{mdd:>7.1f}%")
