"""v78 Phase 2a: 7.8년 그리드서치 — 3워커 병렬"""
import sys, json, numpy as np, pandas as pd, time, csv, os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA_DIR = Path(__file__).parent.parent / 'data_cache'
RESULT_DIR = Path(__file__).parent.parent / 'backtest_results'
RESULT_DIR.mkdir(exist_ok=True)
OHLCV_PATH = str(sorted(DATA_DIR.glob('all_ohlcv_20170601_*.parquet'))[-1])
BENCH_PATH = str(DATA_DIR / 'kospi_yf.parquet')


def load_rankings():
    rk = {}
    for d_dir in [Path(__file__).parent / 'bt_extended', Path(__file__).parent / 'bt_test_A']:
        for f in sorted(d_dir.glob('ranking_*.json')):
            d = f.stem.replace('ranking_', '')
            rk[d] = json.load(open(f, 'r', encoding='utf-8')).get('rankings', [])
    return rk


def run_worker(args):
    from turbo_simulator import TurboSimulator
    g_name, s1, s2, s3, w1, w2, w3, combos = args
    rk = load_rankings()
    dates = sorted(rk.keys())
    ohlcv = pd.read_parquet(OHLCV_PATH).replace(0, np.nan)
    bench = pd.read_parquet(BENCH_PATH)
    tsim = TurboSimulator(rk, dates, ohlcv, bench=bench)

    results = []
    for v, q, g, m, mom in combos:
        if s3:
            r = tsim.run_fast(v/100, q/100, g/100, m/100, 0.5,
                entry_param=5, exit_param=8, max_slots=5, mom_type=mom,
                stop_loss=-0.10, trailing_stop=-0.15,
                g_sub1=s1, g_sub2=s2, g_sub3=s3, g_w1=w1, g_w2=w2, g_w3=w3)
        else:
            r = tsim.run_fast(v/100, q/100, g/100, m/100, w1,
                entry_param=5, exit_param=8, max_slots=5, mom_type=mom,
                stop_loss=-0.10, trailing_stop=-0.15,
                g_sub1=s1, g_sub2=s2)
        results.append((v, q, g, m, mom, g_name, r['calmar'], r['cagr'], r['mdd'], r['sharpe'], r['sortino']))
    return results


if __name__ == '__main__':
    t0 = time.time()

    moms_atk = ['6m', '6m-1m', '12m', '12m-1m']
    atk_combos = []
    for v in range(0, 35, 5):
        for q in range(0, 20, 5):
            for g in range(20, 75, 5):
                m = 100 - v - q - g
                if m < 10 or m > 60: continue
                for mom in moms_atk:
                    atk_combos.append((v, q, g, m, mom))

    def_combos = []
    for v in range(0, 40, 5):
        for q in range(0, 25, 5):
            for g in range(0, 40, 5):
                m = 100 - v - q - g
                if m < 20 or m > 70: continue
                for mom in ['6m', '6m-1m']:
                    def_combos.append((v, q, g, m, mom))

    print(f'Attack: {len(atk_combos)}개, Defense: {len(def_combos)}개')

    # ATTACK
    g_subs_atk = [
        ('rev+oca+gp', 'rev_z', 'oca_z', 'gp_growth_z', 0.5, 0.3, 0.2),
        ('rev+oca+opm', 'rev_z', 'oca_z', 'op_margin_z', 0.5, 0.3, 0.2),
        ('rev+gp+opm', 'rev_z', 'gp_growth_z', 'op_margin_z', 0.5, 0.3, 0.2),
    ]
    print(f'=== ATTACK 3워커 병렬 ===')
    tasks = [(gn, s1, s2, s3, w1, w2, w3, atk_combos) for gn, s1, s2, s3, w1, w2, w3 in g_subs_atk]
    atk_results = []
    with ProcessPoolExecutor(max_workers=3) as exe:
        futs = {exe.submit(run_worker, t): t[0] for t in tasks}
        for fut in as_completed(futs):
            name = futs[fut]
            res = fut.result()
            atk_results.extend(res)
            print(f'  {name}: {len(res)}개 ({time.time()-t0:.0f}초)', flush=True)

    atk_results.sort(key=lambda x: -x[6])
    print(f'\nATTACK {len(atk_results)}개, {time.time()-t0:.0f}초')
    print('Top 15:')
    for i, (v, q, g, m, mom, gn, cal, cagr, mdd, sh, so) in enumerate(atk_results[:15]):
        print(f'  {i+1}. V{v}Q{q}G{g}M{m} {mom} {gn}: Cal={cal:.2f} CAGR={cagr:.1f}% MDD={mdd:.1f}%')
    with open(RESULT_DIR / 'v78_phase2a_attack.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['v', 'q', 'g', 'm', 'mom', 'g_sub', 'cal', 'cagr', 'mdd', 'sharpe', 'sortino'])
        for row in atk_results: w.writerow(row)

    # DEFENSE
    g_subs_def = [
        ('rev+opm 7:3', 'rev_z', 'op_margin_z', None, 0.7, None, None),
        ('raccel+opm 5:5', 'rev_accel_z', 'op_margin_z', None, 0.5, None, None),
        ('rev+oca 7:3', 'rev_z', 'oca_z', None, 0.7, None, None),
    ]
    t1 = time.time()
    print(f'\n=== DEFENSE 3워커 병렬 ===')
    tasks = [(gn, s1, s2, s3, w1, w2, w3, def_combos) for gn, s1, s2, s3, w1, w2, w3 in g_subs_def]
    def_results = []
    with ProcessPoolExecutor(max_workers=3) as exe:
        futs = {exe.submit(run_worker, t): t[0] for t in tasks}
        for fut in as_completed(futs):
            name = futs[fut]
            res = fut.result()
            def_results.extend(res)
            print(f'  {name}: {len(res)}개 ({time.time()-t1:.0f}초)', flush=True)

    def_results.sort(key=lambda x: -x[6])
    print(f'\nDEFENSE {len(def_results)}개, {time.time()-t1:.0f}초')
    print('Top 15:')
    for i, (v, q, g, m, mom, gn, cal, cagr, mdd, sh, so) in enumerate(def_results[:15]):
        print(f'  {i+1}. V{v}Q{q}G{g}M{m} {mom} {gn}: Cal={cal:.2f} CAGR={cagr:.1f}% MDD={mdd:.1f}%')
    with open(RESULT_DIR / 'v78_phase2a_defense.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['v', 'q', 'g', 'm', 'mom', 'g_sub', 'cal', 'cagr', 'mdd', 'sharpe', 'sortino'])
        for row in def_results: w.writerow(row)

    print(f'\n전체: {time.time()-t0:.0f}초 ({(time.time()-t0)/60:.1f}분)')
