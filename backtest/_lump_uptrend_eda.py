# -*- coding: utf-8 -*-
"""lumpiness(<0.25) 종목 — 우상향 급성장 vs 출렁 forward 재검증 (전체 유니버스, 표본 확대).
면제 로직: 최근분기=최대 AND 기울기>0 = 우상향(구제) / 아니면 출렁(감점유지)."""
import sys, io, os, glob, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
px=pd.read_parquet(sorted(glob.glob('data_cache/all_ohlcv_adj_*.parquet'))[-1])
tdays=[d.strftime('%Y%m%d') for d in px.index]; tdi={d:i for i,d in enumerate(tdays)}
mc=pd.read_parquet(sorted(glob.glob('data_cache/market_cap_ALL_*.parquet'))[-1])
uni=[t for t in mc.index if isinstance(t,str) and len(t)==6 and t in px.columns and mc.loc[t,'시가총액']>=1e11]
print(f"유니버스(시총≥1000억, 가격있음): {len(uni)}종목")
def fwd(t,d,h):
    i=tdi[d]; p0=px[t].iloc[i]; p1=px[t].iloc[min(i+h,len(tdays)-1)]
    return (p1/p0-1)*100 if (p0>0 and p1>0) else None
# 월말 거래일
month_ends={}
for d in tdays:
    if d>='20190102': month_ends[d[:6]]=d
mdates=sorted(month_ends.values())
rows=[]
for ti,t in enumerate(uni):
    p=f'data_cache/fs_dart_{t}.parquet'
    if not os.path.exists(p): continue
    try:
        fs=pd.read_parquet(p); fs=fs[(fs['공시구분']=='q')&(fs['계정']=='매출액')].copy()
        fs['rcept_dt']=pd.to_datetime(fs['rcept_dt'],errors='coerce'); fs=fs[fs['rcept_dt'].notna()].sort_values('rcept_dt')
        if len(fs)<4: continue
        rd=fs['rcept_dt'].values; rv=fs['값'].astype(float).values
    except: continue
    for d in mdates:
        if d not in tdi: continue
        dd=np.datetime64(pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]))
        mask=rd<=dd; v=rv[mask]
        if len(v)<4: continue
        r4=v[-4:]
        if max(r4)<=0: continue
        mm=min(r4)/max(r4)
        if mm>=0.25: continue
        up=(r4[-1]==max(r4)) and (np.polyfit(range(4),r4,1)[0]>0)
        r60=fwd(t,d,60)
        if r60 is not None: rows.append({'up':up,'r60':r60})
    if ti%300==0: print(f"  {ti}/{len(uni)} 진행, 수집 {len(rows)}",flush=True)
df=pd.DataFrame(rows)
up=df[df['up']]; dn=df[~df['up']]
print(f"\n[lumpiness(<0.25) 전체유니버스 — 우상향 vs 출렁, n={len(df)}]")
print(f"  우상향 급성장(면제): fwd60 {up['r60'].mean():+.1f}% / 승률 {(up['r60']>0).mean()*100:.0f}% / n={len(up)}")
print(f"  출렁(감점유지)     : fwd60 {dn['r60'].mean():+.1f}% / 승률 {(dn['r60']>0).mean()*100:.0f}% / n={len(dn)}")
print(f"  Δ = {up['r60'].mean()-dn['r60'].mean():+.1f}%p")
print(f"\n→ 우상향 >> 출렁(+차이 크고 표본충분)이면 면제 로직 유효")
