"""액티브 운용자 신규편입 신호 검증 + cross-ETF 합의 랭킹 (오프라인, 캐시 사용).

가설: 한국 액티브 ETF가 매일 홀딩스 공시 → 여러 운용자가 동시에 새로 담은 종목은 forward 초과수익?
데이터: _cache/holdings.parquet(스냅별 액티브 홀딩스) + 기존 주식 OHLCV(7년) 재사용.
검증: 신규편입 종목을 운용자 합의 수(N)별 코호트로 나눠 forward 20d 수익 vs KOSPI.

실행: python etf_research/consensus_backtest.py
"""
import sys
from pathlib import Path
import pandas as pd, numpy as np
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parent.parent
C = Path(__file__).parent / '_cache'
FWD = 20  # forward 거래일

h = pd.read_parquet(C/'holdings.parquet')
h['stock'] = h['stock'].astype(str).str.zfill(6)
snaps = sorted(h['snap'].unique())
print(f'스냅: {snaps}  | 액티브 ETF {h.etf.nunique()} | 행 {len(h)}', flush=True)

ohlcv = pd.read_parquet(ROOT/'data_cache'/'all_ohlcv_20170601_20260522.parquet').replace(0, np.nan)
kospi = pd.read_parquet(ROOT/'data_cache'/'kospi_yf.parquet').iloc[:,0].sort_index()
odates = ohlcv.index
lastd = odates[-1]

def fwd_ret(stock, snap, k=FWD):
    ts = pd.Timestamp(snap)
    if ts > lastd: return None
    pos = odates.searchsorted(ts)
    if pos >= len(odates) or pos+k >= len(odates): return None
    if stock not in ohlcv.columns: return None
    p0 = ohlcv.iloc[pos][stock]; p1 = ohlcv.iloc[pos+k][stock]
    if pd.isna(p0) or pd.isna(p1) or p0<=0: return None
    return p1/p0 - 1

def kospi_fwd(snap, k=FWD):
    ts = pd.Timestamp(snap); pos = kospi.index.searchsorted(ts)
    if pos+k >= len(kospi): return None
    return kospi.iloc[pos+k]/kospi.iloc[pos] - 1

# 신규편입 detect: 스냅 전이별 etf가 새로 담은 종목
records = []  # snap_cur, stock, n_managers(신규편입 운용자수)
for i in range(1, len(snaps)):
    sp, sc = snaps[i-1], snaps[i]
    hp = h[h.snap==sp]; hc = h[h.snap==sc]
    prev_sets = hp.groupby('etf')['stock'].apply(set).to_dict()
    new_by_stock = {}
    for etf, g in hc.groupby('etf'):
        prev = prev_sets.get(etf, set())
        if not prev: continue  # 이전 스냅 없는 etf는 신규편입 판정 불가
        for stk in set(g['stock']) - prev:
            new_by_stock[stk] = new_by_stock.get(stk, 0) + 1
    for stk, n in new_by_stock.items():
        records.append({'snap': sc, 'stock': stk, 'n_mgr': n})
rec = pd.DataFrame(records)
print(f'신규편입 이벤트 {len(rec)} (종목×스냅)', flush=True)

# === 백테스트: forward 수익 가능한 스냅만 (snap+FWD <= 0522) ===
bt = rec.copy()
bt['fwd'] = [fwd_ret(r.stock, r.snap) for r in bt.itertuples()]
bt['kospi'] = [kospi_fwd(r.snap) for r in bt.itertuples()]
bt = bt.dropna(subset=['fwd','kospi'])
bt['excess'] = bt['fwd'] - bt['kospi']
print(f'\n검증 가능 이벤트 {len(bt)} (forward {FWD}d, 주식데이터 ~20260522 내)', flush=True)

if len(bt):
    print(f"\n=== 운용자 합의 수(N)별 forward {FWD}d 수익 ===", flush=True)
    print(f"{'코호트':<16}{'건수':>6}{'평균수익':>9}{'중앙값':>8}{'평균초과(vsKOSPI)':>14}{'승률(초과>0)':>11}", flush=True)
    for lbl, cond in [('N=1 (단독)', bt.n_mgr==1), ('N=2', bt.n_mgr==2),
                      ('N>=3 (합의)', bt.n_mgr>=3), ('전체 신규편입', bt.n_mgr>=1)]:
        sub = bt[cond]
        if len(sub):
            print(f"{lbl:<16}{len(sub):>6}{sub.fwd.mean()*100:>+8.2f}%{sub.fwd.median()*100:>+7.2f}%{sub.excess.mean()*100:>+13.2f}%{(sub.excess>0).mean()*100:>10.0f}%", flush=True)
    print(f"\nKOSPI 평균 forward {FWD}d: {bt.kospi.mean()*100:+.2f}%", flush=True)
    # 스냅별
    print(f"\n=== 스냅별 (합의 N>=2) ===", flush=True)
    for sc in sorted(bt.snap.unique()):
        sub = bt[(bt.snap==sc)&(bt.n_mgr>=2)]
        if len(sub): print(f"  {sc}: {len(sub)}건 평균 {sub.fwd.mean()*100:+.2f}% 초과 {sub.excess.mean()*100:+.2f}%", flush=True)

# === 대칭 검증: 편출(removed) 종목 → forward 하락? ===
rem_records = []
for i in range(1, len(snaps)):
    sp, sc = snaps[i-1], snaps[i]
    cur_sets = h[h.snap==sc].groupby('etf')['stock'].apply(set).to_dict()
    for etf, g in h[h.snap==sp].groupby('etf'):
        cur = cur_sets.get(etf, None)
        if cur is None: continue
        for stk in set(g['stock']) - cur:
            rem_records.append({'snap': sc, 'stock': stk})
remdf = pd.DataFrame(rem_records).drop_duplicates(['snap','stock']) if rem_records else pd.DataFrame(columns=['snap','stock'])
if len(remdf):
    remdf['fwd'] = [fwd_ret(r.stock, r.snap) for r in remdf.itertuples()]
    remdf['kospi'] = [kospi_fwd(r.snap) for r in remdf.itertuples()]
    remdf = remdf.dropna(subset=['fwd','kospi']); remdf['excess'] = remdf['fwd']-remdf['kospi']
    if len(remdf):
        print(f"\n=== 대칭: 액티브 편출 종목 forward {FWD}d (검증 {len(remdf)}건) ===", flush=True)
        print(f"  편출 평균 {remdf.fwd.mean()*100:+.2f}% / 초과 {remdf.excess.mean()*100:+.2f}% / 승률 {(remdf.excess>0).mean()*100:.0f}%", flush=True)
        if len(bt):
            print(f"  → 신규편입(전체) 초과 {bt.excess.mean()*100:+.2f}% vs 편출 초과 {remdf.excess.mean()*100:+.2f}% (편입>편출이면 운용자 매매가 정보적)", flush=True)

# === 현재 합의 랭킹 (최신 스냅 신규편입, 운용자 多 순) ===
latest = snaps[-1]
cur = rec[rec.snap==latest].sort_values('n_mgr', ascending=False)
names = {}
import json
nf = C/'names.json'
sname_map = h.drop_duplicates('stock').set_index('stock')['sname'].to_dict()
print(f"\n=== 현재 합의 신규편입 랭킹 ({latest}, 운용자 수 순) ===", flush=True)
for r in cur.head(15).itertuples():
    print(f"  {sname_map.get(r.stock, r.stock)} ({r.stock}): {r.n_mgr}개 운용자 신규편입", flush=True)

bt.to_parquet(C/'signal_bt.parquet')
print('\n저장: _cache/signal_bt.parquet', flush=True)
