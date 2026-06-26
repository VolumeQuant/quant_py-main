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
# 현행: 매일 top3 동일가중. 종목별 2026 기여 + 거래대금 라벨(진입 거래대금)
contrib={};entryliq={};held=[];prev=None
for d in dts:
    if '20260101'<=d and held and prev:
        for t in held:
            if t in pcol and parr[tdi[prev],pcol[t]]>0 and parr[tdi[d],pcol[t]]>0:
                r=(parr[tdi[d],pcol[t]]/parr[tdi[prev],pcol[t]]-1)/len(held)
                contrib[t]=contrib.get(t,0)+r
    if not reg.get(d,True): held=[]
    else:
        newh=[x['ticker'] for x in ar[d]][:3]
        for t in newh:
            if t not in entryliq: entryliq[t]=liq20(t,d)
        held=newh
    prev=d
print("[2026 보유종목별 시스템 기여 — 진입 거래대금 라벨, 동일가중 1/3]\n")
rows=sorted(contrib.items(),key=lambda z:-z[1])
print(f"  {'종목':12s}{'진입거래대금':>10s}{'2026기여':>10s}")
thin_sum=0;thick_sum=0
for t,c in rows:
    L=entryliq.get(t);lab=f'{L:.0f}억' if L else 'NA'
    flag=' ◄얇음' if (L and L<100) else ''
    if L and L<100: thin_sum+=c
    else: thick_sum+=c
    print(f"  {nameof(t)[:12]:12s}{lab:>10s}{c*100:>+9.1f}%{flag}")
print(f"\n  얇음(<100억) 합산 기여: {thin_sum*100:+.1f}%p")
print(f"  두꺼움(>=100억) 합산 기여: {thick_sum*100:+.1f}%p")
print(f"  → 얇은 종목 빼면 2026 수익에서 {thin_sum*100:+.1f}%p 만큼 사라짐")
