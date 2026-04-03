"""최종 비교: Cal2 vs Cal3 + KK 3일확인"""
import sys, io, json, glob
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

import krx_auth
krx_auth.login()
from pykrx import stock as pykrx_stock
import time as _time

kospi = pykrx_stock.get_index_ohlcv('20200101', '20260404', '1001')
kc = kospi.iloc[:, 3]; kc_ma60 = kc.rolling(60).mean()
_time.sleep(1)
kosdaq = pykrx_stock.get_index_ohlcv('20200101', '20260404', '2001')
kd_v = kosdaq.iloc[:, 3]; kd_ma60 = kd_v.rolling(60).mean()

ind = {}
for idx in kc.index:
    d = idx.strftime('%Y%m%d')
    ind[d] = {'kospi': kc.loc[idx], 'kospi_ma60': kc_ma60.loc[idx]}
for idx in kd_v.index:
    d = idx.strftime('%Y%m%d')
    if d not in ind: ind[d] = {}
    ind[d]['kosdaq'] = kd_v.loc[idx]
    ind[d]['kosdaq_ma60'] = kd_ma60.loc[idx]

kospi_yearly = {}
for yr in ['2021','2022','2023','2024','2025','2026']:
    mask = (kc.index >= pd.Timestamp(yr + '0101')) & (kc.index <= pd.Timestamp(yr + '1231'))
    k = kc[mask]
    if len(k) >= 2:
        kospi_yearly[yr] = (k.iloc[-1] / k.iloc[0] - 1) * 100

tsim_2b = TurboSimulator(bt2b_r, bt2b_d, prices)
tsim_bt = TurboSimulator(bt_r, bt_d, prices)
common = sorted(set(bt2b_d) & set(bt_d))
i2b = {d: i for i, d in enumerate(bt2b_d)}
ibt = {d: i for i, d in enumerate(bt_d)}

def kk(d):
    x = ind.get(d, {})
    k, m = x.get('kospi'), x.get('kospi_ma60')
    k2, m2 = x.get('kosdaq'), x.get('kosdaq_ma60')
    ok1 = k and m and not pd.isna(k) and not pd.isna(m) and k >= m
    ok2 = k2 and m2 and not pd.isna(k2) and not pd.isna(m2) and k2 >= m2
    return ok1 and ok2

cons = {}
prev = None
streak = 0
conf = 'Cal2'
for d in common:
    cur = 'Boost' if kk(d) else 'Cal2'
    if cur == prev:
        streak += 1
    else:
        streak = 1
    prev = cur
    if streak >= 3:
        conf = cur
    cons[d] = conf

# 전체 일별 수익률
tsim_2b._ensure_cache(0.20, 0.25, 0.45, 0.10, 0.15, 20)
cal2_full = TurboRunner(tsim_2b).run(4, 6, 5, corr_threshold=None)
cal2_d = cal2_full['_daily_rets']

tsim_2b._ensure_cache(0.20, 0.20, 0.45, 0.15, 0.10, 20)
cal3_full = TurboRunner(tsim_2b).run(4, 10, 5, corr_threshold=None)
cal3_d = cal3_full['_daily_rets']

tsim_bt._ensure_cache(0.15, 0.05, 0.65, 0.15, 1.0, 20)
bo_full = TurboRunner(tsim_bt).run(3, 4, 3, corr_threshold=None)
bo_d = bo_full['_daily_rets']

years = [
    ('2021', '20210104', '20211230'),
    ('2022', '20220103', '20221229'),
    ('2023', '20230102', '20231228'),
    ('2024', '20240102', '20241230'),
    ('2025', '20250102', '20251230'),
    ('2026', '20260102', '20260320'),
]

print('=== Cal2 vs Cal3 + KK 3일확인 연도별 ===')
print()
hdr = '{:<6} {:>6} {:>4} | {:>9} {:>6} | {:>9} {:>6} | {:>9} | {:>9}'.format(
    '연도', 'KOSPI', '시장', 'Cal2+KK', 'MDD', 'Cal3+KK', 'MDD', 'Cal2solo', 'Cal3solo')
print(hdr)
print('-' * 82)

for yr, start, end in years:
    yr_2b = [d for d in bt2b_d if start <= d <= end]
    yr_bt = [d for d in bt_d if start <= d <= end]
    yr_common = [d for d in common if start <= d <= end]
    if len(yr_2b) < 10:
        continue

    yr_r_2b = {d: bt2b_r[d] for d in yr_2b}
    ts = TurboSimulator(yr_r_2b, yr_2b, prices)

    ts._ensure_cache(0.20, 0.25, 0.45, 0.10, 0.15, 20)
    c2 = TurboRunner(ts).run(4, 6, 5, corr_threshold=None)
    c2_d = c2['_daily_rets']

    ts._ensure_cache(0.20, 0.20, 0.45, 0.15, 0.10, 20)
    c3 = TurboRunner(ts).run(4, 10, 5, corr_threshold=None)
    c3_d = c3['_daily_rets']

    yr_r_bt = {d: bt_r[d] for d in yr_bt if d in bt_r}
    ts2 = TurboSimulator(yr_r_bt, yr_bt, prices)
    ts2._ensure_cache(0.15, 0.05, 0.65, 0.15, 1.0, 20)
    bo = TurboRunner(ts2).run(3, 4, 3, corr_threshold=None)
    bo_yr = bo['_daily_rets']

    yr_i2b = {d: i for i, d in enumerate(yr_2b)}
    yr_ibt = {d: i for i, d in enumerate(yr_bt)}

    def yr_switch(def_d):
        combined = []
        for d in yr_common:
            a = yr_i2b.get(d)
            b = yr_ibt.get(d)
            if a is None or b is None:
                combined.append(0.0)
                continue
            if cons.get(d) == 'Boost':
                combined.append(bo_yr[b])
            else:
                combined.append(def_d[a])
        return _calc_metrics(combined, [0.0]*len(combined), [0]*len(combined))

    r_c2 = yr_switch(c2_d)
    r_c3 = yr_switch(c3_d)

    k_ret = kospi_yearly.get(yr, 0)
    mkt = 'DOWN' if k_ret < -5 else 'FLAT' if k_ret < 10 else 'UP'

    line = '{:<6} {:>+5.0f}% {:>4} | {:>+8.1f}% {:>5.1f}% | {:>+8.1f}% {:>5.1f}% | {:>+8.1f}% | {:>+8.1f}%'.format(
        yr, k_ret, mkt,
        r_c2['cagr'], r_c2['mdd'],
        r_c3['cagr'], r_c3['mdd'],
        c2['cagr'], c3['cagr'])
    print(line)

print('-' * 82)

# 전체
c2_sw = []
c3_sw = []
for d in common:
    a = i2b.get(d)
    b = ibt.get(d)
    if a is None or b is None:
        c2_sw.append(0.0)
        c3_sw.append(0.0)
        continue
    if cons.get(d) == 'Boost':
        c2_sw.append(bo_d[b])
        c3_sw.append(bo_d[b])
    else:
        c2_sw.append(cal2_d[a])
        c3_sw.append(cal3_d[a])

r_c2_f = _calc_metrics(c2_sw, [0.0]*len(c2_sw), [0]*len(c2_sw))
r_c3_f = _calc_metrics(c3_sw, [0.0]*len(c3_sw), [0]*len(c3_sw))

line = '{:<6} {:>6} {:>4} | {:>+8.1f}% {:>5.1f}% | {:>+8.1f}% {:>5.1f}% | {:>+8.1f}% | {:>+8.1f}%'.format(
    'TOTAL', '', '',
    r_c2_f['cagr'], r_c2_f['mdd'],
    r_c3_f['cagr'], r_c3_f['mdd'],
    cal2_full['cagr'], cal3_full['cagr'])
print(line)

print()
print('=== 전체 지표 ===')
fmt = '{:<20} {:>+6.1f}% {:>5.1f}% {:>7.02f} {:>7.02f} {:>7.02f}'
print('{:<20} {:>7} {:>6} {:>7} {:>7} {:>7}'.format('', 'CAGR', 'MDD', 'Calmar', 'Sharpe', 'Sortino'))
print('-' * 55)
print(fmt.format('Cal2+KK 3day', r_c2_f['cagr'], r_c2_f['mdd'], r_c2_f['calmar'], r_c2_f['sharpe'], r_c2_f['sortino']))
print(fmt.format('Cal3+KK 3day', r_c3_f['cagr'], r_c3_f['mdd'], r_c3_f['calmar'], r_c3_f['sharpe'], r_c3_f['sortino']))
print(fmt.format('Cal2 solo', cal2_full['cagr'], cal2_full['mdd'], cal2_full['calmar'], cal2_full['sharpe'], cal2_full['sortino']))
print(fmt.format('Cal3 solo', cal3_full['cagr'], cal3_full['mdd'], cal3_full['calmar'], cal3_full['sharpe'], cal3_full['sortino']))
print(fmt.format('Boost solo', bo_full['cagr'], bo_full['mdd'], bo_full['calmar'], bo_full['sharpe'], bo_full['sortino']))

print()
print('done!')
