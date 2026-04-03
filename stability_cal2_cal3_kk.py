"""Cal2 vs Cal3 + KK 3일확인 인접 안정성"""
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

# 3일 확인
cons = {}
prev = None
streak = 0
conf = 'defense'
for d in common:
    cur = 'attack' if kk(d) else 'defense'
    if cur == prev:
        streak += 1
    else:
        streak = 1
    prev = cur
    if streak >= 3:
        conf = cur
    cons[d] = conf

# Boost 일별 (고정)
tsim_bt._ensure_cache(0.15, 0.05, 0.65, 0.15, 1.0, 20)
bo_d = TurboRunner(tsim_bt).run(3, 4, 3, corr_threshold=None)['_daily_rets']

def test_kk_switch(v, q, g, m, g_rev, entry, exit_, slots, corr):
    tsim_2b._ensure_cache(v, q, g, m, g_rev, 20)
    defense = TurboRunner(tsim_2b).run(entry, exit_, slots, corr_threshold=corr)
    def_d = defense['_daily_rets']
    combined = []
    for d in common:
        a = i2b.get(d)
        b = ibt.get(d)
        if a is None or b is None:
            combined.append(0.0)
            continue
        if cons.get(d) == 'attack':
            combined.append(bo_d[b])
        else:
            combined.append(def_d[a])
    return _calc_metrics(combined, [0.0]*len(combined), [0]*len(combined))

# Cal2 base: V20Q25G45M10 g=0.15 E4/X6/S5
# Cal3 base: V20Q20G45M15 g=0.10 E4/X10/S5

print('=== Cal2 + KK 3일 인접 안정성 ===')
print('V20Q25G45M10 g=0.15 E4/X6/S5')
print()

cal2_neighbors = []
for dv in [-5, 0, 5]:
    for dq in [-5, 0, 5]:
        for dg in [-5, 0, 5]:
            v2 = 20 + dv; q2 = 25 + dq; g2 = 45 + dg; m2 = 100 - v2 - q2 - g2
            if m2 < 5 or m2 > 30 or v2 < 10 or q2 < 10 or g2 < 30:
                continue
            for dgr in [-0.05, 0, 0.05]:
                gr2 = 0.15 + dgr
                if gr2 < 0 or gr2 > 0.5:
                    continue
                r = test_kk_switch(v2/100, q2/100, g2/100, m2/100, gr2, 4, 6, 5, None)
                cal2_neighbors.append({'v': v2, 'q': q2, 'g': g2, 'm': m2, 'g_rev': gr2, **r})

cal2_neighbors.sort(key=lambda x: -x['calmar'])
avg = sum(n['calmar'] for n in cal2_neighbors) / len(cal2_neighbors)
a5 = sum(1 for n in cal2_neighbors if n['calmar'] >= 5.0) / len(cal2_neighbors) * 100
a4 = sum(1 for n in cal2_neighbors if n['calmar'] >= 4.0) / len(cal2_neighbors) * 100
a3 = sum(1 for n in cal2_neighbors if n['calmar'] >= 3.0) / len(cal2_neighbors) * 100
print(f'  인접 {len(cal2_neighbors)}개')
print(f'  평균 Calmar: {avg:.2f}')
print(f'  >=5.0: {a5:.0f}%, >=4.0: {a4:.0f}%, >=3.0: {a3:.0f}%')
print(f'  최고: V{cal2_neighbors[0]["v"]}Q{cal2_neighbors[0]["q"]}G{cal2_neighbors[0]["g"]}M{cal2_neighbors[0]["m"]} g={cal2_neighbors[0]["g_rev"]:.2f} Calmar={cal2_neighbors[0]["calmar"]:.2f}')
print(f'  최저: V{cal2_neighbors[-1]["v"]}Q{cal2_neighbors[-1]["q"]}G{cal2_neighbors[-1]["g"]}M{cal2_neighbors[-1]["m"]} g={cal2_neighbors[-1]["g_rev"]:.2f} Calmar={cal2_neighbors[-1]["calmar"]:.2f}')

# 진입/퇴출 인접
print()
print('  진입/퇴출 인접:')
for entry in [3, 4, 5]:
    for exit_ in [5, 6, 7, 8]:
        if exit_ <= entry:
            continue
        for slots in [4, 5]:
            if entry > slots:
                continue
            r = test_kk_switch(0.20, 0.25, 0.45, 0.10, 0.15, entry, exit_, slots, None)
            print(f'    E{entry}/X{exit_}/S{slots}: Calmar={r["calmar"]:.2f} CAGR={r["cagr"]:+.1f}% MDD={r["mdd"]:.1f}%')

print()
print('=== Cal3 + KK 3일 인접 안정성 ===')
print('V20Q20G45M15 g=0.10 E4/X10/S5')
print()

cal3_neighbors = []
for dv in [-5, 0, 5]:
    for dq in [-5, 0, 5]:
        for dg in [-5, 0, 5]:
            v2 = 20 + dv; q2 = 20 + dq; g2 = 45 + dg; m2 = 100 - v2 - q2 - g2
            if m2 < 5 or m2 > 30 or v2 < 10 or q2 < 10 or g2 < 30:
                continue
            for dgr in [-0.05, 0, 0.05]:
                gr2 = 0.10 + dgr
                if gr2 < 0 or gr2 > 0.5:
                    continue
                r = test_kk_switch(v2/100, q2/100, g2/100, m2/100, gr2, 4, 10, 5, None)
                cal3_neighbors.append({'v': v2, 'q': q2, 'g': g2, 'm': m2, 'g_rev': gr2, **r})

cal3_neighbors.sort(key=lambda x: -x['calmar'])
avg3 = sum(n['calmar'] for n in cal3_neighbors) / len(cal3_neighbors)
a5_3 = sum(1 for n in cal3_neighbors if n['calmar'] >= 5.0) / len(cal3_neighbors) * 100
a4_3 = sum(1 for n in cal3_neighbors if n['calmar'] >= 4.0) / len(cal3_neighbors) * 100
a3_3 = sum(1 for n in cal3_neighbors if n['calmar'] >= 3.0) / len(cal3_neighbors) * 100
print(f'  인접 {len(cal3_neighbors)}개')
print(f'  평균 Calmar: {avg3:.2f}')
print(f'  >=5.0: {a5_3:.0f}%, >=4.0: {a4_3:.0f}%, >=3.0: {a3_3:.0f}%')
print(f'  최고: V{cal3_neighbors[0]["v"]}Q{cal3_neighbors[0]["q"]}G{cal3_neighbors[0]["g"]}M{cal3_neighbors[0]["m"]} g={cal3_neighbors[0]["g_rev"]:.2f} Calmar={cal3_neighbors[0]["calmar"]:.2f}')
print(f'  최저: V{cal3_neighbors[-1]["v"]}Q{cal3_neighbors[-1]["q"]}G{cal3_neighbors[-1]["g"]}M{cal3_neighbors[-1]["m"]} g={cal3_neighbors[-1]["g_rev"]:.2f} Calmar={cal3_neighbors[-1]["calmar"]:.2f}')

# 진입/퇴출 인접
print()
print('  진입/퇴출 인접:')
for entry in [3, 4, 5]:
    for exit_ in [7, 8, 10, 12]:
        if exit_ <= entry:
            continue
        for slots in [4, 5]:
            if entry > slots:
                continue
            r = test_kk_switch(0.20, 0.20, 0.45, 0.15, 0.10, entry, exit_, slots, None)
            print(f'    E{entry}/X{exit_}/S{slots}: Calmar={r["calmar"]:.2f} CAGR={r["cagr"]:+.1f}% MDD={r["mdd"]:.1f}%')

print()
print('=== 최종 비교 ===')
print(f'  Cal2+KK: 본인 Calmar=5.41, 인접 평균={avg:.2f}, >=4.0={a4:.0f}%, >=3.0={a3:.0f}%')
print(f'  Cal3+KK: 본인 Calmar=5.37, 인접 평균={avg3:.2f}, >=4.0={a4_3:.0f}%, >=3.0={a3_3:.0f}%')
print()
print('done!')
