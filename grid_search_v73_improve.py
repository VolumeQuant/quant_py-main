"""v73 개선 탐색 + Walk-Forward 검증 + 2026 OOS

1. Core 개선: G비중/g_rev 조정
2. 단일 통합 전략: Core-Boost 중간 지점
3. Walk-Forward: 2021~N → N+1 테스트
4. 2026 OOS 검증
"""
import sys, io, json, glob, os, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, 'C:/dev/claude-code/quant_py-main')
sys.path.insert(0, 'C:/dev/claude-code/quant_py-main/backtest')

import pandas as pd, numpy as np
from pathlib import Path
from turbo_simulator import TurboSimulator, TurboRunner

PROJECT = Path('C:/dev/claude-code/quant_py-main')
CACHE_DIR = PROJECT / 'data_cache'

_ohlcv_files = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'))
_full_files = [f for f in _ohlcv_files if '_full' in f.stem]
if _full_files:
    _ohlcv_files = _full_files
prices = pd.read_parquet(
    sorted(_ohlcv_files, key=lambda f: f.stem.split('_')[2])[0]
).replace(0, np.nan)

# bt_2b (Revenue Acceleration, 2021~2026)
bt2b_rankings = {}
for fp in sorted((PROJECT / 'state' / 'bt_2b').glob('ranking_*.json')):
    d = fp.stem.replace('ranking_', '')
    with open(fp, 'r', encoding='utf-8') as fh:
        data = json.load(fh)
    bt2b_rankings[d] = data.get('rankings', data) if isinstance(data, dict) else data
bt2b_dates = sorted(bt2b_rankings.keys())

# 일반 bt (2021~2025, 가속도 없음)
bt_rankings = {}
for y in range(2021, 2026):
    for fp in sorted((PROJECT / 'state' / f'bt_{y}').glob('ranking_*.json')):
        d = fp.stem.replace('ranking_', '')
        with open(fp, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        bt_rankings[d] = data.get('rankings', data) if isinstance(data, dict) else data
bt_dates = sorted(bt_rankings.keys())

print(f'bt_2b: {len(bt2b_dates)}일 ({bt2b_dates[0]}~{bt2b_dates[-1]})')
print(f'bt: {len(bt_dates)}일 ({bt_dates[0]}~{bt_dates[-1]})')

t_start = time.time()

# ============================================================
# 1. Core 개선 탐색 (bt_2b)
# ============================================================
print('\n' + '#'*60)
print('  1. Core 개선 탐색 (G비중/g_rev 조정)')
print('#'*60)

tsim_2b = TurboSimulator(bt2b_rankings, bt2b_dates, prices)
results_improve = []

for v in [15, 20, 25]:
    for q in [10, 15, 20, 25]:
        for g in [35, 40, 45, 50, 55]:
            m = 100 - v - q - g
            if m < 10 or m > 30:
                continue
            for g_rev in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6]:
                for entry in [3, 5]:
                    for exit_ in [5, 7, 10]:
                        if exit_ <= entry:
                            continue
                        for slots in [3, 5]:
                            if entry > slots:
                                continue
                            for corr in [None, 0.5]:
                                tsim_2b._ensure_cache(v/100, q/100, g/100, m/100, g_rev, 20)
                                runner = TurboRunner(tsim_2b)
                                r = runner.run(entry, exit_, slots, corr_threshold=corr)
                                if r['cagr'] > 0:
                                    results_improve.append({
                                        'v':v, 'q':q, 'g':g, 'm':m, 'g_rev':g_rev,
                                        'entry':entry, 'exit':exit_, 'slots':slots, 'corr':corr,
                                        **r
                                    })

results_improve.sort(key=lambda x: -x['calmar'])
print(f'\n총 {len(results_improve)}개 조합')
print(f'\n=== Calmar Top 20 ===')
print(f'{"#":>3} {"가중치":<16} {"g_rev":>5} {"E":>2}{"X":>3}{"S":>2} {"corr":>5} {"CAGR":>7} {"MDD":>6} {"Calmar":>7} {"Sharpe":>7}')
print('-'*70)
for i, r in enumerate(results_improve[:20]):
    w = f'V{r["v"]}Q{r["q"]}G{r["g"]}M{r["m"]}'
    c = str(r['corr']) if r['corr'] else 'None'
    marker = ''
    if r['v']==20 and r['q']==20 and r['g']==40 and r['m']==20 and r['g_rev']==0.2 and r['entry']==5 and r['exit']==7 and r['slots']==5 and r['corr']==0.5:
        marker = ' ◀Core'
    print(f'{i+1:>3} {w:<16} {r["g_rev"]:>5.1f} {r["entry"]:>2}{r["exit"]:>3}{r["slots"]:>2} {c:>5} {r["cagr"]:>+6.1f}% {r["mdd"]:>5.1f}% {r["calmar"]:>7.2f} {r["sharpe"]:>7.2f}{marker}')

# CAGR Top 20
results_by_cagr = sorted(results_improve, key=lambda x: -x['cagr'])
print(f'\n=== CAGR Top 20 ===')
print(f'{"#":>3} {"가중치":<16} {"g_rev":>5} {"E":>2}{"X":>3}{"S":>2} {"corr":>5} {"CAGR":>7} {"MDD":>6} {"Calmar":>7} {"Sharpe":>7}')
print('-'*70)
for i, r in enumerate(results_by_cagr[:20]):
    w = f'V{r["v"]}Q{r["q"]}G{r["g"]}M{r["m"]}'
    c = str(r['corr']) if r['corr'] else 'None'
    print(f'{i+1:>3} {w:<16} {r["g_rev"]:>5.1f} {r["entry"]:>2}{r["exit"]:>3}{r["slots"]:>2} {c:>5} {r["cagr"]:>+6.1f}% {r["mdd"]:>5.1f}% {r["calmar"]:>7.2f} {r["sharpe"]:>7.2f}')

# ============================================================
# 2. Walk-Forward 검증
# ============================================================
print('\n\n' + '#'*60)
print('  2. Walk-Forward 검증')
print('#'*60)

# 후보 전략들
strategies = {
    'Core현행': {'v':20,'q':20,'g':40,'m':20,'g_rev':0.2,'entry':5,'exit':7,'slots':5,'corr':0.5,'bt':'2b'},
    'Boost현행': {'v':15,'q':5,'g':65,'m':15,'g_rev':1.0,'entry':3,'exit':4,'slots':3,'corr':None,'bt':'normal'},
}

# Top 3 개선안도 추가
for i, r in enumerate(results_improve[:3]):
    strategies[f'개선{i+1}'] = {
        'v':r['v'],'q':r['q'],'g':r['g'],'m':r['m'],'g_rev':r['g_rev'],
        'entry':r['entry'],'exit':r['exit'],'slots':r['slots'],'corr':r['corr'],'bt':'2b'
    }

# Walk-Forward 기간
wf_periods = [
    ('2021~2022→2023', '20210104', '20221229', '20230102', '20231228'),
    ('2021~2023→2024', '20210104', '20231228', '20240102', '20241230'),
    ('2021~2024→2025', '20210104', '20241230', '20250102', '20251230'),
    ('2021~2025→2026', '20210104', '20251230', '20260102', '20260320'),
]

print(f'\n{"전략":<12}', end='')
for label, _, _, _, _ in wf_periods:
    test_yr = label.split('→')[1]
    print(f' {test_yr:>8}', end='')
print(f' {"전체":>8}')
print('-' * 55)

for name, cfg in strategies.items():
    if cfg['bt'] == '2b':
        rankings = bt2b_rankings
        dates = bt2b_dates
    else:
        rankings = bt_rankings
        dates = bt_dates

    print(f'{name:<12}', end='')
    for label, train_start, train_end, test_start, test_end in wf_periods:
        test_dates = [d for d in dates if test_start <= d <= test_end]
        test_rankings = {d: rankings[d] for d in test_dates if d in rankings}
        if len(test_dates) < 10:
            print(f' {"N/A":>8}', end='')
            continue
        ts = TurboSimulator(test_rankings, test_dates, prices)
        ts._ensure_cache(cfg['v']/100, cfg['q']/100, cfg['g']/100, cfg['m']/100, cfg['g_rev'], 20)
        runner = TurboRunner(ts)
        r = runner.run(cfg['entry'], cfg['exit'], cfg['slots'], corr_threshold=cfg['corr'])
        print(f' {r["cagr"]:>+7.1f}%', end='')

    # 전체 기간
    ts_full = TurboSimulator(rankings, dates, prices)
    ts_full._ensure_cache(cfg['v']/100, cfg['q']/100, cfg['g']/100, cfg['m']/100, cfg['g_rev'], 20)
    runner_full = TurboRunner(ts_full)
    r_full = runner_full.run(cfg['entry'], cfg['exit'], cfg['slots'], corr_threshold=cfg['corr'])
    print(f' {r_full["cagr"]:>+7.1f}%')

# MDD도 표시
print(f'\n{"전략":<12}', end='')
for label, _, _, _, _ in wf_periods:
    test_yr = label.split('→')[1]
    print(f' {test_yr:>8}', end='')
print(f' {"전체":>8}')
print('-' * 55)

for name, cfg in strategies.items():
    if cfg['bt'] == '2b':
        rankings = bt2b_rankings
        dates = bt2b_dates
    else:
        rankings = bt_rankings
        dates = bt_dates

    print(f'{name:<12}', end='')
    for label, train_start, train_end, test_start, test_end in wf_periods:
        test_dates = [d for d in dates if test_start <= d <= test_end]
        test_rankings = {d: rankings[d] for d in test_dates if d in rankings}
        if len(test_dates) < 10:
            print(f' {"N/A":>8}', end='')
            continue
        ts = TurboSimulator(test_rankings, test_dates, prices)
        ts._ensure_cache(cfg['v']/100, cfg['q']/100, cfg['g']/100, cfg['m']/100, cfg['g_rev'], 20)
        runner = TurboRunner(ts)
        r = runner.run(cfg['entry'], cfg['exit'], cfg['slots'], corr_threshold=cfg['corr'])
        print(f' {r["mdd"]:>7.1f}%', end='')

    ts_full = TurboSimulator(rankings, dates, prices)
    ts_full._ensure_cache(cfg['v']/100, cfg['q']/100, cfg['g']/100, cfg['m']/100, cfg['g_rev'], 20)
    runner_full = TurboRunner(ts_full)
    r_full = runner_full.run(cfg['entry'], cfg['exit'], cfg['slots'], corr_threshold=cfg['corr'])
    print(f' {r_full["mdd"]:>7.1f}%')

print(f'\n총 소요: {(time.time()-t_start)/60:.1f}분')
print('완료!')
