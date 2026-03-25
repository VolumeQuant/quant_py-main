"""최종 최적화 — Training/Validation/Test 분할 + Shrinkage

Training:   2020-2023 (파라미터 최적화)
Validation: 2024 (후보 중 최종 선택)
Test:       2025-2026 (1회 실행, 최종 판정)

Usage:
    python backtest/final_optimization.py
"""
import sys
import os
import json
import glob
import time
import subprocess
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
PYTHON = r'C:\Users\user\miniconda3\envs\volumequant\python.exe'


def load_data(years):
    all_rankings = {}
    for year in years:
        for f in sorted(glob.glob(str(PROJECT / f'state/bt_{year}/ranking_*.json'))):
            date = os.path.basename(f).replace('ranking_', '').replace('.json', '')
            with open(f, 'r', encoding='utf-8') as fh:
                all_rankings[date] = json.load(fh).get('rankings', [])
    return all_rankings, sorted(all_rankings.keys())


def generate_weight_grid(step=5, min_w=10, max_w=40):
    combos = []
    for v in range(min_w, max_w + 1, step):
        for q in range(min_w, max_w + 1, step):
            for g in range(min_w, max_w + 1, step):
                m = 100 - v - q - g
                if min_w <= m <= max_w:
                    combos.append((v, q, g, m))
    return combos


def shrink(optimal, equal=25, ratio=0.5):
    """최적값을 동일가중 쪽으로 수축"""
    return round(optimal * (1 - ratio) + equal * ratio)


def main():
    t_start = time.time()
    print('=' * 60)
    print('최종 최적화 (Training/Validation/Test)')
    print('=' * 60)

    # 데이터 로드
    prices = pd.read_parquet(sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'),
                                     key=lambda f: f.stem.split('_')[2])[0])
    prices = prices.replace(0, np.nan)
    bench = pd.read_parquet(CACHE_DIR / 'index_benchmarks.parquet') \
        if (CACHE_DIR / 'index_benchmarks.parquet').exists() else pd.DataFrame()

    # =========================================================
    # Phase 1: Training (2020-2023) Weight 최적화
    # =========================================================
    print('\n=== Phase 1: Training (2020-2023) Weight 최적화 ===')
    train_data, train_dates = load_data(['2020', '2021', '2022', '2023'])
    train_sim = ProductionSimulator(train_data, train_dates, prices, bench)
    print(f'Training: {len(train_dates)}거래일 ({train_dates[0]}~{train_dates[-1]})')

    weights = generate_weight_grid(step=5, min_w=10, max_w=40)
    g_ratios = [0.3, 0.4, 0.5, 0.6, 0.7]

    p1_results = []
    done = 0
    total = len(weights) * len(g_ratios)

    for (v, q, g, m), g_rev in product(weights, g_ratios):
        r = train_sim.run(v_w=v/100, q_w=q/100, g_w=g/100, m_w=m/100, g_rev=g_rev,
                          strategy='rank', entry_param=5, exit_param=20,
                          max_slots=10, top_n=20)
        p1_results.append({'v': v, 'q': q, 'g': g, 'm': m, 'g_rev': g_rev, **r})
        done += 1
        if done % 100 == 0:
            print(f'  [{done}/{total}] {time.time()-t_start:.0f}초', flush=True)

    p1_results.sort(key=lambda x: -x['sharpe'])

    print(f'\nPhase 1 Top 10 (Training 2020-2023):')
    print(f'{"V":>2}{"Q":>3}{"G":>3}{"M":>3} {"Grev":>4} | {"CAGR":>6} {"Shrp":>5} {"Sort":>5} {"MDD":>5} {"Alpha":>6}')
    print('-' * 50)
    for r in p1_results[:10]:
        print(f'{r["v"]:2d}{r["q"]:3d}{r["g"]:3d}{r["m"]:3d} {r["g_rev"]:4.1f} | '
              f'{r["cagr"]:5.1f}% {r["sharpe"]:5.3f} {r["sortino"]:5.3f} {r["mdd"]:4.1f}% {r["alpha"]:+5.1f}%')

    top10 = p1_results[:10]

    # Top 10을 파일로 저장 (chunk에서 읽기 위해)
    top10_clean = [{k: v for k, v in w.items() if k in ('v','q','g','m','g_rev')} for w in top10]
    top10_file = PROJECT / 'backtest_results' / 'final_p1_top10.json'
    with open(top10_file, 'w', encoding='utf-8') as f:
        json.dump(top10_clean, f, ensure_ascii=False)

    # =========================================================
    # Phase 2: Training (2020-2023) 진입/이탈/슬롯 최적화 — 3병렬
    # =========================================================
    print(f'\n=== Phase 2: 진입/이탈/슬롯 최적화 (3병렬) ===')

    chunks = [
        ('0,1,2,3', '1'),
        ('4,5,6', '2'),
        ('7,8,9', '3'),
    ]

    procs = []
    for indices, chunk_id in chunks:
        p = subprocess.Popen(
            [PYTHON, '-u', str(PROJECT / 'backtest/run_chunk.py'),
             indices, chunk_id, '2020,2021,2022,2023'],
            cwd=str(PROJECT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace',
        )
        procs.append((p, chunk_id))
        print(f'  chunk{chunk_id}: weights [{indices}], PID={p.pid}')

    for p, chunk_id in procs:
        for line in p.stdout:
            print(f'  {line.rstrip()}', flush=True)
        p.wait()

    # 병합
    all_p2 = []
    for _, chunk_id in chunks:
        cf = PROJECT / f'backtest_results/final_p2_chunk{chunk_id}.json'
        if cf.exists():
            with open(cf, 'r', encoding='utf-8') as f:
                all_p2.extend(json.load(f))
            cf.unlink()
    all_p2.sort(key=lambda x: -x['sharpe'])

    print(f'\nPhase 2 Top 10 (Training):')
    print(f'{"V":>2}{"Q":>3}{"G":>3}{"M":>3} {"Grev":>4} {"Strat":>10} {"Ent":>3}{"Ext":>4} {"Slt":>3} {"Pl":>2} | {"CAGR":>6} {"Shrp":>5} {"Sort":>5} {"MDD":>5}')
    print('-' * 70)
    for r in all_p2[:10]:
        s = r['slots'] if r['slots'] > 0 else 'inf'
        print(f'{r["v"]:2d}{r["q"]:3d}{r["g"]:3d}{r["m"]:3d} {r["g_rev"]:4.1f} {r["strategy"]:>10} {r["entry"]:3}{r["exit"]:4} {str(s):>3} {r["pool"]:2d} | '
              f'{r["cagr"]:5.1f}% {r["sharpe"]:5.3f} {r["sortino"]:5.3f} {r["mdd"]:4.1f}%')

    # =========================================================
    # Validation: 2024에서 Top 3 비교
    # =========================================================
    print(f'\n=== Validation (2024) ===')
    val_data, val_dates = load_data(['2024'])
    val_sim = ProductionSimulator(val_data, val_dates, prices, bench)
    print(f'Validation: {len(val_dates)}거래일')

    top3 = all_p2[:3]
    val_results = []
    for i, r in enumerate(top3):
        m = val_sim.run(r['v']/100, r['q']/100, r['g']/100, r['m']/100,
                        g_rev=r['g_rev'], strategy=r['strategy'],
                        entry_param=r['entry'], exit_param=r['exit'],
                        max_slots=r['slots'], top_n=r['pool'])
        val_results.append({'rank': i+1, **r, 'val_sharpe': m['sharpe'],
                           'val_cagr': m['cagr'], 'val_mdd': m['mdd'], 'val_sortino': m['sortino']})
        print(f'  #{i+1} V{r["v"]}Q{r["q"]}G{r["g"]}M{r["m"]} {r["strategy"]} → '
              f'Val CAGR={m["cagr"]}% Sharpe={m["sharpe"]} MDD={m["mdd"]}%')

    # Validation Sharpe 기준 최종 선택
    val_results.sort(key=lambda x: -x['val_sharpe'])
    selected = val_results[0]
    print(f'\nValidation 최적: V{selected["v"]}Q{selected["q"]}G{selected["g"]}M{selected["m"]} '
          f'{selected["strategy"]} entry={selected["entry"]} exit={selected["exit"]} '
          f'slots={selected["slots"]} pool={selected["pool"]}')

    # =========================================================
    # Shrinkage 적용
    # =========================================================
    print(f'\n=== Shrinkage (50%) ===')
    original = {'v': selected['v'], 'q': selected['q'],
                'g': selected['g'], 'm': selected['m']}
    shrunk = {
        'v': shrink(selected['v']), 'q': shrink(selected['q']),
        'g': shrink(selected['g']), 'm': shrink(selected['m']),
    }
    # 합이 100이 되도록 조정
    diff = 100 - sum(shrunk.values())
    shrunk['m'] += diff

    print(f'  원래:    V{original["v"]} Q{original["q"]} G{original["g"]} M{original["m"]}')
    print(f'  Shrunk:  V{shrunk["v"]} Q{shrunk["q"]} G{shrunk["g"]} M{shrunk["m"]}')

    # =========================================================
    # Test: 2025-2026 (1회만!)
    # =========================================================
    print(f'\n=== TEST (2025-2026) — 최종 판정 ===')
    test_data, test_dates = load_data(['2025'])
    test_sim = ProductionSimulator(test_data, test_dates, prices, bench)
    print(f'Test: {len(test_dates)}거래일')

    # 원래 파라미터
    m_orig = test_sim.run(selected['v']/100, selected['q']/100,
                          selected['g']/100, selected['m']/100,
                          g_rev=selected['g_rev'], strategy=selected['strategy'],
                          entry_param=selected['entry'], exit_param=selected['exit'],
                          max_slots=selected['slots'], top_n=selected['pool'])

    # Shrunk 파라미터
    m_shrunk = test_sim.run(shrunk['v']/100, shrunk['q']/100,
                            shrunk['g']/100, shrunk['m']/100,
                            g_rev=selected['g_rev'], strategy=selected['strategy'],
                            entry_param=selected['entry'], exit_param=selected['exit'],
                            max_slots=selected['slots'], top_n=selected['pool'])

    # 현재 v69 비교
    m_v69 = test_sim.run(0.25, 0.25, 0.25, 0.25, g_rev=0.5,
                         strategy='score', entry_param=72, exit_param=68,
                         max_slots=5, top_n=20)

    print(f'\n{"전략":<20} {"CAGR":>6} {"Sharpe":>7} {"Sortino":>7} {"MDD":>6} {"Alpha":>7}')
    print('-' * 55)
    print(f'{"현재 v69":<20} {m_v69["cagr"]:5.1f}% {m_v69["sharpe"]:7.3f} {m_v69["sortino"]:7.3f} {m_v69["mdd"]:5.1f}% {m_v69["alpha"]:+6.1f}%')
    print(f'{"최적(원래)":<20} {m_orig["cagr"]:5.1f}% {m_orig["sharpe"]:7.3f} {m_orig["sortino"]:7.3f} {m_orig["mdd"]:5.1f}% {m_orig["alpha"]:+6.1f}%')
    print(f'{"최적(Shrunk)":<20} {m_shrunk["cagr"]:5.1f}% {m_shrunk["sharpe"]:7.3f} {m_shrunk["sortino"]:7.3f} {m_shrunk["mdd"]:5.1f}% {m_shrunk["alpha"]:+6.1f}%')

    # 다중검정 보정
    n_tests = len(all_p2)
    n_days = len(train_dates)
    haircut = np.sqrt(2 * np.log(n_tests) / n_days)
    adj_sharpe = selected['sharpe'] - haircut
    print(f'\n다중검정: 관측 Sharpe={selected["sharpe"]:.3f} - haircut {haircut:.3f} = 조정 {adj_sharpe:.3f}')

    elapsed = time.time() - t_start
    print(f'\n=== 전체 완료: {elapsed/60:.1f}분 ===')

    # 저장
    final = {
        'selected': {k: v for k, v in selected.items() if k not in ('val_sharpe','val_cagr','val_mdd','val_sortino','rank')},
        'shrunk_weights': shrunk,
        'test_original': m_orig,
        'test_shrunk': m_shrunk,
        'test_v69': m_v69,
        'adjusted_sharpe': round(adj_sharpe, 3),
    }
    out = PROJECT / 'backtest_results' / 'final_result.json'
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(final, f, ensure_ascii=False, indent=2)
    print(f'저장: {out}')


if __name__ == '__main__':
    main()
