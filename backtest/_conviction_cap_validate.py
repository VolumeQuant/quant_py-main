# -*- coding: utf-8 -*-
"""cap3 vs cap5 재검증 — cap 그리드 × 기간(WF) × LOWO. cap3가 robust하게 우월한가."""
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
gw={};fp={}
for d in dts:
    i=tdi[d];d1=tdays[min(i+250,len(tdays)-1)]
    for t in [x['ticker'] for x in sorted(ar[d],key=lambda z:z.get('rank',99))[:3]]:
        p0=parr[i,pcol[t]] if t in pcol else None;e0=ttm(t,d);e1=ttm(t,d1)
        if p0 and p0>0 and e0 and e0>0 and e1 and e1>0 and t in sh and sh[t]>0:
            gw[(d,t)]=e1/e0;fp[(d,t)]=(p0*sh[t])/(e1*1e8)
def cal_only(daily):
    a=np.array(daily);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100
    n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100;return (cagr/abs(mdd) if mdd<0 else 0),mdd
def wf(d,t,CAP,K=2.0,GATE=20.0):
    g=gw.get((d,t));f=fp.get((d,t))
    if g is None or f is None or f>=GATE: return 1.0
    return min(1.0+K*max(g-1.0,0.0),CAP)
def sim(CAP,lo=None,hi=None,excl=None):
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
            held=[x['ticker'] for x in sorted(ar[d],key=lambda z:z.get('rank',99))[:3] if x['ticker']!=excl]
            pw={t:wf(d,t,CAP) for t in held}
        prev=d
    return cal_only(daily)
segs=[('전체',None,None),('19-21',dts[0],'20211231'),('22-23약세','20220101','20231231'),('24-26','20240101',dts[-1])]
print("[cap 재검증 — 그리드 × 기간(WF)]  Calmar (MDD)\n")
print(f"  {'cap':5s}"+"".join(f"{nm:>12s}" for nm,_,_ in segs))
for cap in [2,3,4,5,6]:
    row=f"  {cap:<5}"
    for _,lo,hi in segs:
        c,m=sim(cap,lo,hi);row+=f"  {c:5.2f}({m:4.0f})"
    print(row)
print(f"\n[LOWO — 핵심 수혜종목 제외 시 cap3 vs cap5]  Calmar")
print(f"  {'제외':14s}{'cap3':>8s}{'cap5':>8s}{'우위':>7s}")
for nm,ex in [('전체(없음)',None),('-SK하이닉스','000660'),('-제룡전기','033100'),('-한미반도체','042700'),('-브이엠','089970'),('-이오테크닉스','039030')]:
    c3=sim(3,excl=ex)[0];c5=sim(5,excl=ex)[0]
    print(f"  {nm:14s}{c3:>8.2f}{c5:>8.2f}{('cap3' if c3>=c5 else 'cap5'):>7s}")
