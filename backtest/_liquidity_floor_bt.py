# -*- coding: utf-8 -*-
"""거래대금 예방 바닥선 BT — eligible=liq20>=floor, held=top3 eligible. floor 올리면 비용 얼마.
사용자: 작전 예방 위해 얇은거 미리 제외. 평균은 좋아도 미래 꼬리 막자는 리스크선택."""
import sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
px=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(px.columns)};parr=px.values
tdays=[d.strftime('%Y%m%d') for d in px.index];tdi={d:i for i,d in enumerate(tdays)}
kc=pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:,0];ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
vol=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_volume_*.parquet'))[-1])
vd=[d.strftime('%Y%m%d') for d in vol.index];vdi={d:i for i,d in enumerate(vd)};vval=vol.values;vcol={c:i for i,c in enumerate(vol.columns)}
def liq20(t,d):
    if t not in vcol or d not in vdi: return None
    i=vdi[d];s=vval[max(0,i-19):i+1,vcol[t]];s=s[s>0]
    return np.nanmean(s)/1e8 if len(s)>=10 else 0.0
nm=json.load(open(P+'/kr_eps_momentum/ticker_info_cache.json',encoding='utf-8'))
def nameof(t):
    for k in (t,t+'.KS',t+'.KQ'):
        if k in nm: return nm[k].get('shortName',t)
    return t
last=tdays[-1]
print("[지목 종목 20일평균 거래대금]")
for t in ['037460','187870','088130','219130','080220','089970','000660']:
    print(f"  {nameof(t)[:8]:8s}({t}): {liq20(t,last):.0f}억")
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
liqcache={}
def L(t,d):
    if (t,d) not in liqcache: liqcache[(t,d)]=liq20(t,d)
    return liqcache[(t,d)]
def sim(floor):
    held=[];daily=[];prev=None;removed=0;tot=0
    for d in dts:
        ret=0.0
        if held and prev:
            rr=[parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1 for t in held if t in pcol and parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0]
            ret=np.mean(rr) if rr else 0.0
        daily.append(ret)
        if not reg.get(d,True): held=[]
        else:
            elig=[x['ticker'] for x in ar[d] if floor<=0 or L(x['ticker'],d)>=floor]
            held=elig[:3]
            tot+=3;removed+=3-len(ar[d][:3]) if False else 0
        prev=d
    a=np.array(daily);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100
    n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100;return cagr/abs(mdd) if mdd<0 else 0,cagr,mdd
print(f"\n[거래대금 바닥선별 3슬롯 BT — 동일가중, 매일갱신]")
print(f"  {'floor':10s}{'Calmar':>8s}{'CAGR':>7s}{'MDD':>8s}")
for fl in [0,20,50,100,200,500]:
    c,cg,m=sim(fl);tag=f'{fl}억' if fl>0 else '없음(현행~20)'
    print(f"  >={tag:8s}{c:>8.2f}{cg:>6.0f}%{m:>7.1f}%")
