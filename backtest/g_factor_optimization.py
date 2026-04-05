"""G팩터 서브팩터 최적화 — 6C2=15쌍 × 21비율(0.05단위) = 315개 × 다수 세팅

TurboSimulator.run_fast(g_sub1, g_sub2) 직접 호출 → 재초기화 불필요.

Usage:
    python backtest/g_factor_optimization.py
"""
import sys, json, time
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
sys.path.insert(0, 'backtest')

import pandas as pd
import numpy as np
from pathlib import Path
from itertools import combinations

BT_DIR = Path('backtest/bt_v75')
CACHE_DIR = Path('data_cache')
RESULTS_DIR = Path('backtest_results')
RESULTS_DIR.mkdir(exist_ok=True)

G_KEYS = ['rev_z', 'oca_z', 'rev_accel_z', 'gp_growth_z', 'op_margin_z', 'cfo_growth_z']
G_LABELS = {
    'rev_z': '매출성장', 'oca_z': '영업이익변화', 'rev_accel_z': '매출가속도',
    'gp_growth_z': '매출총이익', 'op_margin_z': '이익률변화', 'cfo_growth_z': '현금흐름',
}


def main():
    t0 = time.time()
    print('=== G팩터 서브팩터 최적화 (정밀) ===\n')

    from grid_search_v75 import load_bt_rankings, load_prices
    from turbo_simulator import TurboSimulator

    all_rankings, dates = load_bt_rankings(BT_DIR)
    prices = load_prices()
    bench = pd.read_parquet(CACHE_DIR / 'bench_proxy.parquet') \
        if (CACHE_DIR / 'bench_proxy.parquet').exists() else pd.DataFrame()
    print(f'거래일: {len(dates)}')

    # 커버리지 확인
    sample = all_rankings[dates[-1]]
    print('\n서브팩터 커버리지 (최근일):')
    for gk in G_KEYS:
        cnt = sum(1 for r in sample if abs(r.get(gk, 0)) > 0.001)
        print(f'  {G_LABELS[gk]:10s}: {cnt}/{len(sample)} ({100*cnt/len(sample):.0f}%)')

    tsim = TurboSimulator(all_rankings, dates, prices, bench)
    print(f'초기화: {time.time()-t0:.0f}초\n')

    # 테스트 세팅 (공격/방어 + 다양한 가중치)
    test_configs = [
        ('공격_G50_12m1m', 0.25, 0.0, 0.50, 0.25, '12m-1m', 5, 8.0, 7, -0.10),
        ('공격_G40_12m',   0.20, 0.0, 0.40, 0.40, '12m',    5, 8.0, 7, -0.10),
        ('방어_M50_6m1m',  0.20, 0.10, 0.20, 0.50, '6m-1m', 5, 8.0, 7, -0.10),
        ('방어_M50_6m',    0.20, 0.10, 0.20, 0.50, '6m',    5, 8.0, 7, -0.10),
        ('밸런스_G30_6m',  0.15, 0.15, 0.30, 0.40, '6m',    5, 8.0, 7, -0.10),
    ]

    pairs = list(combinations(G_KEYS, 2))
    ratios = [i/20 for i in range(21)]  # 0.00, 0.05, ..., 1.00

    total = len(pairs) * len(ratios) * len(test_configs)
    print(f'{len(pairs)}쌍 × {len(ratios)}비율 × {len(test_configs)}세팅 = {total}개\n')

    results = []
    done = 0
    t1 = time.time()

    for sub1, sub2 in pairs:
        for ratio in ratios:
            for cfg_name, v, q, g, m, mom, entry, exit_, slots, sl in test_configs:
                r = tsim.run_fast(v, q, g, m, ratio,
                                  entry_param=entry, exit_param=exit_, max_slots=slots,
                                  stop_loss=sl, mom_type=mom,
                                  g_sub1=sub1, g_sub2=sub2)
                results.append({
                    'sub1': sub1, 'sub2': sub2, 'ratio': ratio,
                    'config': cfg_name,
                    'calmar': r['calmar'], 'cagr': r['cagr'],
                    'mdd': r['mdd'], 'sharpe': r['sharpe'], 'sortino': r['sortino'],
                })
                done += 1

            if done % (len(test_configs) * 5) == 0:
                elapsed = time.time() - t1
                rate = done / elapsed if elapsed > 0 else 1
                remain = (total - done) / rate
                print(f'  [{done}/{total}] {elapsed:.0f}초 | ~{remain:.0f}초 남음 | '
                      f'{G_LABELS[sub1]}+{G_LABELS[sub2]} r={ratio:.2f}', flush=True)

    df = pd.DataFrame(results)

    # === 세팅별 Top 10 ===
    for cfg in df['config'].unique():
        cdf = df[df['config'] == cfg].sort_values('calmar', ascending=False)
        print(f'\n{"="*70}')
        print(f'[{cfg}] Top 10')
        print(f'{"="*70}')
        for _, row in cdf.head(10).iterrows():
            l1, l2 = G_LABELS[row.sub1], G_LABELS[row.sub2]
            print(f'  {l1} {row.ratio:.0%} + {l2} {1-row.ratio:.0%}'
                  f' | Cal={row.calmar:.2f} CAGR={row.cagr:.1f}% MDD={row.mdd:.1f}% Sh={row.sharpe:.2f}')

    # === 종합 Borda (전체 세팅 평균) ===
    agg = df.groupby(['sub1', 'sub2', 'ratio']).agg(
        avg_cal=('calmar', 'mean'), avg_cagr=('cagr', 'mean'),
        avg_sharpe=('sharpe', 'mean'), avg_sortino=('sortino', 'mean'),
        min_cal=('calmar', 'min'),
    ).reset_index()
    agg['borda'] = (agg['avg_cal'].rank() + agg['avg_cagr'].rank() +
                    agg['avg_sharpe'].rank() + agg['avg_sortino'].rank() +
                    agg['min_cal'].rank())  # 최소 Calmar도 중요
    agg = agg.sort_values('borda', ascending=False)

    print(f'\n{"="*70}')
    print(f'종합 Borda Top 15 (5세팅 평균 + 최소 Calmar)')
    print(f'{"="*70}')
    for _, row in agg.head(15).iterrows():
        l1, l2 = G_LABELS[row.sub1], G_LABELS[row.sub2]
        print(f'  {l1} {row.ratio:.0%} + {l2} {1-row.ratio:.0%}'
              f' | avgCal={row.avg_cal:.2f} avgCGR={row.avg_cagr:.1f}%'
              f' minCal={row.min_cal:.2f} Sh={row.avg_sharpe:.2f}')

    # === 공격 vs 방어 최적 G 비교 ===
    print(f'\n{"="*70}')
    print(f'공격 vs 방어 최적 G (상위 5개)')
    print(f'{"="*70}')
    for mode in ['공격', '방어']:
        mode_df = df[df['config'].str.startswith(mode)].groupby(['sub1','sub2','ratio']).agg(
            avg_cal=('calmar','mean')).reset_index().sort_values('avg_cal', ascending=False)
        print(f'\n  [{mode}]:')
        for _, row in mode_df.head(5).iterrows():
            l1, l2 = G_LABELS[row.sub1], G_LABELS[row.sub2]
            print(f'    {l1} {row.ratio:.0%} + {l2} {1-row.ratio:.0%} | Cal={row.avg_cal:.2f}')

    # 저장
    df.to_csv(RESULTS_DIR / 'g_factor_optimization.csv', index=False)
    agg.to_csv(RESULTS_DIR / 'g_factor_borda.csv', index=False)
    print(f'\n총 소요: {(time.time()-t0)/60:.1f}분')


if __name__ == '__main__':
    main()
