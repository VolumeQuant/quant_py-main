"""Phase 10 단순화 — boost V/G 그리드 (Q=0, M=30 고정), defense baseline.

cooldown_grid.py 패턴 활용 — TurboSim + _run_regime_inner 직접.
"""
import sys, os, json, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd, numpy as np
from pathlib import Path
from turbo_simulator import TurboSimulator, _calc_metrics, _run_regime_inner

PROJECT = Path(__file__).parent.parent
t0 = time.time()

print('=== Phase 10: boost V/G 그리드 (5.25년, 새 state) ===')
ohlcv_files = sorted((PROJECT/'data_cache').glob('all_ohlcv_*.parquet'))
ohlcv = pd.read_parquet(ohlcv_files[-1]).replace(0, np.nan)
kospi_df = pd.read_parquet(PROJECT/'data_cache'/'kospi_yf.parquet')
kospi = kospi_df.iloc[:,0].fillna(kospi_df['kospi']).dropna() if 'kospi' in kospi_df.columns else kospi_df.iloc[:,0].dropna()
ma170 = kospi.rolling(170).mean()

# state 로드
import glob as _glob
def _load(d):
    out = {}
    for fp in sorted((d).glob('ranking_*.json')):
        k = fp.stem.replace('ranking_', '')
        if len(k) != 8: continue
        with open(fp, encoding='utf-8') as f: out[k] = json.load(f)
    return out

boost_data = _load(PROJECT/'state')
defense_data = _load(PROJECT/'state'/'defense')
dates = sorted(set(boost_data) & set(defense_data))
dates = [d for d in dates if '20210104' <= d <= '20260330']
print(f'  거래일: {len(dates)} ({dates[0]} ~ {dates[-1]})')

# regime
def calc_regime(target_dates):
    reg = {}; md = False; stk = 0; ss = None
    for d in target_dates:
        ts = pd.Timestamp(d)
        kv = kospi.get(ts); mv = ma170.get(ts)
        if kv is None or pd.isna(mv): reg[d] = md; continue
        s = kv > mv
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= 8 and md != s: md = s
        reg[d] = md
    return reg

reg = calc_regime(dates)

# 그리드: V+G=70 (Q=0, M=30 고정) — 5조합
# V=5,G=65 / V=10,G=60 / V=15,G=55(baseline) / V=20,G=50 / V=25,G=45
grid_b = [(5,65), (10,60), (15,55), (20,50), (25,45)]

# defense baseline 고정 (V30 Q15 G15 M40)
boost_rk = {d: boost_data[d]['rankings'] for d in dates}
defense_rk = {d: defense_data[d]['rankings'] for d in dates}

# defense flat (baseline)
tsim_d = TurboSimulator(defense_rk, dates, ohlcv)
tsim_d._ensure_cache(0.30, 0.15, 0.15, 0.40, 0.7, 20, '6m-1m', 'rev_z', 'oca_z')
defense_flat = list(tsim_d._cached_flat)

# boost flat 빌드 + grid
tsim_b = TurboSimulator(boost_rk, dates, ohlcv)
results = []

for V, G in grid_b:
    tsim_b._ensure_cache(V/100, 0.0, G/100, 0.30, 0.6, 20, '12m', 'rev_z', 'oca_z')
    boost_flat = list(tsim_b._cached_flat)
    r = _run_regime_inner(
        defense_flat, boost_flat,
        3, 6, 5,  # defense entry/exit/slots
        3, 6, 3,  # offense entry/exit/slots
        reg, dates,
        tsim_b._price_arr, tsim_b._bench_arr, tsim_b._has_bench,
        tsim_b._date_row_indices, len(dates),
        -0.10, None, None, -0.15,
        breakout_hold=None, take_profit=None,
        stop_loss_o=-0.10, trailing_stop_o=-0.15,
        stop_loss_d=-0.10, trailing_stop_d=-0.15,
    )
    flag = ' (baseline)' if (V, G) == (15, 55) else ''
    print(f'  V{V:>2} G{G:>2}: Cal {r["calmar"]:.3f}  CAGR {r["cagr"]:.1f}%  MDD {r["mdd"]:.1f}%{flag}')
    results.append({'V': V, 'G': G, **r, 'is_baseline': (V, G) == (15, 55)})

# 정렬
results.sort(key=lambda x: -x['calmar'])
print('\n--- 정렬 (Cal 큰 순) ---')
for r in results:
    flag = ' (baseline)' if r['is_baseline'] else ''
    print(f'  V{r["V"]:>2} G{r["G"]:>2}: Cal {r["calmar"]:.3f}{flag}')

# 저장
df = pd.DataFrame(results)
out = PROJECT / 'backtest' / 'phase10_boost_VG_grid.csv'
df.to_csv(out, index=False)
print(f'\n저장: {out}, 소요 {(time.time()-t0)/60:.1f}분')
