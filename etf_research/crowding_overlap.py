"""액티브 ETF crowding + overlap 분석 (오프라인, _cache 사용).
- crowding: 액티브 운용자들이 가장 많이/무겁게 보유한 종목 (합의 보유)
- overlap: 가장 비슷한 액티브 ETF 쌍 (중복 경고)
- 시장수급 결합: crowding 종목이 기존 KR 종목랭킹/주가모멘텀과 정합한지
실행: python etf_research/crowding_overlap.py
"""
import sys
from pathlib import Path
import pandas as pd, numpy as np
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parent.parent
C = Path(__file__).parent / '_cache'

h = pd.read_parquet(C/'holdings.parquet')
h['stock'] = h['stock'].astype(str).str.zfill(6)
latest = sorted(h['snap'].unique())[-1]
hl = h[h.snap==latest].copy()
sname = hl.drop_duplicates('stock').set_index('stock')['sname'].to_dict()
n_etf = hl.etf.nunique()
print(f'최신 스냅 {latest} | 액티브 ETF {n_etf} | 보유관계 {len(hl)}', flush=True)

# === Crowding: 몇 개 운용자가 보유 + 합산 비중 ===
crowd = hl.groupby('stock').agg(n_holders=('etf','nunique'), tot_w=('weight','sum'), avg_w=('weight','mean'))
crowd = crowd.sort_values(['n_holders','tot_w'], ascending=False)
print(f"\n=== 액티브 운용자 합의 보유 Top 20 (몇 명이 들고 있나) ===", flush=True)
print(f"{'종목':<16}{'보유운용자':>8}{'합산비중':>9}{'평균비중':>9}", flush=True)
for stk, r in crowd.head(20).iterrows():
    print(f"  {sname.get(stk,stk)[:14]:<16}{int(r.n_holders):>6}명{r.tot_w:>8.1f}%{r.avg_w:>8.2f}%", flush=True)

# === Overlap: ETF 쌍 유사도 (가중 코사인) ===
piv = hl.pivot_table(index='etf', columns='stock', values='weight', fill_value=0.0)
# 정규화 후 코사인
norm = piv.div(np.sqrt((piv**2).sum(axis=1)), axis=0).fillna(0)
sim = norm.values @ norm.values.T
etfs = piv.index.tolist()
names = __import__('json').loads((C/'names.json').read_text(encoding='utf-8')) if (C/'names.json').exists() else {}
pairs = []
for i in range(len(etfs)):
    for j in range(i+1, len(etfs)):
        pairs.append((etfs[i], etfs[j], sim[i,j]))
pairs.sort(key=lambda x: -x[2])
print(f"\n=== 가장 비슷한 액티브 ETF 쌍 Top 12 (중복 경고) ===", flush=True)
for a, b, sc in pairs[:12]:
    print(f"  {sc*100:5.1f}% ｜ {names.get(a,a)[:22]}  ↔  {names.get(b,b)[:22]}", flush=True)

# === crowding 종목의 주가 모멘텀 정합 (기존 OHLCV 재사용) ===
ohlcv = pd.read_parquet(ROOT/'data_cache'/'all_ohlcv_20170601_20260522.parquet').replace(0,np.nan)
def mom(stk, k=60):
    if stk not in ohlcv.columns: return None
    c = ohlcv[stk].dropna()
    if len(c) < k+1: return None
    return c.iloc[-1]/c.iloc[-1-k]-1
print(f"\n=== 합의보유 Top 10의 최근 60일 모멘텀 (운용자 쏠림 vs 주가) ===", flush=True)
for stk, r in crowd.head(10).iterrows():
    m = mom(stk)
    print(f"  {sname.get(stk,stk)[:14]:<16} {int(r.n_holders)}명 보유 | 60일 {m*100:+.1f}%" if m is not None else f"  {sname.get(stk,stk)[:14]:<16} {int(r.n_holders)}명 (주가데이터 없음)", flush=True)

crowd.to_parquet(C/'crowding.parquet')
print('\n저장: _cache/crowding.parquet', flush=True)
