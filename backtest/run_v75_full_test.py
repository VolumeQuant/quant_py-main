"""v75 전체 후보 재검증 스크립트 — 새 BT 데이터(DART+FnGuide 합침) 기반"""
import sys, json, os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
sys.path.insert(0, 'backtest')
from turbo_simulator import TurboSimulator
from pathlib import Path
import pandas as pd
import numpy as np

# === 데이터 로드 ===
bt_dir = Path('backtest/bt_v75')
all_rankings = {}
for f in sorted(bt_dir.glob('ranking_*.json')):
    with open(f, encoding='utf-8') as fh:
        data = json.load(fh)
        all_rankings[f.stem.replace('ranking_', '')] = data.get('rankings', [])
dates = sorted(all_rankings.keys())

ohlcv_files = sorted(Path('data_cache').glob('all_ohlcv_*.parquet'))
full_files = [f for f in ohlcv_files if '_full' in f.stem]
if full_files:
    ohlcv_files = full_files
ohlcv_files.sort(key=lambda f: f.stem.split('_')[2])
ohlcv = pd.read_parquet(ohlcv_files[0]).replace(0, np.nan)
bench = pd.read_parquet('data_cache/bench_proxy.parquet')
tsim = TurboSimulator(all_rankings, dates, ohlcv, bench)

# === 지수 데이터 ===
kospi = pd.read_parquet('data_cache/kospi_yf.parquet').iloc[:, 0]
kosdaq = pd.read_parquet('data_cache/kosdaq_yf.parquet').iloc[:, 0]
kospi_ma60 = kospi.rolling(60).mean()
kosdaq_ma60 = kosdaq.rolling(60).mean()
kospi_ma120 = kospi.rolling(120).mean()

# === 시장 브레스 ===
print('시장 브레스 계산 중...')
ma120_df = ohlcv.rolling(120).mean()
above_ma120 = (ohlcv > ma120_df).sum(axis=1)
total_valid = ohlcv.notna().sum(axis=1)
breadth = above_ma120 / total_valid
print(f'  브레스 평균: {breadth.mean():.2f}')

# === 유틸 ===
def make_regime(rule_fn, confirm_days=3):
    regime = {}
    streak = 0
    current = 'cal3'
    prev_signal = None
    for d in dates:
        dt = pd.Timestamp(d)
        signal = rule_fn(dt)
        if signal == prev_signal:
            streak += 1
        else:
            streak = 1
        prev_signal = signal
        if streak >= confirm_days:
            current = 'boost' if signal else 'cal3'
        regime[d] = current
    return regime

def calc_stats(rets):
    cum = 1.0; peak = 1.0; mdd = 0.0
    for r in rets:
        cum *= (1 + r)
        peak = max(peak, cum)
        dd = (cum - peak) / peak
        mdd = min(mdd, dd)
    y = len(rets) / 252
    cagr = (cum ** (1/y) - 1) * 100
    mdd *= 100
    calmar = cagr / abs(mdd) if mdd != 0 else 0
    ra = np.array(rets)
    sharpe = ra.mean() * 252 / (ra.std() * np.sqrt(252)) if ra.std() > 0 else 0
    neg = ra[ra < 0]
    sortino = ra.mean() * 252 / (neg.std() * np.sqrt(252)) if len(neg) > 0 and neg.std() > 0 else 0
    return cagr, mdd, calmar, sharpe, sortino

# === 국면 규칙들 ===
def rule_kk_ma60(dt):
    k = kospi.get(dt, None); km = kospi_ma60.get(dt, None)
    q = kosdaq.get(dt, None); qm = kosdaq_ma60.get(dt, None)
    if k is None or km is None or q is None or qm is None: return False
    if pd.isna(k) or pd.isna(km) or pd.isna(q) or pd.isna(qm): return False
    return k > km and q > qm

def rule_kospi_ma60(dt):
    k = kospi.get(dt, None); km = kospi_ma60.get(dt, None)
    if k is None or km is None: return False
    if pd.isna(k) or pd.isna(km): return False
    return k > km

def rule_kospi_ma120(dt):
    k = kospi.get(dt, None); km = kospi_ma120.get(dt, None)
    if k is None or km is None: return False
    if pd.isna(k) or pd.isna(km): return False
    return k > km

def rule_breadth50(dt):
    b = breadth.get(dt, None)
    if b is None or pd.isna(b): return False
    return b > 0.50

def rule_breadth_ma60(dt):
    return rule_breadth50(dt) and rule_kospi_ma60(dt)

# === 1. 단독 전략 ===
print(f'\n{"="*80}')
print(f'1. 단독 전략 ({len(dates)}일: {dates[0]}~{dates[-1]})')
print(f'{"="*80}')
print(f'{"Name":>20} {"CAGR":>7} {"MDD":>7} {"Calmar":>7} {"Sharpe":>7} {"Sortino":>7}')
print('-' * 62)

singles = [
    ('Cal2', 20, 25, 45, 10, 0.15, 4, 6.0, 5),
    ('Cal3', 20, 20, 45, 15, 0.10, 4, 10.0, 5),
    ('Golden1-X6', 20, 10, 45, 25, 0.3, 5, 6.0, 5),
    ('CoreV25', 25, 20, 35, 20, 0.2, 5, 7.0, 5),
    ('v70', 20, 20, 30, 30, 0.7, 5, 15.0, 7),
    ('Boost_g10', 15, 5, 65, 15, 1.0, 3, 4.0, 3),
    ('Boost_g095', 15, 5, 65, 15, 0.95, 3, 4.0, 3),
    ('Boost_g09', 15, 5, 65, 15, 0.9, 3, 4.0, 3),
    ('Boost_g08', 15, 5, 65, 15, 0.8, 3, 4.0, 3),
    ('Boost_g07', 15, 5, 65, 15, 0.7, 3, 4.0, 3),
    ('Boost_g05', 15, 5, 65, 15, 0.5, 3, 4.0, 3),
    ('V15Q25G40M20', 15, 25, 40, 20, 0.7, 5, 10.0, 7),
    ('Balanced', 25, 25, 25, 25, 0.5, 5, 10.0, 5),
]

strat_rets = {}
for name, v, q, g, m, grev, entry, exit_, slots in singles:
    r = tsim.run_fast(v, q, g, m, grev, entry_param=entry, exit_param=exit_, max_slots=slots, stop_loss=-0.10)
    strat_rets[name] = r['_daily_rets']
    cagr, mdd, calmar, sharpe, sortino = calc_stats(r['_daily_rets'])
    print(f'{name:>20} {cagr:6.1f}% {mdd:6.1f}% {calmar:7.2f} {sharpe:7.2f} {sortino:7.2f}')

# === 2. 국면전환 규칙 비교 ===
print(f'\n{"="*80}')
print('2. 국면전환 규칙 비교 (Cal3 방어, Boost_g10 공격)')
print(f'{"="*80}')

regimes = {
    'KK_MA60_3d': make_regime(rule_kk_ma60, 3),
    'KK_MA60_imm': make_regime(rule_kk_ma60, 1),
    'KOSPI_MA60_3d': make_regime(rule_kospi_ma60, 3),
    'KOSPI_MA120_3d': make_regime(rule_kospi_ma120, 3),
    'Breadth50_3d': make_regime(rule_breadth50, 3),
    'Breadth+MA60_3d': make_regime(rule_breadth_ma60, 3),
}

print(f'{"Rule":>20} {"Boost%":>7} {"CAGR":>7} {"MDD":>7} {"Calmar":>7} {"Sharpe":>7} {"Sw/yr":>6}')
print('-' * 65)

for rule_name, regime in regimes.items():
    boost_days = sum(1 for v in regime.values() if v == 'boost')
    combined = [strat_rets['Boost_g10'][i] if regime.get(d, 'cal3') == 'boost' else strat_rets['Cal3'][i] for i, d in enumerate(dates)]
    cagr, mdd, calmar, sharpe, _ = calc_stats(combined)
    switches = sum(1 for i in range(1, len(dates)) if regime[dates[i]] != regime[dates[i-1]])
    sw_yr = switches / (len(dates) / 252)
    pct = boost_days / len(regime) * 100
    print(f'{rule_name:>20} {pct:5.0f}% {cagr:6.1f}% {mdd:6.1f}% {calmar:7.2f} {sharpe:7.2f} {sw_yr:5.1f}')

# === 3. 방어+공격 전 조합 (KK_MA60_3d 기준) ===
print(f'\n{"="*80}')
print('3. 방어+공격 조합 (KK_MA60_3d) — Calmar >= 1.5만 표시')
print(f'{"="*80}')

regime_kk = regimes['KK_MA60_3d']
defenses = ['Cal2', 'Cal3', 'Golden1-X6', 'CoreV25', 'v70', 'Balanced', 'V15Q25G40M20']
offenses = ['Boost_g10', 'Boost_g095', 'Boost_g09', 'Boost_g08', 'Boost_g07', 'Boost_g05']

print(f'{"Defense>Offense":>30} {"CAGR":>7} {"MDD":>7} {"Calmar":>7} {"Sharpe":>7}')
print('-' * 62)

all_combos = []
for d_name in defenses:
    if d_name not in strat_rets:
        continue
    for o_name in offenses:
        if o_name not in strat_rets:
            continue
        combined = [strat_rets[o_name][i] if regime_kk.get(d, 'cal3') == 'boost' else strat_rets[d_name][i] for i, d in enumerate(dates)]
        cagr, mdd, calmar, sharpe, sortino = calc_stats(combined)
        all_combos.append((f'{d_name}>{o_name}', cagr, mdd, calmar, sharpe, sortino))

all_combos.sort(key=lambda x: x[3], reverse=True)
for label, cagr, mdd, calmar, sharpe, sortino in all_combos:
    if calmar >= 1.5:
        print(f'{label:>30} {cagr:6.1f}% {mdd:6.1f}% {calmar:7.2f} {sharpe:7.2f}')

print(f'\n{"="*80}')
print('4. 각 국면전환 규칙별 최적 조합 TOP 3')
print(f'{"="*80}')

for rule_name, regime in regimes.items():
    combos = []
    for d_name in defenses:
        if d_name not in strat_rets: continue
        for o_name in offenses:
            if o_name not in strat_rets: continue
            combined = [strat_rets[o_name][i] if regime.get(d, 'cal3') == 'boost' else strat_rets[d_name][i] for i, d in enumerate(dates)]
            cagr, mdd, calmar, sharpe, _ = calc_stats(combined)
            combos.append((f'{d_name}>{o_name}', cagr, mdd, calmar, sharpe))
    combos.sort(key=lambda x: x[3], reverse=True)
    print(f'\n  {rule_name}:')
    for label, cagr, mdd, calmar, sharpe in combos[:3]:
        print(f'    {label:>30} Calmar={calmar:.2f} CAGR={cagr:.1f}% MDD={mdd:.1f}% Sharpe={sharpe:.2f}')

# === 5. 전체 1위 ===
print(f'\n{"="*80}')
print('5. 전체 조합 Calmar 순위 TOP 10')
print(f'{"="*80}')

mega_list = []
for rule_name, regime in regimes.items():
    for d_name in defenses:
        if d_name not in strat_rets: continue
        for o_name in offenses:
            if o_name not in strat_rets: continue
            combined = [strat_rets[o_name][i] if regime.get(d, 'cal3') == 'boost' else strat_rets[d_name][i] for i, d in enumerate(dates)]
            cagr, mdd, calmar, sharpe, sortino = calc_stats(combined)
            mega_list.append((rule_name, d_name, o_name, cagr, mdd, calmar, sharpe, sortino))

mega_list.sort(key=lambda x: x[5], reverse=True)
print(f'{"#":>3} {"Rule":>20} {"Defense":>15} {"Offense":>15} {"CAGR":>7} {"MDD":>7} {"Calmar":>7} {"Sharpe":>7}')
print('-' * 95)
for i, (rule, d, o, cagr, mdd, calmar, sharpe, sortino) in enumerate(mega_list[:10], 1):
    print(f'{i:3d} {rule:>20} {d:>15} {o:>15} {cagr:6.1f}% {mdd:6.1f}% {calmar:7.2f} {sharpe:7.2f}')
