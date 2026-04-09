"""3팩터 전체 조합 서치 (6C3=20쌍, 모멘텀 고정)

Usage: python v77_3f_all.py attack|defense
"""
import sys, json, numpy as np, pandas as pd, time, os
from itertools import combinations
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from turbo_simulator import TurboSimulator

MODE = sys.argv[1]
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
    entry, exit_r, slots, mom = 5, 8, 3, '12m-1m'
    weights = [
        (15, 5, 60, 20), (10, 0, 70, 20), (10, 5, 65, 20), (20, 5, 55, 20),
        (15, 0, 60, 25), (10, 5, 55, 30), (15, 10, 50, 25), (10, 0, 65, 25),
        (20, 0, 50, 30), (5, 5, 70, 20), (15, 5, 50, 30), (10, 10, 50, 30),
        (25, 5, 45, 25), (20, 10, 40, 30), (15, 5, 55, 25),
    ]
else:
    mode_dates = [d for d in dates if not rd[d]]
    entry, exit_r, slots, mom = 5, 8, 5, '6m-1m'
    weights = [
        (15, 10, 25, 50), (20, 10, 20, 50), (15, 10, 20, 55), (25, 10, 20, 45),
        (15, 5, 20, 60), (20, 5, 25, 50), (10, 10, 30, 50), (15, 15, 20, 50),
        (20, 10, 25, 45), (25, 5, 20, 50), (10, 10, 20, 60), (15, 10, 30, 45),
        (20, 10, 15, 55), (25, 10, 25, 40), (10, 5, 25, 60),
    ]

g_subs = ['rev_z', 'oca_z', 'rev_accel_z', 'gp_growth_z', 'op_margin_z', 'cfo_growth_z']
all_3f = list(combinations(g_subs, 3))
w3_combos = [
    (0.5, 0.3, 0.2), (0.6, 0.2, 0.2), (0.4, 0.4, 0.2),
    (0.5, 0.2, 0.3), (0.4, 0.3, 0.3), (0.7, 0.2, 0.1),
    (0.3, 0.4, 0.3), (0.6, 0.3, 0.1),
]

print(f'{MODE}: {len(all_3f)}조합 × {len(w3_combos)}비율 × {len(weights)}가중치 × mom={mom}', flush=True)
print(f'총 {len(all_3f)*len(w3_combos)*len(weights)}건', flush=True)

all_results = []
for idx, (s1, s2, s3) in enumerate(all_3f):
    t1 = time.time()
    for w1, w2, w3 in w3_combos:
        # 합산 + 정규화
        rk_3f = {}
        for d in mode_dates:
            items = rk[d]
            raw = [((items[i].get(s1,0) or 0)*w1 + (items[i].get(s2,0) or 0)*w2 + (items[i].get(s3,0) or 0)*w3) for i in range(len(items))]
            arr = np.array(raw)
            mean, std = arr.mean(), arr.std()
            normed = (arr - mean) / std if std > 0 else np.zeros(len(arr))
            rk_3f[d] = [dict(items[i], rev_z=float(normed[i]), oca_z=0.0) for i in range(len(items))]

        tsim = TurboSimulator(rk_3f, mode_dates, ohlcv, bench=bench)
        for v, q, g, m in weights:
            r = tsim.run_fast(v/100, q/100, g/100, m/100, 1.0,
                             entry_param=entry, exit_param=exit_r, max_slots=slots,
                             mom_type=mom, stop_loss=-0.10, trailing_stop=-0.15,
                             g_sub1='rev_z', g_sub2='oca_z')
            all_results.append({
                'combo': f'{s1}+{s2}+{s3}', 'ratio': f'{w1}/{w2}/{w3}',
                'v': v, 'q': q, 'g': g, 'm': m,
                'cagr': r['cagr'], 'mdd': r['mdd'], 'calmar': r['calmar'],
                'sharpe': r['sharpe'], 'sortino': r.get('sortino', 0),
            })
    print(f'  [{idx+1}/20] {s1}+{s2}+{s3} ({time.time()-t1:.0f}s)', flush=True)

df = pd.DataFrame(all_results)
summary = df.groupby('combo').agg(
    avg_cal=('calmar', 'mean'), max_cal=('calmar', 'max'),
    avg_cagr=('cagr', 'mean'), avg_sh=('sharpe', 'mean'),
    avg_so=('sortino', 'mean'), worst=('cagr', 'min'),
).sort_values('avg_cal', ascending=False)

print(f'\n{MODE} 3팩터 전체 결과:', flush=True)
for combo, r in summary.iterrows():
    print(f'  {combo:<40} avg_cal={r["avg_cal"]:.3f} max_cal={r["max_cal"]:.2f} cagr={r["avg_cagr"]:+.1f}% sh={r["avg_sh"]:.2f} worst={r["worst"]:+.1f}%', flush=True)

df.to_csv(RESULT_DIR / f'v77_3f_all_{MODE}.csv', index=False)
print(f'\n소요: {(time.time()-t0)/60:.1f}분', flush=True)

try:
    import requests
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
    msg = f'[v77 3팩터 전체 {MODE} 완료]\n소요: {(time.time()-t0)/60:.0f}분\n\nTop5:\n'
    for combo, r in summary.head(5).iterrows():
        msg += f'  {combo}: cal={r["avg_cal"]:.3f} cagr={r["avg_cagr"]:+.1f}% worst={r["worst"]:+.1f}%\n'
    requests.post(f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
                  data={'chat_id': TELEGRAM_PRIVATE_ID, 'text': msg}, timeout=30)
except: pass
