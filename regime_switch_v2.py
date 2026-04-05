"""국면 전환 v2 — TurboSimulator 일별 수익률 기반

두 전략을 각각 전체 기간 돌린 뒤,
매일 국면에 따라 어느 전략의 수익률을 쓸지 선택.
"""
import sys, io, json, glob, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, 'C:/dev/claude-code/quant_py-main')
sys.path.insert(0, 'C:/dev/claude-code/quant_py-main/backtest')

import pandas as pd, numpy as np
from pathlib import Path
from turbo_simulator import TurboSimulator, TurboRunner, _calc_metrics

PROJECT = Path('C:/dev/claude-code/quant_py-main')
CACHE_DIR = PROJECT / 'data_cache'

_ohlcv_files = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'))
_full_files = [f for f in _ohlcv_files if '_full' in f.stem]
if _full_files:
    _ohlcv_files = _full_files
prices = pd.read_parquet(
    sorted(_ohlcv_files, key=lambda f: f.stem.split('_')[2])[0]
).replace(0, np.nan)

# bt_2b
bt2b_r = {}
for fp in sorted((PROJECT / 'state' / 'bt_2b').glob('ranking_*.json')):
    d = fp.stem.replace('ranking_', '')
    with open(fp, 'r', encoding='utf-8') as fh:
        data = json.load(fh)
    bt2b_r[d] = data.get('rankings', data) if isinstance(data, dict) else data
bt2b_d = sorted(bt2b_r.keys())

# 일반 bt
bt_r = {}
for y in range(2021, 2026):
    for fp in sorted((PROJECT / 'state' / f'bt_{y}').glob('ranking_*.json')):
        d = fp.stem.replace('ranking_', '')
        with open(fp, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        bt_r[d] = data.get('rankings', data) if isinstance(data, dict) else data
bt_d = sorted(bt_r.keys())

# Regime 데이터
regime_df = pd.read_parquet(CACHE_DIR / 'regime_daily.parquet')
regime_map = {}
for idx, row in regime_df.iterrows():
    d = idx.strftime('%Y%m%d')
    regime_map[d] = {
        'quadrant': row.get('quadrant'),
        'vix_regime': row.get('vix_regime'),
        'vix': row.get('vix'),
        'spread': row.get('spread'),
    }

# KOSPI MA 계산
import krx_auth
krx_auth.login()
from pykrx import stock as pykrx_stock
kospi = pykrx_stock.get_index_ohlcv('20200101', '20260403', '1001')
if not kospi.empty:
    kospi_close = kospi.iloc[:, 3]
    kospi_ma60 = kospi_close.rolling(60).mean()
    kospi_ma120 = kospi_close.rolling(120).mean()
    kospi_ret20 = kospi_close.pct_change(20)
    kospi_vol20 = kospi_close.pct_change().rolling(20).std() * np.sqrt(252)

    for idx in kospi_close.index:
        d = idx.strftime('%Y%m%d')
        if d not in regime_map:
            regime_map[d] = {}
        regime_map[d]['kospi'] = kospi_close.loc[idx]
        regime_map[d]['kospi_ma60'] = kospi_ma60.loc[idx] if idx in kospi_ma60.index else None
        regime_map[d]['kospi_ma120'] = kospi_ma120.loc[idx] if idx in kospi_ma120.index else None
        regime_map[d]['kospi_ret20'] = kospi_ret20.loc[idx] if idx in kospi_ret20.index else None
        regime_map[d]['kospi_vol20'] = kospi_vol20.loc[idx] if idx in kospi_vol20.index else None

t0 = time.time()

# === 전략별 일별 수익률 추출 ===
print('전략별 일별 수익률 계산...')

# CoreV25
tsim_2b = TurboSimulator(bt2b_r, bt2b_d, prices)
tsim_2b._ensure_cache(0.25, 0.20, 0.35, 0.20, 0.2, 20)
runner_core = TurboRunner(tsim_2b)
r_core = runner_core.run(5, 7, 5, corr_threshold=0.5)
core_daily = r_core['_daily_rets']

# Golden1-X5
tsim_2b._ensure_cache(0.20, 0.10, 0.45, 0.25, 0.3, 20)
runner_golden = TurboRunner(tsim_2b)
r_golden = runner_golden.run(5, 5, 5, corr_threshold=None)
golden_daily = r_golden['_daily_rets']

# Boost
tsim_bt = TurboSimulator(bt_r, bt_d, prices)
tsim_bt._ensure_cache(0.15, 0.05, 0.65, 0.15, 1.0, 20)
runner_boost = TurboRunner(tsim_bt)
r_boost = runner_boost.run(3, 4, 3, corr_threshold=None)
boost_daily = r_boost['_daily_rets']

# 날짜 맞추기 (bt_2b 기준, boost는 bt 기준)
n_2b = len(bt2b_d)
n_bt = len(bt_d)
print(f'  Core/Golden: {n_2b}일, Boost: {n_bt}일')

# 공통 날짜 사용 (bt_2b 기준, boost도 같은 범위)
common_dates = sorted(set(bt2b_d) & set(bt_d))
print(f'  공통 날짜: {len(common_dates)}일')

# 인덱스 매핑
core_idx = {d: i for i, d in enumerate(bt2b_d)}
golden_idx = {d: i for i, d in enumerate(bt2b_d)}
boost_idx = {d: i for i, d in enumerate(bt_d)}


def regime_switch(dates, defense_daily, defense_dates, attack_daily, attack_dates,
                   rule_fn, defense_name='Defense', attack_name='Attack'):
    """날짜별로 rule_fn(date) → True면 attack, False면 defense"""
    d_idx = {d: i for i, d in enumerate(defense_dates)}
    a_idx = {d: i for i, d in enumerate(attack_dates)}

    combined_rets = []
    for d in dates:
        if d not in d_idx or d not in a_idx:
            combined_rets.append(0.0)
            continue
        use_attack = rule_fn(d)
        if use_attack:
            combined_rets.append(attack_daily[a_idx[d]])
        else:
            combined_rets.append(defense_daily[d_idx[d]])

    return _calc_metrics(combined_rets, [0.0]*len(combined_rets), [0]*len(combined_rets))


def fmt(r):
    return f"CAGR={r['cagr']:>+6.1f}% MDD={r['mdd']:>5.1f}% Calmar={r['calmar']:>5.2f} Sharpe={r['sharpe']:>5.2f}"


# === 국면 정의 규칙들 ===

# HY 분면 기반
def hy_q1q2_boost(d):
    r = regime_map.get(d, {})
    return r.get('quadrant') in ('Q1', 'Q2')

def hy_q1_boost(d):
    r = regime_map.get(d, {})
    return r.get('quadrant') == 'Q1'

def hy_q1q4_boost(d):
    """Q1(회복) + Q4(침체 후기 = 반등 기회)에서 공격"""
    r = regime_map.get(d, {})
    return r.get('quadrant') in ('Q1', 'Q4')

def hy_not_q4early(d):
    """Q4 초기(20일 이내)만 방어, 나머지 공격"""
    r = regime_map.get(d, {})
    return r.get('quadrant') != 'Q4'

# VIX 기반
def vix_normal_boost(d):
    r = regime_map.get(d, {})
    return r.get('vix_regime') in ('normal',)

def vix_not_crisis(d):
    r = regime_map.get(d, {})
    return r.get('vix_regime') != 'crisis'

# KOSPI MA 기반
def kospi_above_ma60(d):
    r = regime_map.get(d, {})
    k = r.get('kospi')
    ma = r.get('kospi_ma60')
    if k and ma and not pd.isna(k) and not pd.isna(ma):
        return k >= ma
    return False

def kospi_above_ma120(d):
    r = regime_map.get(d, {})
    k = r.get('kospi')
    ma = r.get('kospi_ma120')
    if k and ma and not pd.isna(k) and not pd.isna(ma):
        return k >= ma
    return False

# KOSPI 모멘텀 기반
def kospi_ret20_positive(d):
    r = regime_map.get(d, {})
    ret = r.get('kospi_ret20')
    if ret and not pd.isna(ret):
        return ret > 0
    return False

# 복합: KOSPI MA60 위 + VIX not crisis
def kospi_ma60_vix_ok(d):
    return kospi_above_ma60(d) and vix_not_crisis(d)

# 복합: HY Q1Q2 + KOSPI MA60 위
def hy_q1q2_kospi_ma60(d):
    return hy_q1q2_boost(d) and kospi_above_ma60(d)

# 항상 Core/Boost (기준선)
def always_defense(d):
    return False

def always_attack(d):
    return True


print('\n' + '=' * 60)
print('  국면 전환 v2: CoreV25 ↔ Boost')
print('=' * 60)

rules = [
    ('항상Core',         always_defense),
    ('항상Boost',        always_attack),
    ('HY Q1Q2=B',       hy_q1q2_boost),
    ('HY Q1=B',         hy_q1_boost),
    ('HY Q1Q4=B',       hy_q1q4_boost),
    ('HY notQ4=B',      hy_not_q4early),
    ('VIX normal=B',    vix_normal_boost),
    ('VIX !crisis=B',   vix_not_crisis),
    ('KOSPI>MA60=B',    kospi_above_ma60),
    ('KOSPI>MA120=B',   kospi_above_ma120),
    ('KOSPI ret20>0=B', kospi_ret20_positive),
    ('MA60+VIX=B',      kospi_ma60_vix_ok),
    ('HY12+MA60=B',     hy_q1q2_kospi_ma60),
]

print(f"{'규칙':<18} {'CAGR':>7} {'MDD':>6} {'Calmar':>7} {'Sharpe':>7}")
print('-' * 50)
for name, rule_fn in rules:
    r = regime_switch(common_dates, core_daily, bt2b_d, boost_daily, bt_d, rule_fn)
    print(f"{name:<18} {r['cagr']:>+6.1f}% {r['mdd']:>5.1f}% {r['calmar']:>7.2f} {r['sharpe']:>7.2f}")

print('\n' + '=' * 60)
print('  국면 전환 v2: Golden1-X5 ↔ Boost')
print('=' * 60)

print(f"{'규칙':<18} {'CAGR':>7} {'MDD':>6} {'Calmar':>7} {'Sharpe':>7}")
print('-' * 50)
for name, rule_fn in rules:
    r = regime_switch(common_dates, golden_daily, bt2b_d, boost_daily, bt_d, rule_fn)
    print(f"{name:<18} {r['cagr']:>+6.1f}% {r['mdd']:>5.1f}% {r['calmar']:>7.2f} {r['sharpe']:>7.02f}")

# 기준선
print('\n--- 단독 전략 기준선 ---')
print(f"  CoreV25:     {fmt(r_core)}")
print(f"  Golden1-X5:  {fmt(r_golden)}")
print(f"  Boost:       {fmt(r_boost)}")

print(f'\n소요: {(time.time()-t0)/60:.1f}분')
print('완료!')
