"""3팩터만 재정규화 적용 재실행 (공격+방어)

Usage: python v77_3f_rerun.py attack|defense
"""
import sys, json, numpy as np, pandas as pd, time, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from turbo_simulator import TurboSimulator

MODE = sys.argv[1]  # attack | defense
DATA_DIR = Path(__file__).parent.parent / 'data_cache'
BT_DIR = Path(__file__).parent / 'bt_test_A'
RESULT_DIR = Path(__file__).parent.parent / 'backtest_results'
t0 = time.time()

ohlcv = pd.read_parquet(sorted(DATA_DIR.glob('all_ohlcv_*.parquet'))[-1]).replace(0, np.nan)
bench = pd.read_parquet(DATA_DIR / 'kospi_yf.parquet')
kospi = bench.iloc[:, 0].dropna(); km200 = kospi.rolling(200).mean()
dates = sorted([f.stem.replace('ranking_', '') for f in BT_DIR.glob('ranking_*.json')])
rk = {}
for d in dates:
    with open(BT_DIR / f'ranking_{d}.json', 'r', encoding='utf-8') as f:
        rk[d] = json.load(f).get('rankings', [])

md = False; streak = 0; ss = False; rd = {}
for d in dates:
    ts = pd.Timestamp(d); kv = kospi.get(ts, None); mv = km200.get(ts, None)
    s = (kv > mv) if kv is not None and mv is not None else md
    if s == ss: streak += 1
    else: streak = 1; ss = s
    if streak >= 5 and md != s: md = s
    rd[d] = md

if MODE == 'attack':
    mode_dates = [d for d in dates if rd[d]]
    entry, exit_r, slots = 5, 8, 3
    weights = [
        (15, 5, 60, 20), (10, 0, 70, 20), (10, 5, 65, 20), (20, 5, 55, 20),
        (15, 0, 60, 25), (10, 5, 55, 30), (15, 10, 50, 25), (10, 0, 65, 25),
        (20, 0, 50, 30), (5, 5, 70, 20), (15, 5, 50, 30), (10, 10, 50, 30),
        (25, 5, 45, 25), (20, 10, 40, 30), (15, 5, 55, 25),
    ]
    combos_3f = [
        ('atk_3f_oca_opm_gp', 'oca_z', 'op_margin_z', 'gp_growth_z'),
        ('atk_3f_rev_oca_opm', 'rev_z', 'oca_z', 'op_margin_z'),
    ]
else:
    mode_dates = [d for d in dates if not rd[d]]
    entry, exit_r, slots = 5, 8, 5
    weights = [
        (15, 10, 25, 50), (20, 10, 20, 50), (15, 10, 20, 55), (25, 10, 20, 45),
        (15, 5, 20, 60), (20, 5, 25, 50), (10, 10, 30, 50), (15, 15, 20, 50),
        (20, 10, 25, 45), (25, 5, 20, 50), (10, 10, 20, 60), (15, 10, 30, 45),
        (20, 10, 15, 55), (25, 10, 25, 40), (10, 5, 25, 60),
    ]
    combos_3f = [
        ('def_3f_raccel_rev_opm', 'rev_accel_z', 'rev_z', 'op_margin_z'),
        ('def_3f_rev_oca_opm', 'rev_z', 'oca_z', 'op_margin_z'),
    ]

mom_types = ['6m', '6m-1m', '12m', '12m-1m']
w3_combos = [
    (0.5, 0.3, 0.2), (0.6, 0.2, 0.2), (0.4, 0.4, 0.2),
    (0.5, 0.2, 0.3), (0.4, 0.3, 0.3), (0.7, 0.2, 0.1),
    (0.3, 0.4, 0.3), (0.6, 0.3, 0.1),
]

def make_3f_normalized(rk_orig, sub1, sub2, sub3, w1, w2, w3):
    rk_new = {}
    for d, items in rk_orig.items():
        raw_vals = []
        for s in items:
            v1 = s.get(sub1, 0) or 0
            v2 = s.get(sub2, 0) or 0
            v3 = s.get(sub3, 0) or 0
            raw_vals.append(v1 * w1 + v2 * w2 + v3 * w3)
        arr = np.array(raw_vals)
        mean, std = arr.mean(), arr.std()
        normed = (arr - mean) / std if std > 0 else np.zeros(len(arr))
        new_items = []
        for i, s in enumerate(items):
            ns = dict(s)
            ns['growth_s'] = float(normed[i])
            new_items.append(ns)
        rk_new[d] = new_items
    return rk_new

print(f'{MODE} 3팩터 재정규화 재실행 ({len(mode_dates)}일)', flush=True)

all_results = []
for label, s1, s2, s3 in combos_3f:
    print(f'  {label}: {s1}+{s2}+{s3}', flush=True)
    t1 = time.time()
    for w1, w2, w3 in w3_combos:
        rk_3f = make_3f_normalized(rk, s1, s2, s3, w1, w2, w3)
        rk_mode = {d: rk_3f[d] for d in mode_dates if d in rk_3f}
        tsim = TurboSimulator(rk_mode, mode_dates, ohlcv, bench=bench)
        for mom in mom_types:
            for v, q, g, m in weights:
                r = tsim.run_fast(v/100, q/100, g/100, m/100, 0.5,
                                 entry_param=entry, exit_param=exit_r, max_slots=slots,
                                 mom_type=mom, stop_loss=-0.10, trailing_stop=-0.15)
                all_results.append({
                    'label': label, 'gr': f'{w1}/{w2}/{w3}', 'mom': mom,
                    'v': v, 'q': q, 'g': g, 'm': m,
                    'cagr': r['cagr'], 'mdd': r['mdd'], 'calmar': r['calmar'],
                    'sharpe': r['sharpe'], 'sortino': r.get('sortino', 0),
                })
    print(f'    {len(w3_combos)*len(mom_types)*len(weights)}건 ({time.time()-t1:.0f}s)', flush=True)

df = pd.DataFrame(all_results)
summary = df.groupby('label').agg(
    avg_cal=('calmar', 'mean'), max_cal=('calmar', 'max'),
    avg_cagr=('cagr', 'mean'), avg_sh=('sharpe', 'mean'),
    avg_so=('sortino', 'mean'), worst_cagr=('cagr', 'min'),
).sort_values('avg_cal', ascending=False)

print(f'\n{MODE} 3팩터 재정규화 결과:', flush=True)
for label, r in summary.iterrows():
    print(f'  {label}: avg_cal={r["avg_cal"]:.3f} max_cal={r["max_cal"]:.2f} avg_cagr={r["avg_cagr"]:.1f}% avg_sh={r["avg_sh"]:.2f} avg_so={r["avg_so"]:.2f}', flush=True)

df.to_csv(RESULT_DIR / f'v77_3f_normalized_{MODE}.csv', index=False)
print(f'소요: {(time.time()-t0)/60:.1f}분', flush=True)
