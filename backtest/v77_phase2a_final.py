"""v77 Phase 2a — 가중치 + E/X 동시 서치 (인사이트 기반)

공격: G서브 Top 5 × 653가중치 × E/X 9개 × mom 12m-1m 고정
방어: G서브 Top 6 × 653가중치 × E/X 9개 × mom 6m-1m 고정

Usage: python v77_phase2a_final.py attack|defense
"""
import sys, json, numpy as np, pandas as pd, time, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from turbo_simulator import TurboSimulator

MODE = sys.argv[1]
DATA_DIR = Path(__file__).parent.parent / 'data_cache'
BT_DIR = Path(__file__).parent / 'bt_test_A'
RESULT_DIR = Path(__file__).parent.parent / 'backtest_results'
RESULT_DIR.mkdir(exist_ok=True)
t0 = time.time()

ohlcv = pd.read_parquet(sorted(DATA_DIR.glob('all_ohlcv_*.parquet'))[-1]).replace(0, np.nan)
bench = pd.read_parquet(DATA_DIR / 'kospi_yf.parquet')
kospi = bench.iloc[:,0].dropna(); km200 = kospi.rolling(200).mean()
dates = sorted([f.stem.replace('ranking_','') for f in BT_DIR.glob('ranking_*.json')])
rk = {}
for d in dates:
    with open(BT_DIR / f'ranking_{d}.json', 'r', encoding='utf-8') as f:
        rk[d] = json.load(f).get('rankings', [])

md = False; streak = 0; ss = False; rd = {}
for d in dates:
    ts = pd.Timestamp(d); kv = kospi.get(ts,None); mv = km200.get(ts,None)
    s = (kv > mv) if kv is not None and mv is not None else md
    if s == ss: streak += 1
    else: streak = 1; ss = s
    if streak >= 5 and md != s: md = s
    rd[d] = md

if MODE == 'attack':
    mode_dates = [d for d in dates if rd[d]]
    mom = '12m-1m'
    slots_list = [3]  # 공격 슬롯 고정
    gsub_configs = [
        # (label, g_sub1, g_sub2, g_sub3, g_w1, g_w2, g_w3, g_rev)
        ('3f_rev_oca_gp', 'rev_z','oca_z','gp_growth_z', 0.5,0.3,0.2, 0.0),
        ('3f_rev_oca_opm', 'rev_z','oca_z','op_margin_z', 0.5,0.3,0.2, 0.0),
        ('3f_rev_gp_opm', 'rev_z','gp_growth_z','op_margin_z', 0.5,0.3,0.2, 0.0),
        ('2f_oca_only', 'oca_z','oca_z', None, None,None,None, 1.0),
        ('2f_rev_oca', 'rev_z','oca_z', None, None,None,None, 0.6),
    ]
else:
    mode_dates = [d for d in dates if not rd[d]]
    mom = '6m-1m'
    slots_list = [5, 7]  # 방어 슬롯 서치
    gsub_configs = [
        ('2f_oca_opm', 'oca_z','op_margin_z', None, None,None,None, 0.6),
        ('2f_rev_opm', 'rev_z','op_margin_z', None, None,None,None, 0.7),
        ('2f_oca_raccel', 'oca_z','rev_accel_z', None, None,None,None, 0.5),
        ('2f_raccel_opm', 'rev_accel_z','op_margin_z', None, None,None,None, 0.5),
        ('3f_rev_oca_gp', 'rev_z','oca_z','gp_growth_z', 0.5,0.3,0.2, 0.0),
        ('3f_rev_oca_opm', 'rev_z','oca_z','op_margin_z', 0.5,0.3,0.2, 0.0),
    ]

# 가중치 그리드
def weight_grid():
    combos = []
    for v in range(0, 45, 5):
        for q in range(0, 45, 5):
            for g in range(10, 75, 5):
                m = 100 - v - q - g
                if 10 <= m <= 60:
                    combos.append((v, q, g, m))
    return combos

weights = weight_grid()
entry_exit = [(e, x) for e in [3, 5, 7] for x in [6, 8, 10] if x > e]

print(f'{MODE}: {len(gsub_configs)} G서브 × {len(weights)} 가중치 × {len(entry_exit)} E/X × {len(slots_list)} 슬롯', flush=True)
total = len(gsub_configs) * len(weights) * len(entry_exit) * len(slots_list)
print(f'총 {total:,}건, mom={mom} 고정', flush=True)

rk_mode = {d: rk[d] for d in mode_dates}
tsim = TurboSimulator(rk_mode, mode_dates, ohlcv, bench=bench)
print(f'init: {time.time()-t0:.0f}s', flush=True)

all_results = []
done = 0
t1 = time.time()

for label, gs1, gs2, gs3, gw1, gw2, gw3, g_rev in gsub_configs:
    t_gs = time.time()
    for v, q, g, m in weights:
        for e, x in entry_exit:
            for slots in slots_list:
                r = tsim.run_fast(v/100, q/100, g/100, m/100, g_rev,
                                 entry_param=e, exit_param=x, max_slots=slots,
                                 mom_type=mom, stop_loss=-0.10, trailing_stop=-0.15,
                                 g_sub1=gs1, g_sub2=gs2,
                                 g_sub3=gs3, g_w1=gw1, g_w2=gw2, g_w3=gw3)
                all_results.append({
                    'gsub': label, 'v': v, 'q': q, 'g': g, 'm': m,
                    'e': e, 'x': x, 's': slots,
                    'cagr': r['cagr'], 'mdd': r['mdd'], 'cal': r['calmar'],
                    'sh': r['sharpe'], 'sort': r.get('sortino', 0),
                })
    done += 1
    elapsed = time.time() - t1
    print(f'  [{done}/{len(gsub_configs)}] {label} ({time.time()-t_gs:.0f}s)', flush=True)

df = pd.DataFrame(all_results)
df.to_csv(RESULT_DIR / f'v77_phase2a_{MODE}.csv', index=False)

# 요약
summary = df.sort_values('cal', ascending=False)
print(f'\n{MODE} Phase 2a Top 15 (Cal 순):', flush=True)
print(f'{"gsub":<20} {"V":>3}{"Q":>3}{"G":>3}{"M":>3} {"E":>2}{"X":>2}{"S":>2} {"Cal":>6} {"CAGR":>7} {"MDD":>6} {"Sh":>5} {"So":>5}', flush=True)
print('-'*75, flush=True)
for _, r in summary.head(15).iterrows():
    print(f'{r["gsub"]:<20} {r["v"]:>3}{r["q"]:>3}{r["g"]:>3}{r["m"]:>3} {r["e"]:>2}{r["x"]:>2}{r["s"]:>2} {r["cal"]:>6.2f} {r["cagr"]:>+6.1f}% {r["mdd"]:>5.1f}% {r["sh"]:>5.2f} {r["sort"]:>5.2f}', flush=True)

# G서브별 최고
print(f'\nG서브별 Top1:', flush=True)
for gsub in df['gsub'].unique():
    sub = df[df['gsub']==gsub].sort_values('cal', ascending=False).iloc[0]
    print(f'  {gsub:<20} V{sub["v"]}Q{sub["q"]}G{sub["g"]}M{sub["m"]} E{sub["e"]}X{sub["x"]}S{sub["s"]} Cal={sub["cal"]:.2f} CAGR={sub["cagr"]:.1f}%', flush=True)

print(f'\n소요: {(time.time()-t0)/60:.1f}분', flush=True)

# 텔레그램
try:
    import requests
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
    top = summary.iloc[0]
    msg = f'[v77 Phase 2a {MODE} 완료]\n소요: {(time.time()-t0)/60:.0f}분\n{total:,}건\n\n'
    msg += f'Top1: {top["gsub"]} V{top["v"]}Q{top["q"]}G{top["g"]}M{top["m"]} E{top["e"]}X{top["x"]}\n'
    msg += f'Cal={top["cal"]:.2f} CAGR={top["cagr"]:.1f}% MDD={top["mdd"]:.1f}% Sh={top["sh"]:.2f}\n\n'
    msg += 'G서브별 Top1:\n'
    for gsub in df['gsub'].unique():
        sub = df[df['gsub']==gsub].sort_values('cal', ascending=False).iloc[0]
        msg += f'  {gsub}: Cal={sub["cal"]:.2f} CAGR={sub["cagr"]:.1f}%\n'
    requests.post(f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
                  data={'chat_id': TELEGRAM_PRIVATE_ID, 'text': msg}, timeout=30)
except: pass
