# -*- coding: utf-8 -*-
"""확인신호 월간갱신 vs 매일갱신 — 차이 있나. 기대성장(TTM실적)은 분기마다 변해서 매일해도 비슷할 것."""
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
# TTM 시계열을 거래일 그리드에 미리 계산 (벡터화)
ttm_series={}
for t,dd in cache.items():
    s=dd.get('ni') or dd.get('ni2')
    if s is None: continue
    qd=np.asarray(s[0]);qv=np.asarray(s[1],float)
    order=np.argsort(qd);qd=qd[order];qv=qv[order]
    c4=np.array([qv[max(0,k-3):k+1].sum() if k>=3 else np.nan for k in range(len(qv))])
    idx=np.searchsorted(qd,tdn,side='right')-1
    ser=np.where(idx>=0,c4[np.clip(idx,0,len(c4)-1)],np.nan)
    ser=np.where(idx<3,np.nan,ser)
    ttm_series[t]=ser
def confirm_set(i):
    d1=min(i+250,len(tdays)-1);fg=[]
    for t,ser in ttm_series.items():
        if t not in pcol or not(parr[i,pcol[t]]>0): continue
        e0=ser[i];e1=ser[d1]
        if e0>0 and np.isfinite(e1): fg.append((t,e1/e0-1))
    fg.sort(key=lambda z:-z[1]);return set(t for t,_ in fg[:100])
# 월간 캐시 vs 매일
conf_m={};cur=set();curm=None
conf_d={}
for d in dts:
    i=tdi[d]
    if d[:6]!=curm: curm=d[:6];cur=confirm_set(i)
    conf_m[d]=cur
    conf_d[d]=confirm_set(i)
diff=np.mean([len(conf_m[d]^conf_d[d])/200 for d in dts])
print(f"월간셋 vs 매일셋 평균 차집합비율 {diff*100:.1f}% (작을수록 동일)\n")
def sim(CW,conf):
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
            cf=conf.get(d,set());pw={t:(CW if t in cf else 1.0) for t in held}
        prev=d
    a=np.array(daily);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100
    n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100;return (cagr/abs(mdd) if mdd<0 else 0),cagr,mdd
print(f"  {'CW':5s}{'월간갱신Cal':>11s}{'매일갱신Cal':>11s}{'월CAGR':>8s}{'일CAGR':>8s}")
for cw in [1.0,2.0,3.0]:
    m=sim(cw,conf_m);dd=sim(cw,conf_d)
    print(f"  ×{cw:<4}{m[0]:>11.2f}{dd[0]:>11.2f}{m[1]:>7.0f}%{dd[1]:>7.0f}%")
