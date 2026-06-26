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
nm=json.load(open(P+'/kr_eps_momentum/ticker_info_cache.json',encoding='utf-8'))
def nameof(t):
    for k in (t,t+'.KS',t+'.KQ'):
        if k in nm: return nm[k].get('shortName',t)
    return t
lc={}
def liq20(t,d):
    if (t,d) in lc: return lc[(t,d)]
    r=None
    if t in vcol:
        dd=d if d in vdi else max([x for x in vd if x<=d],default=None)
        if dd:
            i=vdi[dd];s=vval[max(0,i-19):i+1,vcol[t]];s=s[s>0];r=np.nanmean(s)/1e8 if len(s)>=5 else None
    lc[(t,d)]=r;return r
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
def sim(floor,lo,hi):
    held=[];daily=[];prev=None
    for d in dts:
        ins=lo<=d<=hi;ret=0.0
        if held and prev and ins:
            rr=[parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1 for t in held if t in pcol and parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0]
            ret=np.mean(rr) if rr else 0.0
        if ins: daily.append(ret)
        if not reg.get(d,True): held=[]
        else:
            elig=[x['ticker'] for x in ar[d] if floor<=0 or (liq20(x['ticker'],d) or 0)>=floor]
            held=elig[:3]
        prev=d
    a=np.array(daily);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100
    n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100;tot=(eq[-1]-1)*100
    return (cagr/abs(mdd) if mdd<0 else 0),tot,mdd
print("[거래대금 바닥선별 — 2026년(1/1~) vs 전체]\n")
print(f"  {'floor':12s}{'2026 누적':>10s}{'2026 MDD':>10s}{'│ 전체Cal':>10s}{'전체MDD':>9s}")
y26=('20260101',dts[-1]);full=(dts[0],dts[-1])
for fl in [0,50,100,200]:
    c2,t2,m2=sim(fl,*y26);cf,tf,mf=sim(fl,*full)
    tag=f'>={fl}억' if fl>0 else '현행(~20억)'
    print(f"  {tag:12s}{t2:>9.0f}%{m2:>9.1f}%{cf:>10.2f}{mf:>8.1f}%")
# 2026 제거되는 종목
print("\n[2026 매수권(top3) 진입 중 거래대금<100억이라 막혔을 종목]")
seen=set()
for d in dts:
    if d<'20260101' or not reg.get(d,True): continue
    for x in ar[d][:3]:
        t=x['ticker'];L=liq20(t,d)
        if L is not None and L<100 and t not in seen:
            seen.add(t);print(f"  {nameof(t)[:10]:10s} {d} 거래대금 {L:.0f}억")
