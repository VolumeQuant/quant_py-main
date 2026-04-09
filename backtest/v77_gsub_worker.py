"""v77 G서브 서치 워커 — 지정된 쌍만 처리 (병렬용)

Usage: python v77_gsub_worker.py <mode> <start> <end>
  mode: attack | defense
  start/end: g_sub_pairs 인덱스 (0-based, end 미포함)

Example: python v77_gsub_worker.py attack 0 5  → 0~4번 쌍
"""
import sys, json, numpy as np, pandas as pd, time, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from itertools import combinations
from turbo_simulator import TurboSimulator

mode = sys.argv[1]  # attack | defense
pair_start = int(sys.argv[2])
pair_end = int(sys.argv[3])

DATA_DIR = Path(__file__).parent.parent / 'data_cache'
BT_DIR = Path(__file__).parent / 'bt_test_A'
RESULT_DIR = Path(__file__).parent.parent / 'backtest_results'
RESULT_DIR.mkdir(exist_ok=True)
t0 = time.time()

ohlcv = pd.read_parquet(sorted(DATA_DIR.glob('all_ohlcv_*.parquet'))[-1]).replace(0, np.nan)
bench = pd.read_parquet(DATA_DIR / 'kospi_yf.parquet')
kospi = bench.iloc[:, 0].dropna()
km200 = kospi.rolling(200).mean()

dates = sorted([f.stem.replace('ranking_', '') for f in BT_DIR.glob('ranking_*.json')])
rk = {}
for d in dates:
    with open(BT_DIR / f'ranking_{d}.json', 'r', encoding='utf-8') as f:
        rk[d] = json.load(f).get('rankings', [])

md = False; streak = 0; ss = False; rd = {}
for d in dates:
    ts = pd.Timestamp(d)
    kv = kospi.get(ts, None); mv = km200.get(ts, None)
    s = (kv > mv) if kv is not None and mv is not None else md
    if s == ss: streak += 1
    else: streak = 1; ss = s
    if streak >= 5 and md != s: md = s
    rd[d] = md

if mode == 'attack':
    mode_dates = [d for d in dates if rd[d]]
    entry, exit_r, slots = 5, 8, 3
else:
    mode_dates = [d for d in dates if not rd[d]]
    entry, exit_r, slots = 5, 8, 5

g_sub_names = ['rev_z', 'oca_z', 'rev_accel_z', 'gp_growth_z', 'op_margin_z', 'cfo_growth_z']
all_pairs = list(combinations(g_sub_names, 2))
my_pairs = all_pairs[pair_start:pair_end]
g_revs = [round(x * 0.1, 1) for x in range(11)]

repr_weights = [
    (40, 10, 30, 20), (35, 15, 25, 25), (30, 10, 30, 30),
    (10, 40, 30, 20), (15, 35, 25, 25), (20, 30, 20, 30),
    (10, 10, 60, 20), (15, 5, 50, 30), (5, 5, 70, 20), (10, 10, 55, 25),
    (10, 10, 20, 60), (15, 10, 20, 55), (10, 5, 25, 60), (20, 10, 15, 55),
    (25, 25, 25, 25), (20, 20, 30, 30), (20, 20, 20, 40),
    (30, 5, 50, 15), (5, 30, 15, 50), (15, 15, 45, 25),
]
mom_types = ['6m', '6m-1m', '12m', '12m-1m']

print(f'{mode} 워커: 쌍 {pair_start}~{pair_end} ({len(my_pairs)}쌍), {len(mode_dates)}일', flush=True)

rk_mode = {d: rk[d] for d in mode_dates}
tsim = TurboSimulator(rk_mode, mode_dates, ohlcv, bench=bench)
print(f'init: {time.time()-t0:.0f}s', flush=True)

results = []
done = 0
total = len(my_pairs) * len(g_revs)
t1 = time.time()

for gs1, gs2 in my_pairs:
    for gr in g_revs:
        for v, q, g, m in repr_weights:
            for mom in mom_types:
                r = tsim.run_fast(v/100, q/100, g/100, m/100, gr,
                                 entry_param=entry, exit_param=exit_r, max_slots=slots,
                                 mom_type=mom, stop_loss=-0.10, trailing_stop=-0.15,
                                 g_sub1=gs1, g_sub2=gs2)
                results.append({
                    'gs1': gs1, 'gs2': gs2, 'gr': gr,
                    'v': v, 'q': q, 'g': g, 'm': m, 'mom': mom,
                    'cagr': r['cagr'], 'mdd': r['mdd'], 'cal': r['calmar'],
                    'sh': r['sharpe'], 'sort': r.get('sortino', 0),
                })
        done += 1
        if done % 10 == 0:
            elapsed = time.time() - t1
            rate = done / elapsed if elapsed > 0 else 1
            remain = (total - done) / rate / 60
            print(f'  [{mode} {pair_start}-{pair_end}] {done}/{total} ({elapsed/60:.1f}분, ~{remain:.1f}분 남음)', flush=True)

df = pd.DataFrame(results)
out = RESULT_DIR / f'v77_gsub_{mode}_{pair_start}_{pair_end}.csv'
df.to_csv(out, index=False)
print(f'저장: {out.name} ({len(df)}행, {time.time()-t0:.0f}s)', flush=True)
