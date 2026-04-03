"""확장 국면 테스트: Cal2 기반 + Breadth/Vol/KOSDAQ/VKOSPI"""
import sys, io, json, glob, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, 'C:/dev/claude-code/quant_py-main')
sys.path.insert(0, 'C:/dev/claude-code/quant_py-main/backtest')

import pandas as pd, numpy as np
from pathlib import Path
from turbo_simulator import TurboSimulator, TurboRunner, _calc_metrics

PROJECT = Path('C:/dev/claude-code/quant_py-main')
CACHE_DIR = PROJECT / 'data_cache'

prices = pd.read_parquet(
    sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'), key=lambda f: f.stem.split('_')[2])[0]
).replace(0, np.nan)

bt2b_r = {}
for fp in sorted((PROJECT / 'state' / 'bt_2b').glob('ranking_*.json')):
    d = fp.stem.replace('ranking_', '')
    with open(fp, 'r', encoding='utf-8') as fh:
        data = json.load(fh)
    bt2b_r[d] = data.get('rankings', data) if isinstance(data, dict) else data
bt2b_d = sorted(bt2b_r.keys())

bt_r = {}
for y in range(2021, 2026):
    for fp in sorted((PROJECT / 'state' / f'bt_{y}').glob('ranking_*.json')):
        d = fp.stem.replace('ranking_', '')
        with open(fp, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        bt_r[d] = data.get('rankings', data) if isinstance(data, dict) else data
bt_d = sorted(bt_r.keys())

# Regime
regime_df = pd.read_parquet(CACHE_DIR / 'regime_daily.parquet')

import krx_auth
krx_auth.login()
from pykrx import stock as pykrx_stock
import yfinance as yf

# KOSPI
print('데이터 수집...')
kospi = pykrx_stock.get_index_ohlcv('20200101', '20260404', '1001')
kc = kospi.iloc[:, 3]
kc_ma60 = kc.rolling(60).mean()
kc_ret = kc.pct_change()
kc_vol20 = kc_ret.rolling(20).std() * np.sqrt(252)
kc_vol_med = kc_vol20.rolling(252).median()

# KOSDAQ
import time as _time
_time.sleep(1)
kosdaq = pykrx_stock.get_index_ohlcv('20200101', '20260404', '2001')
kd = kosdaq.iloc[:, 3]
kd_ma60 = kd.rolling(60).mean()

# VKOSPI
_time.sleep(1)
try:
    vkospi = pykrx_stock.get_index_ohlcv('20200101', '20260404', '1004')
    vk = vkospi.iloc[:, 3]
    vk_pct = vk.rolling(504, min_periods=100).rank(pct=True) * 100
    print(f'  VKOSPI: {len(vk)}일')
except:
    vk = pd.Series(dtype=float)
    vk_pct = pd.Series(dtype=float)
    print('  VKOSPI 수집 실패')

# Breadth
ma120_stocks = prices.rolling(120).mean()
above_ma120 = (prices > ma120_stocks).sum(axis=1)
total_valid = prices.notna().sum(axis=1)
breadth = above_ma120 / total_valid * 100

print(f'  KOSPI: {len(kc)}일, KOSDAQ: {len(kd)}일')

# 지표 매핑
ind = {}
for idx in kc.index:
    d = idx.strftime('%Y%m%d')
    ind[d] = {
        'kospi': kc.loc[idx], 'kospi_ma60': kc_ma60.loc[idx],
        'kospi_vol20': kc_vol20.loc[idx] if idx in kc_vol20.index else None,
        'kospi_vol_med': kc_vol_med.loc[idx] if idx in kc_vol_med.index else None,
    }

for idx in kd.index:
    d = idx.strftime('%Y%m%d')
    if d not in ind: ind[d] = {}
    ind[d]['kosdaq'] = kd.loc[idx]
    ind[d]['kosdaq_ma60'] = kd_ma60.loc[idx]

for idx in breadth.index:
    d = idx.strftime('%Y%m%d')
    if d not in ind: ind[d] = {}
    ind[d]['breadth'] = breadth.loc[idx]

if not vk.empty:
    for idx in vk.index:
        d = idx.strftime('%Y%m%d')
        if d not in ind: ind[d] = {}
        ind[d]['vkospi'] = vk.loc[idx]
        ind[d]['vkospi_pct'] = vk_pct.loc[idx] if idx in vk_pct.index else None

for idx, row in regime_df.iterrows():
    d = idx.strftime('%Y%m%d')
    if d not in ind: ind[d] = {}
    ind[d]['vix_regime'] = row.get('vix_regime')

# 시뮬레이터
tsim_2b = TurboSimulator(bt2b_r, bt2b_d, prices)
tsim_bt = TurboSimulator(bt_r, bt_d, prices)

# Cal2 일별
tsim_2b._ensure_cache(0.20, 0.25, 0.45, 0.10, 0.15, 20)
cal2_d = TurboRunner(tsim_2b).run(4, 6, 5, corr_threshold=None)['_daily_rets']

# Boost 일별
tsim_bt._ensure_cache(0.15, 0.05, 0.65, 0.15, 1.0, 20)
bo_d = TurboRunner(tsim_bt).run(3, 4, 3, corr_threshold=None)['_daily_rets']

common = sorted(set(bt2b_d) & set(bt_d))
i2b = {d: i for i, d in enumerate(bt2b_d)}
ibt = {d: i for i, d in enumerate(bt_d)}

# === 국면 규칙들 ===

def _kospi_ma60(d):
    x = ind.get(d, {})
    k, m = x.get('kospi'), x.get('kospi_ma60')
    return k and m and not pd.isna(k) and not pd.isna(m) and k >= m

def _vix_ok(d):
    return ind.get(d, {}).get('vix_regime') != 'crisis'

def _kosdaq_ma60(d):
    x = ind.get(d, {})
    k, m = x.get('kosdaq'), x.get('kosdaq_ma60')
    return k and m and not pd.isna(k) and not pd.isna(m) and k >= m

def _breadth50(d):
    x = ind.get(d, {})
    b = x.get('breadth')
    return b and not pd.isna(b) and b > 50

def _vol_low(d):
    x = ind.get(d, {})
    v, vm = x.get('kospi_vol20'), x.get('kospi_vol_med')
    return v and vm and not pd.isna(v) and not pd.isna(vm) and v <= vm

def _vkospi_ok(d):
    x = ind.get(d, {})
    vp = x.get('vkospi_pct')
    if vp and not pd.isna(vp):
        return vp < 90  # crisis가 아닌 경우
    return True  # 데이터 없으면 공격

def _vkospi_normal(d):
    x = ind.get(d, {})
    vp = x.get('vkospi_pct')
    if vp and not pd.isna(vp):
        return vp < 67
    return True

rules = [
    # 기존 top 3
    ('MA60+VIX',            lambda d: _kospi_ma60(d) and _vix_ok(d)),
    ('Breadth>50%+MA60',    lambda d: _breadth50(d) and _kospi_ma60(d)),
    ('MA60+Vol<med',        lambda d: _kospi_ma60(d) and _vol_low(d)),
    # Breadth 단독
    ('Breadth>50%',         _breadth50),
    # 코스닥 조합
    ('KOSPI+KOSDAQ MA60',   lambda d: _kospi_ma60(d) and _kosdaq_ma60(d)),
    ('KOSPI+KOSDAQ+VIX',    lambda d: _kospi_ma60(d) and _kosdaq_ma60(d) and _vix_ok(d)),
    ('KOSDAQ MA60',         _kosdaq_ma60),
    # VKOSPI 조합
    ('MA60+VKOSPI(!crisis)',lambda d: _kospi_ma60(d) and _vkospi_ok(d)),
    ('MA60+VKOSPI(normal)', lambda d: _kospi_ma60(d) and _vkospi_normal(d)),
    ('VKOSPI(!crisis)',     _vkospi_ok),
    # 복합
    ('KOSPI+KOSDAQ+VKOSPI', lambda d: _kospi_ma60(d) and _kosdaq_ma60(d) and _vkospi_ok(d)),
    ('Breadth+VKOSPI',      lambda d: _breadth50(d) and _vkospi_ok(d)),
    ('Breadth+Vol',          lambda d: _breadth50(d) and _vol_low(d)),
    # 기준선
    ('항상Cal2',            lambda d: False),
    ('항상Boost',           lambda d: True),
]

# 3일 확인 적용
def make_3day(base_fn):
    consecutive = {}
    prev = None
    streak = 0
    confirmed = 'defense'
    for d in common:
        cur = 'attack' if base_fn(d) else 'defense'
        if cur == prev: streak += 1
        else: streak = 1
        prev = cur
        if streak >= 3: confirmed = cur
        consecutive[d] = confirmed
    return lambda d: consecutive.get(d) == 'attack'

def switch(rule_fn):
    c = []
    for d in common:
        a, b = i2b.get(d), ibt.get(d)
        if a is None or b is None: c.append(0.0); continue
        c.append(bo_d[b] if rule_fn(d) else cal2_d[a])
    return _calc_metrics(c, [0.0]*len(c), [0]*len(c))

def count_sw(fn):
    sw = 0
    prev = None
    for d in common:
        cur = fn(d)
        if prev is not None and cur != prev: sw += 1
        prev = cur
    return sw

print()
print('=== Cal2 ↔ Boost: 확장 국면 테스트 (3일확인) ===')
print()
print(f"{'규칙':<26} {'CAGR':>7} {'MDD':>6} {'Calmar':>7} {'Sharpe':>7} {'Sort':>7} {'전환':>5}")
print('-' * 70)

results = []
for name, fn in rules:
    fn_3d = make_3day(fn)
    r = switch(fn_3d)
    sw = count_sw(fn_3d)
    results.append((name, r, sw))
    print(f"{name:<26} {r['cagr']:>+6.1f}% {r['mdd']:>5.1f}% {r['calmar']:>7.02f} {r['sharpe']:>7.02f} {r['sortino']:>7.02f} {sw:>5}")

# Calmar 기준 정렬
print()
print('=== Calmar 기준 순위 ===')
results.sort(key=lambda x: -x[1]['calmar'])
for i, (name, r, sw) in enumerate(results):
    if name in ('항상Cal2', '항상Boost'): continue
    print(f"  {i+1}. {name:<24} Calmar={r['calmar']:.02f} CAGR={r['cagr']:+.1f}% MDD={r['mdd']:.1f}% 전환={sw}")

print('\n완료!')
