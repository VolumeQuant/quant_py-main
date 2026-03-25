"""모멘텀 기간 비교 결과 → 텔레그램 개인봇 전송"""
import sys, io, os, glob, json, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, r'C:\dev')
sys.path.insert(0, r'C:\dev\backtest')

import pandas as pd
import numpy as np
import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
from production_simulator import ProductionSimulator

CACHE = r'C:\dev\data_cache'
OHLCV_FILE = os.path.join(CACHE, 'all_ohlcv_20190102_20260320.parquet')

prices = pd.read_parquet(OHLCV_FILE).replace(0, np.nan)
bench = pd.read_parquet(os.path.join(CACHE, 'index_benchmarks.parquet'))

periods = {
    '6M/Vol (현행)': ['bt_2020', 'bt_2021', 'bt_2022', 'bt_2023', 'bt_2024', 'bt_2025'],
    '6M-1M/Vol': ['bt_mom_6m1m'],
    '12M-1M/Vol': ['bt_mom_12m1m'],
    '12M/Vol': ['bt_mom_12m'],
}

results = []
for label, dirnames in periods.items():
    all_rankings = {}
    for dirname in dirnames:
        state_dir = os.path.join(r'C:\dev\state', dirname)
        if not os.path.exists(state_dir):
            continue
        for f in sorted(glob.glob(os.path.join(state_dir, 'ranking_*.json'))):
            d = os.path.basename(f).replace('ranking_', '').replace('.json', '')
            with open(f, 'r', encoding='utf-8') as fh:
                all_rankings[d] = json.load(fh).get('rankings', [])
    dates = sorted(all_rankings.keys())

    if len(dates) < 100:
        results.append((label, None))
        continue

    sim = ProductionSimulator(all_rankings, dates, prices, bench)
    m = sim.run(0.20, 0.20, 0.30, 0.30, g_rev=0.7, strategy='rank',
                entry_param=5, exit_param=15, max_slots=7, stop_loss=-0.10)
    results.append((label, m))
    print(f'{label}: CAGR={m["cagr"]}% Sharpe={m["sharpe"]} MDD={m["mdd"]}%')

# 텔레그램 메시지 구성
lines = ['<b>모멘텀 기간 비교 결과 (2020-2026)</b>', '']
lines.append('V20Q20G30M30, rank≤5/rank>15, 7슬롯, 손절-10%')
lines.append('모든 조건 v70 동일, 모멘텀 기간만 변경')
lines.append('')

for label, m in results:
    if m is None:
        lines.append(f'{label}: 데이터 부족')
    else:
        mark = ' ← 현행' if '현행' in label else ''
        lines.append(f'{label}: CAGR {m["cagr"]}% | Sharpe {m["sharpe"]} | MDD {m["mdd"]}%{mark}')

lines.append('')
best = max((r for r in results if r[1]), key=lambda x: x[1]['sharpe'])
lines.append(f'최적: {best[0]} (Sharpe {best[1]["sharpe"]})')

msg = '\n'.join(lines)
print(f'\n=== 메시지 ===\n{msg}')

# 전송
r = requests.post(
    f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
    data={'chat_id': TELEGRAM_PRIVATE_ID, 'text': msg, 'parse_mode': 'HTML'},
    timeout=30
)
print(f'\n전송: {r.status_code}')
