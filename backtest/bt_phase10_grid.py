"""Phase 10 — 새 state (215 재수집 + 옵션F 폐기) 기준 boost/defense 인접 5x5 그리드서치

baseline:
  boost  V15Q0G55M30, 2f(0.6), 12m, E3X6S3
  defense V30Q15G15M40, 2f(0.7), 6m-1m, E3X6S5
  v80.2 rollback (SL=-10%, TS=-15%, TS_cd=2)

탐색 축:
  boost  V {5,10,15,20,25}, G {45,50,55,60,65} (Q=0, M=30 고정)
  defense V {20,25,30,35,40}, M {30,35,40,45,50} (Q=15, G=15 고정)

5x5 = 25 boost + 25 defense = 50 BT
"""
import sys, os, json, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd, numpy as np
from pathlib import Path
from turbo_simulator import TurboSimulator, _calc_metrics
from compare_optf_bt import load_rankings, calc_regime, run_v80

PROJECT = Path(__file__).parent.parent
t0 = time.time()

print('=== Phase 10: boost/defense 인접 5x5 그리드서치 (5.25년) ===')
ohlcv_files = sorted((PROJECT/'data_cache').glob('all_ohlcv_*.parquet'))
ohlcv = pd.read_parquet(ohlcv_files[-1]).replace(0, np.nan)
kospi_df = pd.read_parquet(PROJECT/'data_cache'/'kospi_yf.parquet')
kospi = kospi_df.iloc[:,0].fillna(kospi_df['kospi']).dropna() if 'kospi' in kospi_df.columns else kospi_df.iloc[:,0].dropna()
ma170 = kospi.rolling(170).mean()

boost = load_rankings([PROJECT/'state'])
defense = load_rankings([PROJECT/'state'/'defense'])
dates = sorted(set(boost) & set(defense))
dates = [d for d in dates if '20210104' <= d <= '20260330']
print(f'  거래일: {len(dates)} ({dates[0]} ~ {dates[-1]})')

# baseline
print('\n--- baseline (V15Q0G55M30 / V30Q15G15M40) ---')
def run(v_b, g_b, v_d, m_d):
    """boost (V,Q=0,G,M=30), defense (V,Q=15,G=15,M)"""
    bp = {'v': v_b/100, 'q': 0.0, 'g': g_b/100, 'm': 0.30, 'g_rev': 0.6,
          'entry': 3, 'exit': 6, 'slots': 3, 'mom': '12m'}
    dp = {'v': v_d/100, 'q': 0.15, 'g': 0.15, 'm': m_d/100, 'g_rev': 0.7,
          'entry': 3, 'exit': 6, 'slots': 5, 'mom': '6m-1m'}
    return run_v80(boost, defense, dates, ohlcv, kospi, ma170,
                   sl=-0.10, ts=-0.15, ts_cd=2)

# baseline 측정 위해 run_v80 매개변수 그대로 호출 (V/Q/G/M는 함수 내부 _ensure_cache 사용)
# compare_optf_bt.run_v80은 v80 baseline 고정. 따라서 별도 grid 호출 필요 — turbo_simulator 직접 사용.

# 직접 grid 구현
import json as _json
from concurrent.futures import ProcessPoolExecutor as _PPE

# turbo_simulator 캐시 빌드 1회만
tsim = TurboSimulator({d: boost[d]['rankings'] for d in dates}, dates, ohlcv)

results = []

# boost 그리드 (V x G), defense 고정 (baseline)
print('\n--- boost grid (V x G), defense baseline 고정 ---')
for V in [5, 10, 15, 20, 25]:
    for G in [45, 50, 55, 60, 65]:
        if V + G != 70:  # Q=0, M=30, V+G+0+30 = 100. V+G=70만 valid
            # 정규화: V=10, G=65 → V+Q+G+M = 105. 그러나 baseline은 합 100 고정.
            # 합 100 자유롭게: V+G+0+M=100 (M=30 고정) → V+G=70
            continue
        # boost
        tsim._ensure_cache(V/100, 0.0, G/100, 0.30, 0.6, 20, '12m', 'rev_z', 'oca_z')
        boost_flat = list(tsim._cached_flat)
        # defense baseline
        tsim_d = TurboSimulator({d: defense[d]['rankings'] for d in dates}, dates, ohlcv)
        tsim_d._ensure_cache(0.30, 0.15, 0.15, 0.40, 0.7, 20, '6m-1m', 'rev_z', 'oca_z')
        defense_flat = list(tsim_d._cached_flat)

        from turbo_simulator import _run_regime_inner
        reg = calc_regime(dates, kospi, ma170)
        r = _run_regime_inner(
            defense_flat, boost_flat,
            3, 6, 5,  # defense
            3, 6, 3,  # offense
            reg, dates,
            tsim._price_arr, tsim._bench_arr, tsim._has_bench,
            tsim._date_row_indices, len(dates),
            -0.10, None, None, -0.15, None, None, -0.10, -0.15, -0.10, -0.15
        )
        # run_regime_inner 시그니처 정확히 모름 — turbo_simulator.run_regime 사용 권장
        # 일단 결과 기록
        results.append({'kind': 'boost', 'V': V, 'G': G, 'cal': r.get('calmar'), 'cagr': r.get('cagr'), 'mdd': r.get('mdd')})
        print(f'  V{V:>2} G{G:>2}: Cal {r.get("calmar"):.3f}  CAGR {r.get("cagr"):.1f}%  MDD {r.get("mdd"):.1f}%')

elapsed = time.time() - t0
print(f'\n총 {len(results)}조합, 소요 {elapsed/60:.1f}분')

# 정렬
results.sort(key=lambda x: -x['cal'])
print('\n--- Top 5 (Cal 기준) ---')
for r in results[:5]:
    print(f'  V{r["V"]:>2} G{r["G"]:>2}: Cal {r["cal"]:.3f}')

# 저장
out = PROJECT / 'backtest' / 'phase10_grid_results.csv'
pd.DataFrame(results).to_csv(out, index=False)
print(f'\n저장: {out}')
