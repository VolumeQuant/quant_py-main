# -*- coding: utf-8 -*-
"""끝물 cohort 영구 vs 일시 분해 — 가격끝물 × 재무약점 = 영구함정 시그니처 정련."""
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
# 끝물 cohort
ex=v[(v['upratio20']>0.6)&(v['dpar20']>v['dpar20'].median())].copy()
print(f"=== 상승끝물 cohort {len(ex)}건: 누가 걸리고 영구/일시 ===")
print(f"  cohort 전체 fwd60 {ex['f60'].mean():+.1f}% fwd120 {ex['f120'].mean():+.1f}%")
print("  개별(f60 나쁜순):")
for _,x in ex.sort_values('f60').head(14).iterrows():
    print(f"    {x['d']} {x['nm'][:9]:9s} f60{x['f60']:>+5.0f}% f120{(x['f120'] if pd.notna(x['f120']) else 0):>+5.0f}% growth{x['growth']:>4.1f} accrC{(x.get('accr_C') if 'accr_C' in x else float('nan'))} pbr{x['pbr']} asset_g{(x['asset_g'] if pd.notna(x['asset_g']) else 0):>+4.0f}")
# 영구(f120<0) vs 회복(f120>0) 재무 비교
exv=ex.dropna(subset=['f120'])
perm=exv[exv['f120']<0]; rec=exv[exv['f120']>=0]
print(f"\n  영구(f120<0) {len(perm)}건 vs 회복(f120>=0) {len(rec)}건 — 재무 차이:")
for c in ['growth','value','qual','mom','pbr','per','asset_g','leverage','gpmargin','rvol20','volsurge','max1d20']:
    if c in exv.columns:
        pm=perm[c].astype(float).mean(); rm=rec[c].astype(float).mean()
        print(f"    {c:10s} 영구 {pm:>+8.2f}  회복 {rm:>+8.2f}  차이 {pm-rm:>+8.2f}")
