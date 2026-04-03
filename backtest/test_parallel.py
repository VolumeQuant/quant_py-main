"""ProcessPoolExecutor 검증 — Windows 호환 테스트"""
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))


def simple_worker(x):
    return x * x


def heavy_worker(args):
    """TurboSimulator 로드 + 실행 테스트"""
    weight_combo, rules = args
    import pandas as pd
    import numpy as np
    import json
    import glob
    import os
    from turbo_simulator import TurboSimulator, TurboRunner

    PROJECT = Path(__file__).parent.parent

    # 데이터 로드 (각 워커가 독립적으로)
    all_rankings = {}
    for year in ['2024']:  # 테스트라 1년만
        for f in sorted(glob.glob(str(PROJECT / f'state/bt_{year}/ranking_*.json'))):
            date = os.path.basename(f).replace('ranking_', '').replace('.json', '')
            with open(f, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
                all_rankings[date] = data.get('rankings', data) if isinstance(data, dict) else data
    dates = sorted(all_rankings.keys())
    prices = pd.read_parquet(sorted(glob.glob(str(PROJECT / 'data_cache/all_ohlcv_*.parquet')),
                                     key=lambda f: f.split('_')[2])[0])
    prices = prices.replace(0, np.nan)

    tsim = TurboSimulator(all_rankings, dates, prices)
    v, q, g, m, g_rev = weight_combo
    tsim._ensure_cache(v/100, q/100, g/100, m/100, g_rev, 20)
    runner = TurboRunner(tsim)

    results = []
    for entry, exit_r, slots in rules:
        r = runner.run(entry, exit_r, slots)
        results.append({'v': v, 'q': q, 'g': g, 'm': m, 'g_rev': g_rev,
                        'entry': entry, 'exit': exit_r, 'slots': slots, **r})
    return results


if __name__ == '__main__':
    # 기본 테스트
    print('1. 기본 테스트...')
    with ProcessPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(simple_worker, i) for i in range(5)]
        results = [f.result(timeout=10) for f in futures]
    print(f'   결과: {results}')
    print('   ✅ 기본 OK')

    # TurboSimulator 테스트
    print('2. TurboSimulator 병렬 테스트...')
    tasks = [
        ((15, 25, 40, 20, 0.6), [(5, 15, 7), (3, 10, 5)]),
        ((20, 15, 40, 25, 0.4), [(5, 15, 7), (7, 20, 10)]),
        ((30, 10, 40, 20, 0.8), [(5, 15, 7)]),
    ]

    t0 = time.time()
    all_results = []
    with ProcessPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(heavy_worker, t) for t in tasks]
        for f in futures:
            batch = f.result(timeout=120)
            all_results.extend(batch)
    elapsed = time.time() - t0

    print(f'   {len(all_results)}회 실행: {elapsed:.1f}초')
    for r in all_results:
        print(f'   V{r["v"]}Q{r["q"]}G{r["g"]}M{r["m"]} g={r["g_rev"]} e={r["entry"]} x={r["exit"]} s={r["slots"]}'
              f' → CAGR={r["cagr"]:.1f}% Sharpe={r["sharpe"]:.3f} Calmar={r.get("calmar",0):.3f}')
    print('   ✅ 병렬 OK')
