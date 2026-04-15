"""v78 Phase 2b: E/X/S 규칙 서치 — Attack Top15 + Defense Top15"""
import sys, json, numpy as np, pandas as pd, time, csv, os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = Path(__file__).parent.parent / 'data_cache'
RESULT_DIR = Path(__file__).parent.parent / 'backtest_results'
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
    worker_combos = args
    rk = load_rankings()
    dates = sorted(rk.keys())
    ohlcv = pd.read_parquet(OHLCV_PATH).replace(0, np.nan)
    bench = pd.read_parquet(BENCH_PATH)
    tsim = TurboSimulator(rk, dates, ohlcv, bench=bench)

    results = []
    for combo in worker_combos:
        v, q, g, m, mom, g_name, s1, s2, s3, w1, w2, w3, entry, exit_r, slots = combo
        if s3:
            r = tsim.run_fast(v/100, q/100, g/100, m/100, 0.5,
                entry_param=entry, exit_param=exit_r, max_slots=slots, mom_type=mom,
                stop_loss=-0.10, trailing_stop=-0.15,
                g_sub1=s1, g_sub2=s2, g_sub3=s3, g_w1=w1, g_w2=w2, g_w3=w3)
        else:
            r = tsim.run_fast(v/100, q/100, g/100, m/100, w1,
                entry_param=entry, exit_param=exit_r, max_slots=slots, mom_type=mom,
                stop_loss=-0.10, trailing_stop=-0.15,
                g_sub1=s1, g_sub2=s2)
        results.append((v, q, g, m, mom, g_name, entry, exit_r, slots,
                        r['calmar'], r['cagr'], r['mdd'], r['sharpe'], r['sortino']))
    return results


# G서브 이름 → 파라미터 매핑
G_SUB_MAP = {
    'rev+oca+gp': ('rev_z', 'oca_z', 'gp_growth_z', 0.5, 0.3, 0.2),
    'rev+oca+opm': ('rev_z', 'oca_z', 'op_margin_z', 0.5, 0.3, 0.2),
    'rev+gp+opm': ('rev_z', 'gp_growth_z', 'op_margin_z', 0.5, 0.3, 0.2),
    'rev+opm 7:3': ('rev_z', 'op_margin_z', None, 0.7, None, None),
    'rev+oca 7:3': ('rev_z', 'oca_z', None, 0.7, None, None),
    'raccel+opm 5:5': ('rev_accel_z', 'op_margin_z', None, 0.5, None, None),
}

# E/X/S 규칙
EXS_RULES = []
for entry in [3, 5, 7, 10]:
    for exit_r in range(entry + 1, entry + 6):
        for slots in [3, 5, 7]:
            EXS_RULES.append((entry, exit_r, slots))


if __name__ == '__main__':
    t0 = time.time()
    print(f'OHLCV: {OHLCV_PATH}')
    print(f'E/X/S 규칙: {len(EXS_RULES)}개')

    # Attack Top 15 로드
    atk_df = pd.read_csv(RESULT_DIR / 'v78_phase2a_attack.csv')
    atk_top = atk_df.nlargest(15, 'cal')

    # Defense Top 15 로드
    def_df = pd.read_csv(RESULT_DIR / 'v78_phase2a_defense.csv')
    def_top = def_df.nlargest(15, 'cal')

    # Attack 조합 생성
    atk_combos = []
    for _, row in atk_top.iterrows():
        s1, s2, s3, w1, w2, w3 = G_SUB_MAP[row.g_sub]
        for entry, exit_r, slots in EXS_RULES:
            atk_combos.append((int(row.v), int(row.q), int(row.g), int(row.m),
                             row.mom, row.g_sub, s1, s2, s3, w1, w2, w3,
                             entry, exit_r, slots))

    # Defense 조합 생성
    def_combos = []
    for _, row in def_top.iterrows():
        s1, s2, s3, w1, w2, w3 = G_SUB_MAP[row.g_sub]
        for entry, exit_r, slots in EXS_RULES:
            def_combos.append((int(row.v), int(row.q), int(row.g), int(row.m),
                             row.mom, row.g_sub, s1, s2, s3, w1, w2, w3,
                             entry, exit_r, slots))

    print(f'Attack: {len(atk_combos)}개, Defense: {len(def_combos)}개')

    # === ATTACK ===
    print(f'\n=== ATTACK E/X/S 서치 ({len(atk_combos)}개, 3워커) ===')
    chunk_size = len(atk_combos) // 3 + 1
    atk_chunks = [atk_combos[i:i+chunk_size] for i in range(0, len(atk_combos), chunk_size)]
    atk_results = []
    with ProcessPoolExecutor(max_workers=3) as exe:
        futs = {exe.submit(run_worker, chunk): i for i, chunk in enumerate(atk_chunks)}
        for fut in as_completed(futs):
            res = fut.result()
            atk_results.extend(res)
            print(f'  워커{futs[fut]}: {len(res)}개 ({time.time()-t0:.0f}초)', flush=True)

    atk_results.sort(key=lambda x: -x[9])  # cal
    print(f'\nATTACK Top 10:')
    for i, r in enumerate(atk_results[:10]):
        v, q, g, m, mom, gn, entry, exit_r, slots, cal, cagr, mdd, sh, so = r
        print(f'  {i+1}. V{v}Q{q}G{g}M{m} {mom} {gn} E{entry}X{exit_r}S{slots}: Cal={cal:.2f} CAGR={cagr:.1f}% MDD={mdd:.1f}%')

    with open(RESULT_DIR / 'v78_phase2b_attack.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['v','q','g','m','mom','g_sub','entry','exit','slots','cal','cagr','mdd','sharpe','sortino'])
        for row in atk_results: w.writerow(row)

    # === DEFENSE ===
    t1 = time.time()
    print(f'\n=== DEFENSE E/X/S 서치 ({len(def_combos)}개, 3워커) ===')
    chunk_size = len(def_combos) // 3 + 1
    def_chunks = [def_combos[i:i+chunk_size] for i in range(0, len(def_combos), chunk_size)]
    def_results = []
    with ProcessPoolExecutor(max_workers=3) as exe:
        futs = {exe.submit(run_worker, chunk): i for i, chunk in enumerate(def_chunks)}
        for fut in as_completed(futs):
            res = fut.result()
            def_results.extend(res)
            print(f'  워커{futs[fut]}: {len(res)}개 ({time.time()-t1:.0f}초)', flush=True)

    def_results.sort(key=lambda x: -x[9])
    print(f'\nDEFENSE Top 10:')
    for i, r in enumerate(def_results[:10]):
        v, q, g, m, mom, gn, entry, exit_r, slots, cal, cagr, mdd, sh, so = r
        print(f'  {i+1}. V{v}Q{q}G{g}M{m} {mom} {gn} E{entry}X{exit_r}S{slots}: Cal={cal:.2f} CAGR={cagr:.1f}% MDD={mdd:.1f}%')

    with open(RESULT_DIR / 'v78_phase2b_defense.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['v','q','g','m','mom','g_sub','entry','exit','slots','cal','cagr','mdd','sharpe','sortino'])
        for row in def_results: w.writerow(row)

    print(f'\n전체: {time.time()-t0:.0f}초 ({(time.time()-t0)/60:.1f}분)')
