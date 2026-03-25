"""Robust 최적화 — 전체 Sharpe 최대화 + 연도별 제약

전문가 권장:
  - 전체 기간 Sharpe 최대화
  - 모든 연도 Sharpe > 0 (약세장 포함)
  - 2022 MDD < 45%
  - 손절 -10%
  - 진입/이탈: rank 5/15, slots 7 (robust finding)

Usage:
    python backtest/robust_search.py
"""
import sys
import os
import json
import glob
import time
from pathlib import Path
from itertools import product

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from production_simulator import ProductionSimulator

PROJECT = Path(__file__).parent.parent
CACHE_DIR = PROJECT / 'data_cache'


def load_data(years):
    all_rankings = {}
    for year in years:
        for f in sorted(glob.glob(str(PROJECT / f'state/bt_{year}/ranking_*.json'))):
            date = os.path.basename(f).replace('ranking_', '').replace('.json', '')
            with open(f, 'r', encoding='utf-8') as fh:
                all_rankings[date] = json.load(fh).get('rankings', [])
    return all_rankings, sorted(all_rankings.keys())


def main():
    t0 = time.time()
    print('=== Robust 최적화 (전체 Sharpe + 연도별 제약) ===')

    # 데이터 로드
    prices = pd.read_parquet(sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'),
                                     key=lambda f: f.stem.split('_')[2])[0])
    prices = prices.replace(0, np.nan)
    bench = pd.read_parquet(CACHE_DIR / 'index_benchmarks.parquet') \
        if (CACHE_DIR / 'index_benchmarks.parquet').exists() else pd.DataFrame()

    # 연도별 데이터 로드
    year_data = {}
    for year in ['2020', '2021', '2022', '2023', '2024', '2025']:
        year_data[year] = load_data([year])

    # 전체 데이터
    all_data, all_dates = load_data(['2020', '2021', '2022', '2023', '2024', '2025'])
    print(f'전체: {len(all_dates)}거래일')

    # Weight grid
    weights = []
    for v in range(10, 41, 5):
        for q in range(10, 41, 5):
            for g in range(10, 41, 5):
                m = 100 - v - q - g
                if 10 <= m <= 40:
                    weights.append((v, q, g, m))
    g_ratios = [0.3, 0.4, 0.5, 0.6, 0.7]

    total = len(weights) * len(g_ratios)
    print(f'{len(weights)} weights x {len(g_ratios)} G ratios = {total} 조합')
    print(f'고정: rank 5/15, slots 7, pool 20, 손절 -10%')
    print()

    results = []
    done = 0

    for (v, q, g, m), g_rev in product(weights, g_ratios):
        # 전체 기간
        sim_all = ProductionSimulator(all_data, all_dates, prices, bench)
        r_all = sim_all.run(v/100, q/100, g/100, m/100, g_rev=g_rev,
                            strategy='rank', entry_param=5, exit_param=15,
                            max_slots=7, top_n=20, stop_loss=-0.10)

        # 연도별
        yearly = {}
        for year in ['2020', '2021', '2022', '2023', '2024', '2025']:
            data, dates = year_data[year]
            sim_y = ProductionSimulator(data, dates, prices, bench)
            r_y = sim_y.run(v/100, q/100, g/100, m/100, g_rev=g_rev,
                            strategy='rank', entry_param=5, exit_param=15,
                            max_slots=7, top_n=20, stop_loss=-0.10)
            yearly[year] = r_y

        # 제약 체크
        all_positive = all(yearly[y]['sharpe'] >= 0 for y in yearly)
        bear_mdd_ok = yearly['2022']['mdd'] < 45
        min_sharpe = min(yearly[y]['sharpe'] for y in yearly)

        results.append({
            'v': v, 'q': q, 'g': g, 'm': m, 'g_rev': g_rev,
            **r_all,
            'min_year_sharpe': round(min_sharpe, 3),
            'bear_2022_sharpe': yearly['2022']['sharpe'],
            'bear_2022_mdd': yearly['2022']['mdd'],
            'all_positive': all_positive,
            'bear_mdd_ok': bear_mdd_ok,
            'y2020': yearly['2020']['sharpe'],
            'y2021': yearly['2021']['sharpe'],
            'y2022': yearly['2022']['sharpe'],
            'y2023': yearly['2023']['sharpe'],
            'y2024': yearly['2024']['sharpe'],
            'y2025': yearly['2025']['sharpe'],
        })
        done += 1
        if done % 100 == 0:
            elapsed = time.time() - t0
            print(f'  [{done}/{total}] {elapsed:.0f}초', flush=True)

    # 제약 통과한 것만 필터
    passed = [r for r in results if r['all_positive'] and r['bear_mdd_ok']]
    passed.sort(key=lambda x: -x['sharpe'])

    failed = [r for r in results if not (r['all_positive'] and r['bear_mdd_ok'])]

    print(f'\n=== 결과 ===')
    print(f'전체: {len(results)}, 제약 통과: {len(passed)}, 탈락: {len(failed)}')

    if passed:
        print(f'\n=== 제약 통과 Top 15 ===')
        print(f'{"V":>2}{"Q":>3}{"G":>3}{"M":>3} {"Grev":>4} | {"CAGR":>6} {"Shrp":>5} {"MDD":>5} {"Alpha":>6} | {"20":>5} {"21":>5} {"22":>5} {"23":>5} {"24":>5} {"25":>5} | {"MinS":>5}')
        print('-' * 90)
        for r in passed[:15]:
            print(f'{r["v"]:2d}{r["q"]:3d}{r["g"]:3d}{r["m"]:3d} {r["g_rev"]:4.1f} | '
                  f'{r["cagr"]:5.1f}% {r["sharpe"]:5.3f} {r["mdd"]:4.1f}% {r["alpha"]:+5.1f}% | '
                  f'{r["y2020"]:5.2f} {r["y2021"]:5.2f} {r["y2022"]:5.2f} {r["y2023"]:5.2f} {r["y2024"]:5.2f} {r["y2025"]:5.2f} | '
                  f'{r["min_year_sharpe"]:5.3f}')

        # 제약 통과 중 최적 vs Shrinkage 비교
        best = passed[0]
        print(f'\n최적: V{best["v"]}Q{best["q"]}G{best["g"]}M{best["m"]} Grev={best["g_rev"]}')
        print(f'  전체 Sharpe: {best["sharpe"]}, 최악연도 Sharpe: {best["min_year_sharpe"]}')
        print(f'  2022 약세: Sharpe={best["bear_2022_sharpe"]}, MDD={best["bear_2022_mdd"]}%')
    else:
        print('제약 통과한 weight 없음! 제약 완화 필요.')
        # 제약 완화: all_positive만
        relaxed = [r for r in results if r['all_positive']]
        relaxed.sort(key=lambda x: -x['sharpe'])
        if relaxed:
            print(f'\n연도별 Sharpe>0만 (MDD 제약 완화): {len(relaxed)}개')
            for r in relaxed[:5]:
                print(f'  V{r["v"]}Q{r["q"]}G{r["g"]}M{r["m"]} Grev={r["g_rev"]} Sharpe={r["sharpe"]} 2022MDD={r["bear_2022_mdd"]}%')

    # 저장
    out = PROJECT / 'backtest_results' / 'robust_search.json'
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    elapsed = time.time() - t0
    print(f'\n=== 완료: {elapsed/60:.1f}분 ===')


if __name__ == '__main__':
    main()
