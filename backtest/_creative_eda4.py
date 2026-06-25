# -*- coding: utf-8 -*-
"""성장-주도 vs 모멘텀-주도 진입 — '성장없는 모멘텀'이 영구함정인가 (전 진입, 큰표본)."""
import sys, io, os, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
px=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(px.columns)};parr=px.values;pdi={d.strftime('%Y%m%d'):i for i,d in enumerate(px.index)}
df=pd.read_parquet(P+'/backtest/_creative_feats.parquet')
def fwd(tk,d,h):
    if tk not in pcol or d not in pdi: return None
    i=pdi[d];ci=pcol[tk]
    if i+h>=len(parr): return None
    p0,p1=parr[i,ci],parr[i+h,ci]
    return (p1/p0-1)*100 if(p0>0 and p1>0)else None
df['f120']=[fwd(tk,d,120) for tk,d in zip(df['tk'],df['d'])]
v=df.dropna(subset=['f60']).copy()
gm=v['growth'].median(); mm=v['mom'].median()
print(f"전체 {len(v)}건 기준선: fwd60 +9.6% 승률51% 큰손실20%  (growth중앙{gm:.2f} mom중앙{mm:.2f})\n")
print("=== 성장 × 모멘텀 2x2 ===")
def cell(name,mask):
    g=v[mask].dropna(subset=['f60'])
    g2=g.dropna(subset=['f120'])
    print(f"  {name:28s} n={len(g):>3} fwd60{g['f60'].mean():>+6.1f}% 승률{(g['f60']>0).mean()*100:>3.0f}% 큰손실{(g['f60']<-15).mean()*100:>3.0f}% fwd120{(g2['f120'].mean() if len(g2) else 0):>+6.1f}%")
cell('고성장+고모멘텀',(v['growth']>=gm)&(v['mom']>=mm))
cell('고성장+저모멘텀',(v['growth']>=gm)&(v['mom']<mm))
cell('저성장+고모멘텀 (모멘텀주도)',(v['growth']<gm)&(v['mom']>=mm))
cell('저성장+저모멘텀',(v['growth']<gm)&(v['mom']<mm))
print("\n=== '성장없는 모멘텀' 정련 (저성장 강도별) ===")
cell('growth<중앙 & mom>70%',(v['growth']<gm)&(v['mom']>v['mom'].quantile(0.7)))
cell('growth<30% & mom>중앙',(v['growth']<v['growth'].quantile(0.3))&(v['mom']>mm))
cell('growth<30% & mom>60% & pbr<중앙',(v['growth']<v['growth'].quantile(0.3))&(v['mom']>v['mom'].quantile(0.6))&(v['pbr']<v['pbr'].median()))
# 모멘텀-주도 + 끝물
cell('저성장 & 단기초과열(dpar20>60%)',(v['growth']<gm)&(v['dpar20']>v['dpar20'].quantile(0.6)))
print("\n=== 누가 걸리나: 저성장+고모멘텀 패자 ===")
mz=v[(v['growth']<gm)&(v['mom']>=mm)].dropna(subset=['f60']).sort_values('f60')
for _,x in mz.head(10).iterrows():
    print(f"    {x['d']} {x['nm'][:9]:9s} f60{x['f60']:>+5.0f}% growth{x['growth']:>4.1f} mom{x['mom']:>4.1f} pbr{x['pbr']}")
