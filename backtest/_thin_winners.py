import sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
px=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(px.columns)};parr=px.values
tdays=[d.strftime('%Y%m%d') for d in px.index];tdi={d:i for i,d in enumerate(tdays)}
vol=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_volume_*.parquet'))[-1])
vd=[d.strftime('%Y%m%d') for d in vol.index];vdi={d:i for i,d in enumerate(vd)};vval=vol.values;vcol={c:i for i,c in enumerate(vol.columns)}
nm=json.load(open(P+'/kr_eps_momentum/ticker_info_cache.json',encoding='utf-8'))
def nameof(t):
    for k in (t,t+'.KS',t+'.KQ'):
        if k in nm: return nm[k].get('shortName',t)
    return t
def liq20(t,d):
    if t not in vcol: return None
    if d not in vdi: d=max([x for x in vd if x<=d],default=None)
    if d is None: return None
    i=vdi[d];s=vval[max(0,i-19):i+1,vcol[t]];s=s[s>0]
    return np.nanmean(s)/1e8 if len(s)>=5 else None
def fwd(t,d,h):
    if t not in pcol or d not in tdi: return None
    i=tdi[d];d2=tdays[min(i+h,len(tdays)-1)];p0=parr[i,pcol[t]];p1=parr[tdi[d2],pcol[t]]
    return (p1/p0-1)*100 if p0>0 and p1>0 else None
print("[지목 종목 20일평균 거래대금]")
for t in ['037460','187870','088130','219130']:
    L=liq20(t,'20260622');print(f"  {nameof(t)[:8]:8s}: {L:.0f}억" if L else f"  {nameof(t)[:8]}: NA")
# 신규 top3 진입 전수
rows=[];prev=set()
for f in sorted(glob.glob(P+'/state/ranking_*.json')):
    d=os.path.basename(f)[8:16]
    if not(d.isdigit() and d>='20190102' and d in tdi): continue
    held=[x['ticker'] for x in sorted(json.load(open(f,encoding='utf-8'))['rankings'],key=lambda z:z.get('rank',99))[:3]]
    for t in held:
        if t in prev: continue
        L=liq20(t,d);r60=fwd(t,d,60)
        if L is not None and r60 is not None: rows.append({'t':t,'nm':nameof(t),'d':d,'liq':L,'r60':r60})
    prev=set(held)
o=pd.DataFrame(rows)
thin=o[o['liq']<100]
print(f"\n[거래대금 <100억 신규진입 {len(thin)}건 — 이득/손실]")
print(f"  이득(r60>0): {(thin['r60']>0).sum()}건  평균 {thin[thin['r60']>0]['r60'].mean():+.0f}%")
print(f"  손실(r60<0): {(thin['r60']<0).sum()}건  평균 {thin[thin['r60']<0]['r60'].mean():+.0f}%")
print(f"\n  ★얇은데 이득 본 종목 top10 (진입일 거래대금):")
for _,r in thin.sort_values('r60',ascending=False).head(10).iterrows():
    print(f"    {r['nm'][:10]:10s} {r['d']} 거래대금 {r['liq']:.0f}억 → 60일 {r['r60']:+.0f}%")
print(f"\n  얇은데 손실 본 종목 top5:")
for _,r in thin.sort_values('r60').head(5).iterrows():
    print(f"    {r['nm'][:10]:10s} {r['d']} 거래대금 {r['liq']:.0f}억 → 60일 {r['r60']:+.0f}%")
