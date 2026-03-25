"""Phase 2 병렬 실행 — Top 10 weight를 3프로세스로 분할

Phase 1 결과에서 Top 10 weight를 로드하고,
각 weight를 별도 프로세스에서 진입/이탈/슬롯/전략 테스트.

Usage:
    python backtest/run_phase2_parallel.py
"""
import sys
import os
import json
import glob
import time
import subprocess
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
PROJECT = Path(__file__).parent.parent
PYTHON = r'C:\Users\user\miniconda3\envs\volumequant\python.exe'


def run_weight_chunk(weight_indices, chunk_id):
    """weight 인덱스 리스트에 대해 Phase 2 실행"""
    script = f"""
import sys, json, glob, os, time
sys.path.insert(0, r'C:\\dev')
sys.path.insert(0, r'C:\\dev\\backtest')
import pandas as pd, numpy as np
from production_simulator import ProductionSimulator
from itertools import product

PROJECT = r'C:\\dev'
CACHE = os.path.join(PROJECT, 'data_cache')

# 데이터 로드
all_rankings = {{}}
for year in ['2020','2021','2022','2023','2024','2025']:
    for f in sorted(glob.glob(os.path.join(PROJECT, f'state/bt_{{year}}/ranking_*.json'))):
        date = os.path.basename(f).replace('ranking_','').replace('.json','')
        with open(f,'r',encoding='utf-8') as fh:
            all_rankings[date] = json.load(fh).get('rankings',[])
dates = sorted(all_rankings.keys())
prices = pd.read_parquet(sorted(glob.glob(os.path.join(CACHE,'all_ohlcv_*.parquet')),
    key=lambda f: f.split('_')[2])[0])
prices = prices.replace(0, np.nan)
bench_file = os.path.join(CACHE, 'index_benchmarks.parquet')
bench = pd.read_parquet(bench_file) if os.path.exists(bench_file) else pd.DataFrame()
sim = ProductionSimulator(all_rankings, dates, prices, bench)

# Phase 1 Top 10 로드
with open(os.path.join(PROJECT, 'backtest_results/full_phase1_weights.json'),'r',encoding='utf-8') as f:
    p1 = json.load(f)
top10 = p1[:10]
my_weights = [top10[i] for i in {weight_indices}]

strategies = {{
    'score': [(e,x) for e in [64,66,68,70,72,74] for x in [58,60,62,64,66,68] if e>x],
    'rank': [(e,x) for e in [3,5,7,10] for x in [10,15,20,25,30] if x>e],
    'hybrid_se': [(e,x) for e in [66,68,70,72] for x in [15,20,25,30]],
    'hybrid_re': [(e,x) for e in [3,5,7,10] for x in [60,64,68]],
}}
slot_options = [3,5,7,10,0]
pool_options = [15,20,25]

results = []
done = 0
t0 = time.time()

for w in my_weights:
    for strat_name, params in strategies.items():
        for entry_p, exit_p in params:
            for slots in slot_options:
                for pool in pool_options:
                    r = sim.run(w['v']/100, w['q']/100, w['g']/100, w['m']/100,
                               g_rev=w['g_rev'], strategy=strat_name,
                               entry_param=entry_p, exit_param=exit_p,
                               max_slots=slots, top_n=pool)
                    results.append({{
                        'v':w['v'],'q':w['q'],'g':w['g'],'m':w['m'],
                        'g_rev':w['g_rev'],'strategy':strat_name,
                        'entry':entry_p,'exit':exit_p,'slots':slots,'pool':pool,
                        **r}})
                    done += 1
                    if done % 200 == 0:
                        print(f'chunk{chunk_id}: [{{done}}] {{time.time()-t0:.0f}}s', flush=True)

out = os.path.join(PROJECT, f'backtest_results/phase2_chunk{chunk_id}.json')
with open(out, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False)
print(f'chunk{chunk_id}: {{len(results)}}조합 완료 {{time.time()-t0:.0f}}s')
"""
    return script


def main():
    t0 = time.time()
    print('=== Phase 2 병렬 실행 (3프로세스) ===')

    # Top 10을 3개로 분할: [0,1,2,3], [4,5,6], [7,8,9]
    chunks = [
        ([0, 1, 2, 3], 1),
        ([4, 5, 6], 2),
        ([7, 8, 9], 3),
    ]

    procs = []
    for indices, chunk_id in chunks:
        script = run_weight_chunk(indices, chunk_id)
        p = subprocess.Popen(
            [PYTHON, '-u', '-c', script],
            cwd=str(PROJECT),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace',
        )
        procs.append((p, chunk_id))
        print(f'  chunk{chunk_id}: weights {indices}, PID={p.pid}')

    # 완료 대기 + 출력
    for p, chunk_id in procs:
        for line in p.stdout:
            print(f'  {line.rstrip()}', flush=True)
        p.wait()
        print(f'  chunk{chunk_id} exit={p.returncode}')

    # 결과 병합
    print('\n=== 결과 병합 ===')
    all_results = []
    for _, chunk_id in chunks:
        cf = PROJECT / f'backtest_results/phase2_chunk{chunk_id}.json'
        if cf.exists():
            with open(cf, 'r', encoding='utf-8') as f:
                all_results.extend(json.load(f))
            cf.unlink()

    all_results.sort(key=lambda x: -x['sharpe'])

    print(f'총 {len(all_results)}조합')
    print(f'\nPhase 2 Top 15:')
    print(f'{"V":>2}{"Q":>3}{"G":>3}{"M":>3} {"Grev":>4} {"Strat":>10} {"Ent":>3}{"Ext":>4} {"Slt":>3} {"Pl":>2} | {"CAGR":>6} {"Shrp":>5} {"Sort":>5} {"MDD":>5} {"Alpha":>6} {"H":>3}')
    print('-' * 80)
    for r in all_results[:15]:
        s = r['slots'] if r['slots'] > 0 else 'inf'
        print(f'{r["v"]:2d}{r["q"]:3d}{r["g"]:3d}{r["m"]:3d} {r["g_rev"]:4.1f} {r["strategy"]:>10} {r["entry"]:3}{r["exit"]:4} {str(s):>3} {r["pool"]:2d} | '
              f'{r["cagr"]:5.1f}% {r["sharpe"]:5.3f} {r["sortino"]:5.3f} {r["mdd"]:4.1f}% {r["alpha"]:+5.1f}% {r["avg_holdings"]:3.1f}')

    # 저장
    out = PROJECT / 'backtest_results' / 'full_phase2_entry_exit.json'
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    best = all_results[0]

    # =========================================================
    # Phase 3: Walk-Forward + 안정성 + 다중검정
    # =========================================================
    print(f'\n=== Phase 3: Walk-Forward 검증 ===')
    print(f'최적: V{best["v"]}Q{best["q"]}G{best["g"]}M{best["m"]} Grev={best["g_rev"]} '
          f'{best["strategy"]} entry={best["entry"]} exit={best["exit"]} slots={best["slots"]} pool={best["pool"]}')

    # 데이터 로드 (Phase 3용)
    import pandas as pd, numpy as np
    sys.path.insert(0, str(PROJECT))
    sys.path.insert(0, str(PROJECT / 'backtest'))
    from production_simulator import ProductionSimulator

    CACHE = PROJECT / 'data_cache'
    prices = pd.read_parquet(sorted(CACHE.glob('all_ohlcv_*.parquet'),
                                     key=lambda f: f.stem.split('_')[2])[0])
    prices = prices.replace(0, np.nan)
    bench = pd.read_parquet(CACHE / 'index_benchmarks.parquet') \
        if (CACHE / 'index_benchmarks.parquet').exists() else pd.DataFrame()

    def load_rankings(years):
        data = {}
        for year in years:
            for f in sorted(glob.glob(str(PROJECT / f'state/bt_{year}/ranking_*.json'))):
                date = os.path.basename(f).replace('ranking_', '').replace('.json', '')
                with open(f, 'r', encoding='utf-8') as fh:
                    data[date] = json.load(fh).get('rankings', [])
        return data, sorted(data.keys())

    wf_windows = [
        (['2020'], ['2021'], '2020->2021'),
        (['2020', '2021'], ['2022'], '20-21->2022(약세)'),
        (['2020', '2021', '2022'], ['2023'], '20-22->2023(횡보)'),
        (['2020', '2021', '2022', '2023'], ['2024'], '20-23->2024(강세)'),
        (['2020', '2021', '2022', '2023', '2024'], ['2025'], '20-24->2025-26'),
    ]

    print(f'\n{"윈도우":<20} {"CAGR":>6} {"Sharpe":>7} {"Sortino":>7} {"MDD":>6} {"Alpha":>7} {"Hold":>4}')
    print('-' * 65)

    for train_yrs, test_yrs, label in wf_windows:
        test_data, test_dates = load_rankings(test_yrs)
        test_sim = ProductionSimulator(test_data, test_dates, prices, bench)
        m = test_sim.run(
            v_w=best['v']/100, q_w=best['q']/100, g_w=best['g']/100, m_w=best['m']/100,
            g_rev=best['g_rev'], strategy=best['strategy'],
            entry_param=best['entry'], exit_param=best['exit'],
            max_slots=best['slots'], top_n=best['pool'],
        )
        print(f'{label:<20} {m["cagr"]:5.1f}% {m["sharpe"]:7.3f} {m["sortino"]:7.3f} {m["mdd"]:5.1f}% {m["alpha"]:+6.1f}% {m["avg_holdings"]:4.1f}')

    # 팩터 안정성
    print(f'\n=== 팩터 안정성 (윈도우별 최적) ===')
    with open(PROJECT / 'backtest_results/full_phase1_weights.json', 'r', encoding='utf-8') as f:
        p1_results = json.load(f)

    for train_yrs, test_yrs, label in wf_windows:
        train_data, train_dates = load_rankings(train_yrs)
        train_sim = ProductionSimulator(train_data, train_dates, prices, bench)
        best_local = None
        for w in p1_results[:20]:
            r = train_sim.run(w['v']/100, w['q']/100, w['g']/100, w['m']/100,
                             g_rev=w['g_rev'], strategy='rank', entry_param=5, exit_param=20,
                             max_slots=10, top_n=20)
            if best_local is None or r['sharpe'] > best_local['sharpe']:
                best_local = {**r, 'v': w['v'], 'q': w['q'], 'g': w['g'], 'm': w['m'], 'g_rev': w['g_rev']}
        print(f'  {label}: V{best_local["v"]}Q{best_local["q"]}G{best_local["g"]}M{best_local["m"]} Grev={best_local["g_rev"]} Sharpe={best_local["sharpe"]:.3f}')

    # 다중검정 보정
    n_tests = len(all_results)
    all_data, all_dates = load_rankings(['2020', '2021', '2022', '2023', '2024', '2025'])
    n_days = len(all_dates)
    haircut = np.sqrt(2 * np.log(n_tests) / n_days)
    adj_sharpe = best['sharpe'] - haircut
    print(f'\n=== 다중검정 보정 ===')
    print(f'테스트 수: {n_tests}, 거래일: {n_days}')
    print(f'관측 Sharpe: {best["sharpe"]:.3f}')
    print(f'Haircut: {haircut:.3f}')
    print(f'조정 Sharpe: {adj_sharpe:.3f} (>0.5면 유의)')

    elapsed = time.time() - t0
    print(f'\n=== 전체 완료: {elapsed/60:.1f}분 ===')

    # 최종 저장
    final = {
        'best_strategy': best,
        'adjusted_sharpe': round(adj_sharpe, 3),
        'total_tests': n_tests,
    }
    out_final = PROJECT / 'backtest_results' / 'full_final_result.json'
    with open(out_final, 'w', encoding='utf-8') as f:
        json.dump(final, f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
