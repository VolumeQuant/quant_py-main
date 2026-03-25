"""앙상블 비교 — 개별 전략 vs 2/3 투표 앙상블"""
import sys
import json
import glob
import os
import time

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r'C:\dev')
sys.path.insert(0, r'C:\dev\backtest')

import pandas as pd
import numpy as np
from production_simulator import ProductionSimulator

CACHE = r'C:\dev\data_cache'
t0 = time.time()

# 데이터 로드
all_rankings = {}
for year in ['2020', '2021', '2022', '2023', '2024', '2025']:
    for f in sorted(glob.glob(os.path.join(r'C:\dev', f'state/bt_{year}/ranking_*.json'))):
        date = os.path.basename(f).replace('ranking_', '').replace('.json', '')
        with open(f, 'r', encoding='utf-8') as fh:
            all_rankings[date] = json.load(fh).get('rankings', [])
dates = sorted(all_rankings.keys())
prices = pd.read_parquet(sorted(glob.glob(os.path.join(CACHE, 'all_ohlcv_*.parquet')),
                                 key=lambda f: f.split('_')[2])[0])
prices = prices.replace(0, np.nan)
bench = pd.read_parquet(os.path.join(CACHE, 'index_benchmarks.parquet'))
print(f'데이터: {len(dates)}거래일')

# 앙상블 전략 3개
strategies = [
    {'label': 'A_MoQ', 'v': 20, 'q': 20, 'g': 30, 'm': 30, 'g_rev': 0.7,
     'strategy': 'rank', 'entry': 5, 'exit': 15, 'slots': 7, 'pool': 20},
    {'label': 'B_Grw', 'v': 25, 'q': 10, 'g': 40, 'm': 25, 'g_rev': 0.4,
     'strategy': 'rank', 'entry': 5, 'exit': 15, 'slots': 10, 'pool': 15},
    {'label': 'C_Hyb', 'v': 20, 'q': 15, 'g': 40, 'm': 25, 'g_rev': 0.6,
     'strategy': 'hybrid_re', 'entry': 7, 'exit': 64, 'slots': 7, 'pool': 25},
]

# 각 전략 개별 성과
print('\n=== 개별 전략 성과 ===')
individual = {}
for strat in strategies:
    sim = ProductionSimulator(all_rankings, dates, prices, bench)
    m = sim.run(strat['v'] / 100, strat['q'] / 100, strat['g'] / 100, strat['m'] / 100,
                g_rev=strat['g_rev'], strategy=strat['strategy'],
                entry_param=strat['entry'], exit_param=strat['exit'],
                max_slots=strat['slots'], top_n=strat['pool'])
    individual[strat['label']] = m
    print(f"  {strat['label']}: CAGR={m['cagr']}% Sharpe={m['sharpe']} Sortino={m['sortino']} MDD={m['mdd']}%")

# 각 전략의 일별 보유 종목 추출
print('\n앙상블 시뮬레이션...')
daily_holdings = {s['label']: {} for s in strategies}

for strat in strategies:
    sim = ProductionSimulator(all_rankings, dates, prices, bench)
    portfolio = {}

    for i, date in enumerate(dates):
        if i < 2:
            daily_holdings[strat['label']][date] = set()
            continue

        rankings = all_rankings.get(date, [])
        if not rankings:
            daily_holdings[strat['label']][date] = set(portfolio.keys())
            continue

        d0, d1, d2 = dates[i], dates[i - 1], dates[i - 2]
        scored_t0 = sim._reweight(all_rankings.get(d0, []), strat['v'] / 100, strat['q'] / 100,
                                   strat['g'] / 100, strat['m'] / 100, strat['g_rev'])
        scored_t1 = sim._reweight(all_rankings.get(d1, []), strat['v'] / 100, strat['q'] / 100,
                                   strat['g'] / 100, strat['m'] / 100, strat['g_rev'])
        scored_t2 = sim._reweight(all_rankings.get(d2, []), strat['v'] / 100, strat['q'] / 100,
                                   strat['g'] / 100, strat['m'] / 100, strat['g_rev'])

        pipeline = sim._compute_status(scored_t0, scored_t1, scored_t2, strat['pool'])
        status_map = {s['ticker']: s for s in pipeline}

        # 매도
        for tk in list(portfolio.keys()):
            s = status_map.get(tk)
            should_exit = s is None
            if not should_exit:
                if strat['strategy'] in ('rank',):
                    should_exit = s['weighted_rank'] > strat['exit']
                elif strat['strategy'] in ('hybrid_re', 'score'):
                    should_exit = s['score_100'] < strat['exit']
            if should_exit:
                del portfolio[tk]

        # 매수
        for s in pipeline:
            if s['ticker'] in portfolio or s['price'] is None or s['status'] != 'verified':
                continue
            if strat['slots'] > 0 and len(portfolio) >= strat['slots']:
                break
            enter = False
            if strat['strategy'] in ('rank', 'hybrid_re'):
                enter = s['weighted_rank'] <= strat['entry']
            elif strat['strategy'] == 'score':
                enter = s['score_100'] >= strat['entry']
            if enter:
                portfolio[s['ticker']] = s['price']

        daily_holdings[strat['label']][date] = set(portfolio.keys())

# 앙상블: 2/3 투표
ensemble_daily_rets = []
bench_daily_rets = []
ensemble_holdings = []

for i, date in enumerate(dates):
    if i < 2:
        ensemble_daily_rets.append(0)
        bench_daily_rets.append(0)
        ensemble_holdings.append(0)
        continue

    h_a = daily_holdings[strategies[0]['label']].get(date, set())
    h_b = daily_holdings[strategies[1]['label']].get(date, set())
    h_c = daily_holdings[strategies[2]['label']].get(date, set())

    consensus = set()
    for tk in h_a | h_b | h_c:
        votes = (tk in h_a) + (tk in h_b) + (tk in h_c)
        if votes >= 2:
            consensus.add(tk)

    ensemble_holdings.append(len(consensus))

    if i + 1 < len(dates) and consensus:
        next_ts = pd.Timestamp(dates[i + 1])
        cur_ts = pd.Timestamp(date)
        if next_ts in prices.index and cur_ts in prices.index:
            rets = []
            for tk in consensus:
                if tk in prices.columns:
                    c = prices.loc[next_ts, tk]
                    p = prices.loc[cur_ts, tk]
                    if pd.notna(c) and pd.notna(p) and p > 0:
                        rets.append(c / p - 1)
            ensemble_daily_rets.append(np.mean(rets) if rets else 0)

            if next_ts in bench.index and cur_ts in bench.index:
                b_c = bench.loc[next_ts].iloc[0]
                b_p = bench.loc[cur_ts].iloc[0]
                bench_daily_rets.append((b_c / b_p - 1) if (pd.notna(b_c) and pd.notna(b_p) and b_p > 0) else 0)
            else:
                bench_daily_rets.append(0)
        else:
            ensemble_daily_rets.append(0)
            bench_daily_rets.append(0)
    else:
        ensemble_daily_rets.append(0)
        bench_daily_rets.append(0)

# 앙상블 메트릭
arr = np.array(ensemble_daily_rets)
equity = np.cumprod(1 + arr)
n = len(arr)
cagr = (equity[-1] ** (252 / max(n, 1)) - 1) * 100
sharpe = arr.mean() / arr.std() * np.sqrt(252) if arr.std() > 0 else 0
down = arr[arr < 0]
sortino = (arr.mean() / down.std() * np.sqrt(252)) if len(down) > 0 and down.std() > 0 else sharpe
peak = np.maximum.accumulate(np.concatenate([[1], equity]))
dd = (np.concatenate([[1], equity]) - peak) / peak
mdd = abs(dd.min()) * 100
b_arr = np.array(bench_daily_rets)
b_eq = np.cumprod(1 + b_arr)
b_cagr = (b_eq[-1] ** (252 / max(len(b_arr), 1)) - 1) * 100
avg_h = np.mean(ensemble_holdings[2:])

print(f'\n=== 비교 (2020-2026) ===')
print(f'{"전략":<18} {"CAGR":>6} {"Sharpe":>7} {"Sortino":>7} {"MDD":>6} {"Alpha":>7} {"Hold":>4}')
print('-' * 58)
for strat in strategies:
    m = individual[strat['label']]
    print(f'{strat["label"]:<18} {m["cagr"]:5.1f}% {m["sharpe"]:7.3f} {m["sortino"]:7.3f} {m["mdd"]:5.1f}% {m["alpha"]:+6.1f}% {m["avg_holdings"]:4.1f}')
print(f'{"Ensemble(2/3)":<18} {cagr:5.1f}% {sharpe:7.3f} {sortino:7.3f} {mdd:5.1f}% {cagr - b_cagr:+6.1f}% {avg_h:4.1f}')

elapsed = time.time() - t0
print(f'\n완료: {elapsed:.0f}초')
