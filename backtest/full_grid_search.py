"""전체 Grid Search — 프로덕션 동일 로직

Phase 1: Weight + G ratio (고정 진입/이탈로 평가)
Phase 2: Top 10 weight에서 진입/이탈/슬롯/전략유형 최적화
Phase 3: Walk-Forward 검증 + 다중검정 보정 + 안정성

Usage:
    python backtest/full_grid_search.py
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
    dates = sorted(all_rankings.keys())
    return all_rankings, dates


def generate_weight_grid(step=5, min_w=10, max_w=40):
    combos = []
    for v in range(min_w, max_w + 1, step):
        for q in range(min_w, max_w + 1, step):
            for g in range(min_w, max_w + 1, step):
                m = 100 - v - q - g
                if min_w <= m <= max_w:
                    combos.append((v, q, g, m))
    return combos


def main():
    t_start = time.time()

    # 데이터 로드
    print('=== 데이터 로드 ===')
    all_rankings, dates = load_data(['2020', '2021', '2022', '2023', '2024', '2025'])
    prices = pd.read_parquet(sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'),
                                     key=lambda f: f.stem.split('_')[2])[0])
    prices = prices.replace(0, np.nan)
    bench = pd.read_parquet(CACHE_DIR / 'index_benchmarks.parquet') \
        if (CACHE_DIR / 'index_benchmarks.parquet').exists() else pd.DataFrame()
    sim = ProductionSimulator(all_rankings, dates, prices, bench)
    print(f'{len(dates)}거래일 로드 ({dates[0]}~{dates[-1]})')

    # =========================================================
    # Phase 1: Weight + G ratio
    # =========================================================
    print('\n=== Phase 1: Weight + G ratio (1155조합) ===')
    weights = generate_weight_grid(step=5, min_w=10, max_w=40)
    g_ratios = [0.3, 0.4, 0.5, 0.6, 0.7]

    # 고정 평가 규칙: rank Top5/Top20 이탈, 슬롯 10 (단순 rank로 weight 평가)
    p1_results = []
    done = 0
    total = len(weights) * len(g_ratios)

    for (v, q, g, m), g_rev in product(weights, g_ratios):
        r = sim.run(v_w=v/100, q_w=q/100, g_w=g/100, m_w=m/100, g_rev=g_rev,
                    strategy='rank', entry_param=5, exit_param=20,
                    max_slots=10, top_n=20)
        p1_results.append({'v': v, 'q': q, 'g': g, 'm': m, 'g_rev': g_rev, **r})
        done += 1
        if done % 100 == 0:
            elapsed = time.time() - t_start
            print(f'  [{done}/{total}] {elapsed:.0f}초', flush=True)

    p1_results.sort(key=lambda x: -x['sharpe'])

    print(f'\nPhase 1 Top 10:')
    print(f'{"V":>2}{"Q":>3}{"G":>3}{"M":>3} {"Grev":>4} | {"CAGR":>6} {"Shrp":>5} {"Sort":>5} {"MDD":>5} {"Alpha":>6} {"Hold":>4}')
    print('-' * 55)
    for r in p1_results[:10]:
        print(f'{r["v"]:2d}{r["q"]:3d}{r["g"]:3d}{r["m"]:3d} {r["g_rev"]:4.1f} | '
              f'{r["cagr"]:5.1f}% {r["sharpe"]:5.3f} {r["sortino"]:5.3f} {r["mdd"]:4.1f}% {r["alpha"]:+5.1f}% {r["avg_holdings"]:4.1f}')

    # Phase 1 결과 저장
    out1 = PROJECT / 'backtest_results' / 'full_phase1_weights.json'
    out1.parent.mkdir(exist_ok=True)
    with open(out1, 'w', encoding='utf-8') as f:
        json.dump(p1_results, f, ensure_ascii=False, indent=2)

    top10_weights = p1_results[:10]

    # =========================================================
    # Phase 2: 진입/이탈/슬롯/전략유형
    # =========================================================
    print(f'\n=== Phase 2: 진입/이탈/슬롯/전략 최적화 ===')

    strategies = {
        'score': [(e, x) for e in [64, 66, 68, 70, 72, 74]
                         for x in [58, 60, 62, 64, 66, 68] if e > x],
        'rank': [(e, x) for e in [3, 5, 7, 10]
                        for x in [10, 15, 20, 25, 30] if x > e],
        'hybrid_se': [(e, x) for e in [66, 68, 70, 72]
                             for x in [15, 20, 25, 30]],
        'hybrid_re': [(e, x) for e in [3, 5, 7, 10]
                             for x in [60, 64, 68]],
    }
    slot_options = [3, 5, 7, 10, 0]
    pool_options = [15, 20, 25]

    p2_results = []
    done = 0
    total_p2 = sum(len(params) for params in strategies.values()) * len(slot_options) * len(pool_options) * len(top10_weights)
    print(f'총 {total_p2}조합')

    for w in top10_weights:
        for strat_name, param_list in strategies.items():
            for entry_p, exit_p in param_list:
                for slots in slot_options:
                    for pool in pool_options:
                        r = sim.run(
                            v_w=w['v']/100, q_w=w['q']/100, g_w=w['g']/100, m_w=w['m']/100,
                            g_rev=w['g_rev'],
                            strategy=strat_name, entry_param=entry_p, exit_param=exit_p,
                            max_slots=slots, top_n=pool,
                        )
                        p2_results.append({
                            'v': w['v'], 'q': w['q'], 'g': w['g'], 'm': w['m'],
                            'g_rev': w['g_rev'],
                            'strategy': strat_name, 'entry': entry_p, 'exit': exit_p,
                            'slots': slots, 'pool': pool,
                            **r,
                        })
                        done += 1
                        if done % 500 == 0:
                            elapsed = time.time() - t_start
                            print(f'  [{done}/{total_p2}] {elapsed:.0f}초', flush=True)

    p2_results.sort(key=lambda x: -x['sharpe'])

    print(f'\nPhase 2 Top 15:')
    print(f'{"V":>2}{"Q":>3}{"G":>3}{"M":>3} {"Grev":>4} {"Strat":>10} {"Ent":>3}{"Ext":>4} {"Slt":>3} {"Pl":>2} | {"CAGR":>6} {"Shrp":>5} {"Sort":>5} {"MDD":>5} {"Alpha":>6} {"H":>3}')
    print('-' * 80)
    for r in p2_results[:15]:
        s = r['slots'] if r['slots'] > 0 else 'inf'
        print(f'{r["v"]:2d}{r["q"]:3d}{r["g"]:3d}{r["m"]:3d} {r["g_rev"]:4.1f} {r["strategy"]:>10} {r["entry"]:3}{r["exit"]:4} {str(s):>3} {r["pool"]:2d} | '
              f'{r["cagr"]:5.1f}% {r["sharpe"]:5.3f} {r["sortino"]:5.3f} {r["mdd"]:4.1f}% {r["alpha"]:+5.1f}% {r["avg_holdings"]:3.1f}')

    out2 = PROJECT / 'backtest_results' / 'full_phase2_entry_exit.json'
    with open(out2, 'w', encoding='utf-8') as f:
        json.dump(p2_results, f, ensure_ascii=False, indent=2)

    best = p2_results[0]

    # =========================================================
    # Phase 3: Walk-Forward + 안정성
    # =========================================================
    print(f'\n=== Phase 3: Walk-Forward 검증 ===')
    print(f'최적: V{best["v"]}Q{best["q"]}G{best["g"]}M{best["m"]} Grev={best["g_rev"]} '
          f'{best["strategy"]} entry={best["entry"]} exit={best["exit"]} slots={best["slots"]} pool={best["pool"]}')

    wf_windows = [
        (['2020'], ['2021'], '2020->2021'),
        (['2020', '2021'], ['2022'], '20-21->2022(약세)'),
        (['2020', '2021', '2022'], ['2023'], '20-22->2023(횡보)'),
        (['2020', '2021', '2022', '2023'], ['2024'], '20-23->2024(강세)'),
        (['2020', '2021', '2022', '2023', '2024'], ['2025'], '20-24->2025-26'),
    ]

    print(f'\n{"윈도우":<20} {"CAGR":>6} {"Sharpe":>7} {"Sortino":>7} {"MDD":>6} {"Alpha":>7} {"Hold":>4}')
    print('-' * 65)

    wf_results = []
    for train_yrs, test_yrs, label in wf_windows:
        test_data, test_dates = load_data(test_yrs)
        test_sim = ProductionSimulator(test_data, test_dates, prices, bench)
        m = test_sim.run(
            v_w=best['v']/100, q_w=best['q']/100, g_w=best['g']/100, m_w=best['m']/100,
            g_rev=best['g_rev'],
            strategy=best['strategy'], entry_param=best['entry'], exit_param=best['exit'],
            max_slots=best['slots'], top_n=best['pool'],
        )
        print(f'{label:<20} {m["cagr"]:5.1f}% {m["sharpe"]:7.3f} {m["sortino"]:7.3f} {m["mdd"]:5.1f}% {m["alpha"]:+6.1f}% {m["avg_holdings"]:4.1f}')
        wf_results.append({'window': label, **m})

    # 팩터 안정성 (각 윈도우별 최적 weight)
    print(f'\n=== 팩터 안정성 (윈도우별 최적) ===')
    for train_yrs, test_yrs, label in wf_windows:
        train_data, train_dates = load_data(train_yrs)
        train_sim = ProductionSimulator(train_data, train_dates, prices, bench)
        best_local = None
        for w in p1_results[:20]:
            r = train_sim.run(v_w=w['v']/100, q_w=w['q']/100, g_w=w['g']/100, m_w=w['m']/100,
                             g_rev=w['g_rev'], strategy='rank', entry_param=5, exit_param=20,
                             max_slots=10, top_n=20)
            if best_local is None or r['sharpe'] > best_local['sharpe']:
                best_local = {**r, 'v': w['v'], 'q': w['q'], 'g': w['g'], 'm': w['m'], 'g_rev': w['g_rev']}
        print(f'  {label}: V{best_local["v"]}Q{best_local["q"]}G{best_local["g"]}M{best_local["m"]} Grev={best_local["g_rev"]}')

    # 다중검정 보정
    n_tests = len(p2_results)
    n_days = len(dates)
    haircut = np.sqrt(2 * np.log(n_tests) / n_days)
    adj_sharpe = best['sharpe'] - haircut
    print(f'\n=== 다중검정 보정 ===')
    print(f'테스트 수: {n_tests}, 거래일: {n_days}')
    print(f'관측 Sharpe: {best["sharpe"]:.3f}')
    print(f'Haircut: {haircut:.3f}')
    print(f'조정 Sharpe: {adj_sharpe:.3f} (>0.5면 유의)')

    elapsed = time.time() - t_start
    print(f'\n=== 전체 완료: {elapsed/60:.1f}분 ===')

    # 최종 저장
    final = {
        'best_strategy': best,
        'walk_forward': wf_results,
        'adjusted_sharpe': round(adj_sharpe, 3),
        'total_tests': n_tests,
    }
    out3 = PROJECT / 'backtest_results' / 'full_final_result.json'
    with open(out3, 'w', encoding='utf-8') as f:
        json.dump(final, f, ensure_ascii=False, indent=2)
    print(f'결과 저장: {out3}')


if __name__ == '__main__':
    main()
