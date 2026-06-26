# -*- coding: utf-8 -*-
"""US 핸드오프 — 모멘텀 3슬롯 + 가치(gap) sleeve 결합 시너지 (look-ahead 상한).
KR은 gap↔모멘텀 직교(+0.015)라 결합이 각각보다 나은가? = 진짜 검증."""
import sys, io, os, glob, json, pickle
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P='C:/dev'
px=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan);px=px.dropna(how='all')
pcol={c:i for i,c in enumerate(px.columns)};parr=px.values
tdays=[d.strftime('%Y%m%d') for d in px.index];tdi={d:i for i,d in enumerate(tdays)}
kc=pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:,0];ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
cache=pickle.load(open(P+'/backtest/_earn_cache.pkl','rb'))
vol=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_volume_*.parquet'))[-1])
vd=[d.strftime('%Y%m%d') for d in vol.index];vdi={d:i for i,d in enumerate(vd)};vval=vol.values;vcol={c:i for i,c in enumerate(vol.columns)}
def liq(t,d):
    if t not in vcol: return 0
    dd=d if d in vdi else max([x for x in vd if x<=d],default=None)
    if not dd: return 0
    i=vdi[dd];s=vval[max(0,i-19):i+1,vcol[t]];s=s[s>0];return np.nanmean(s)/1e8 if len(s)>=5 else 0
def ttm(t,d):
    dd=cache.get(t);s=dd.get('ni') if dd else None
    if s is None: return None
    v=s[1][s[0]<=np.datetime64(pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]))];return v[-4:].sum() if len(v)>=4 else None
ar={};dts=[]
for f in sorted(glob.glob(P+'/state/ranking_*.json')):
    d=os.path.basename(f)[8:16]
    if d.isdigit() and len(d)==8 and d>='20190102' and d in tdi:
        ar[d]=sorted(json.load(open(f,encoding='utf-8'))['rankings'],key=lambda z:z.get('rank',99));dts.append(d)
dts=sorted(dts)
reg={};md=True;stk=0;ss=None
for d in dts:
    ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
    if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md;continue
    s=bool(ma20[ts]>ma80[ts]);stk=stk+1 if s==ss else 1;ss=s
    if stk>=5 and md!=s: md=s
    reg[d]=md
def dret(t,d0,d1):
    if t not in pcol: return 0.0
    p0=parr[tdi[d0],pcol[t]];p1=parr[tdi[d1],pcol[t]]
    return (p1/p0-1) if p0>0 and p1>0 else 0.0
# 모멘텀 3슬롯 일별수익
def mom_daily():
    held=[];out={};prev=None
    for d in dts:
        if held and prev: out[d]=np.mean([dret(t,prev,d) for t in held]) if held else 0.0
        else: out[d]=0.0
        if not reg.get(d,True): held=[]
        else:
            rk=[x['ticker'] for x in ar[d]];held=[t for t in held if t in rk[:6]]
            for t in rk[:3]:
                if len(held)>=3: break
                if t not in held: held.append(t)
        prev=d
    return out
# 가치 sleeve: 월1회 gap 상위K 동일가중, 약세장 현금
def val_daily(K):
    held=[];out={};prev=None;curm=None
    for d in dts:
        if held and prev: out[d]=np.mean([dret(t,prev,d) for t in held]) if held else 0.0
        else: out[d]=0.0
        if not reg.get(d,True): held=[];prev=d;continue
        if d[:6]!=curm:  # 월 리밸
            curm=d[:6];i=tdi[d];d1=tdays[min(i+250,len(tdays)-1)];cand=[]
            for t in cache:
                if t not in pcol or not(parr[i,pcol[t]]>0) or liq(t,d)<50: continue
                e0=ttm(t,d);e1=ttm(t,d1)
                if e0 and e0>0 and e1 and e1>0:
                    g=e1/e0
                    if 1.0<g<10: cand.append((t,g))
            cand.sort(key=lambda z:-z[1]);held=[t for t,_ in cand[:K]]
        prev=d
    return out
def met(series):
    a=np.array([series[d] for d in dts])
    eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100
    n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100;return (cagr/abs(mdd) if mdd<0 else 0),cagr,mdd
mom=mom_daily()
print("[모멘텀 3슬롯 + 가치 sleeve 결합 — look-ahead 상한]\n")
cm,cgm,mm=met(mom);print(f"  모멘텀 단독        Calmar {cm:.2f}  CAGR {cgm:.0f}%  MDD {mm:.1f}%")
for K in [7,10,15]:
    val=val_daily(K)
    cv,cgv,mv=met(val)
    print(f"\n  가치sleeve K={K} 단독  Calmar {cv:.2f}  CAGR {cgv:.0f}%  MDD {mv:.1f}%")
    for w in [0.7,0.5,0.3]:
        comb={d:w*mom[d]+(1-w)*val[d] for d in dts}
        cc,cgc,mc=met(comb)
        flag=' ★시너지' if (cc>cm and mc>mm) else (' MDD개선' if mc>mm else '')
        print(f"    결합 {int(w*100)}모멘텀/{int((1-w)*100)}가치  Calmar {cc:.2f}  CAGR {cgc:.0f}%  MDD {mc:.1f}%{flag}")
