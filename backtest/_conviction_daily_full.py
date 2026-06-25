# -*- coding: utf-8 -*-
"""★매일 갱신 융합 풀백테스트 (look-ahead 상한). 확신신호=매일 재계산. 전체지표+기간별+LOWO."""
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
# TTM 시계열 거래일 그리드 (벡터화)
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
def confirm_daily(d):
    i=tdi[d];d1=min(i+250,len(tdays)-1)
    e0=SER[:,i];e1=SER[:,d1];px=PX[:,i]
    ok=(e0>0)&np.isfinite(e1)&(px>0)
    g=np.where(ok,e1/e0-1,-np.inf)
    top=np.argsort(-g)[:100]
    return set(tks[j] for j in top if ok[j])
conf={d:confirm_daily(d) for d in dts}
def metrics(daily):
    a=np.array(daily);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100
    n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100;cal=cagr/abs(mdd) if mdd<0 else 0
    sh=a.mean()/(a.std() or 1)*np.sqrt(252);dn=a[a<0].std() or 1;so=a.mean()/dn*np.sqrt(252)
    return cal,cagr,mdd,sh,so,eq[-1]
def sim(CW,lo=None,hi=None,excl=None):
    held=[];daily=[];prev=None;pw={}
    for d in dts:
        inseg = (lo is None) or (lo<=d<=hi)
        ret=0.0
        if held and prev and inseg:
            num=0;den=0
            for t in held:
                if t in pcol and parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0:
                    w=pw.get(t,1.0);num+=w*(parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1);den+=w
            ret=num/den if den>0 else 0.0
        if inseg: daily.append(ret)
        if not reg.get(d,True): held=[];pw={}
        else:
            held=[x['ticker'] for x in sorted(ar[d],key=lambda z:z.get('rank',99)) if x['ticker']!=excl][:3]
            cf=conf.get(d,set());pw={t:(CW if t in cf else 1.0) for t in held}
        prev=d
    return metrics(daily)
print("="*64)
print("[① 매일 갱신 융합 풀백테스트 — look-ahead 상한]")
print("="*64)
print(f"\n  {'비중':6s}{'Calmar':>8s}{'CAGR':>7s}{'MDD':>8s}{'Sharpe':>8s}{'Sortino':>8s}{'누적배수':>9s}")
for cw in [1.0,1.5,2.0,2.5,3.0,5.0,10.0]:
    m=sim(cw);print(f"  ×{cw:<5}{m[0]:>8.2f}{m[1]:>6.0f}%{m[2]:>7.1f}%{m[3]:>8.2f}{m[4]:>8.2f}{m[5]:>8.0f}x")
print(f"\n  [기간별 Calmar]  {'비중':6s}{'전체':>8s}{'19-21':>8s}{'약세':>8s}{'24-26':>8s}")
segs=[(dts[0],dts[-1]),(dts[0],'20211231'),('20220101','20231231'),('20240101',dts[-1])]
for cw in [1.0,2.0,2.5,3.0]:
    vals=[sim(cw,lo,hi)[0] for lo,hi in segs];print(f"  {'':6s}×{cw:<5}{vals[0]:>7.2f}{vals[1]:>8.2f}{vals[2]:>8.2f}{vals[3]:>8.2f}")
print(f"\n  [LOWO Calmar — 핵심종목 제외]  {'비중':6s}{'×2':>7s}{'×3':>7s}")
for nm,ex in [('-SK하이닉스','000660'),('-한미반도체','042700'),('-브이엠','089970')]:
    print(f"  {nm:14s}{'':6s}{sim(2.0,excl=ex)[0]:>7.2f}{sim(3.0,excl=ex)[0]:>7.2f}")
