"""Cal2/Cal3 기준 국면전환 4가지 방법 비교"""
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

regime_df = pd.read_parquet(CACHE_DIR / 'regime_daily.parquet')
import krx_auth
krx_auth.login()
from pykrx import stock as pykrx_stock
kospi = pykrx_stock.get_index_ohlcv('20200101', '20260404', '1001')
kc = kospi.iloc[:, 3]
ma60 = kc.rolling(60).mean()

ind = {}
for idx in kc.index:
    d = idx.strftime('%Y%m%d')
    ind[d] = {'kospi': kc.loc[idx], 'ma60': ma60.loc[idx]}
for idx, row in regime_df.iterrows():
    d = idx.strftime('%Y%m%d')
    if d not in ind:
        ind[d] = {}
    ind[d]['vix_regime'] = row.get('vix_regime')

tsim_2b = TurboSimulator(bt2b_r, bt2b_d, prices)
tsim_bt = TurboSimulator(bt_r, bt_d, prices)

common = sorted(set(bt2b_d) & set(bt_d))
i2b = {d: i for i, d in enumerate(bt2b_d)}
ibt = {d: i for i, d in enumerate(bt_d)}

# === 일별 수익률 ===

# Boost
tsim_bt._ensure_cache(0.15, 0.05, 0.65, 0.15, 1.0, 20)
bo_d = TurboRunner(tsim_bt).run(3, 4, 3, corr_threshold=None)['_daily_rets']

# Cal2 방어 (E4/X6/S5)
tsim_2b._ensure_cache(0.20, 0.25, 0.45, 0.10, 0.15, 20)
cal2_def_d = TurboRunner(tsim_2b).run(4, 6, 5, corr_threshold=None)['_daily_rets']
# Cal2 공격 (E3/X4/S3)
cal2_agg_d = TurboRunner(tsim_2b).run(3, 4, 3, corr_threshold=None)['_daily_rets']
cal2_solo = TurboRunner(tsim_2b).run(4, 6, 5, corr_threshold=None)
cal2_agg_solo = TurboRunner(tsim_2b).run(3, 4, 3, corr_threshold=None)

# Cal3 방어 (E4/X10/S5)
tsim_2b._ensure_cache(0.20, 0.20, 0.45, 0.15, 0.10, 20)
cal3_def_d = TurboRunner(tsim_2b).run(4, 10, 5, corr_threshold=None)['_daily_rets']
# Cal3 공격 (E3/X4/S3)
cal3_agg_d = TurboRunner(tsim_2b).run(3, 4, 3, corr_threshold=None)['_daily_rets']
cal3_solo = TurboRunner(tsim_2b).run(4, 10, 5, corr_threshold=None)
cal3_agg_solo = TurboRunner(tsim_2b).run(3, 4, 3, corr_threshold=None)

# === 국면 규칙 ===

def base_rule(d):
    x = ind.get(d, {})
    k, m = x.get('kospi'), x.get('ma60')
    vr = x.get('vix_regime')
    return k and m and not pd.isna(k) and not pd.isna(m) and k >= m and vr != 'crisis'

# 3일 확인
consecutive = {}
prev_mode = None
streak = 0
confirmed = 'defense'
for d in common:
    cur = 'attack' if base_rule(d) else 'defense'
    if cur == prev_mode:
        streak += 1
    else:
        streak = 1
    prev_mode = cur
    if streak >= 3:
        confirmed = cur
    consecutive[d] = confirmed

def rule_3day(d):
    return consecutive.get(d) == 'attack'

# 2% 히스테리시스
buf_mode = 'defense'
buf_map = {}
for d in common:
    x = ind.get(d, {})
    k, m = x.get('kospi'), x.get('ma60')
    vr = x.get('vix_regime')
    if k and m and not pd.isna(k) and not pd.isna(m) and vr != 'crisis':
        if buf_mode == 'defense' and k >= m * 1.02:
            buf_mode = 'attack'
        elif buf_mode == 'attack' and k < m * 0.98:
            buf_mode = 'defense'
    else:
        buf_mode = 'defense'
    buf_map[d] = buf_mode

def rule_hyst(d):
    return buf_map.get(d) == 'attack'

def count_sw(fn):
    sw = 0
    prev = None
    for d in common:
        cur = fn(d)
        if prev is not None and cur != prev:
            sw += 1
        prev = cur
    return sw

def switch_boost(def_d, rule_fn):
    """방어전략 ↔ Boost"""
    c = []
    for d in common:
        a, b = i2b.get(d), ibt.get(d)
        if a is None or b is None:
            c.append(0.0); continue
        c.append(bo_d[b] if rule_fn(d) else def_d[a])
    return _calc_metrics(c, [0.0]*len(c), [0]*len(c))

def switch_param(def_d, agg_d, rule_fn):
    """같은 가중치, 파라미터만 변경"""
    c = []
    for d in common:
        a = i2b.get(d)
        if a is None:
            c.append(0.0); continue
        c.append(agg_d[a] if rule_fn(d) else def_d[a])
    return _calc_metrics(c, [0.0]*len(c), [0]*len(c))

def fmt(r, sw=''):
    return f"{r['cagr']:>+6.1f}% {r['mdd']:>5.1f}% {r['calmar']:>7.02f} {r['sharpe']:>7.02f} {r['sortino']:>7.02f} {sw:>5}"

hdr = f"{'방법':<32} {'CAGR':>7} {'MDD':>6} {'Calmar':>7} {'Sharpe':>7} {'Sort':>7} {'전환':>5}"
sep = '-' * 75

# === Cal2 ===
print('=' * 75)
print('  Cal2 (V20Q25G45M10 g=0.15)')
print('=' * 75)
print(hdr)
print(sep)
print(f"{'Cal2 단독 (E4/X6/S5)':<32} {fmt(cal2_solo, '0')}")
print(f"{'Cal2 공격단독 (E3/X4/S3)':<32} {fmt(cal2_agg_solo, '0')}")
print(f"{'Cal2↔Boost 기본':<32} {fmt(switch_boost(cal2_def_d, base_rule), str(count_sw(base_rule)))}")
print(f"{'Cal2↔Boost 3일확인':<32} {fmt(switch_boost(cal2_def_d, rule_3day), str(count_sw(rule_3day)))}")
print(f"{'Cal2↔Boost 2%히스테리시스':<32} {fmt(switch_boost(cal2_def_d, rule_hyst), str(count_sw(rule_hyst)))}")
print(f"{'Cal2 E4X6↔E3X4 기본':<32} {fmt(switch_param(cal2_def_d, cal2_agg_d, base_rule), str(count_sw(base_rule)))}")
print(f"{'Cal2 E4X6↔E3X4 3일확인':<32} {fmt(switch_param(cal2_def_d, cal2_agg_d, rule_3day), str(count_sw(rule_3day)))}")
print(f"{'Cal2 E4X6↔E3X4 2%히스테리시스':<32} {fmt(switch_param(cal2_def_d, cal2_agg_d, rule_hyst), str(count_sw(rule_hyst)))}")

# === Cal3 ===
print()
print('=' * 75)
print('  Cal3 (V20Q20G45M15 g=0.10)')
print('=' * 75)
print(hdr)
print(sep)
print(f"{'Cal3 단독 (E4/X10/S5)':<32} {fmt(cal3_solo, '0')}")
print(f"{'Cal3 공격단독 (E3/X4/S3)':<32} {fmt(cal3_agg_solo, '0')}")
print(f"{'Cal3↔Boost 기본':<32} {fmt(switch_boost(cal3_def_d, base_rule), str(count_sw(base_rule)))}")
print(f"{'Cal3↔Boost 3일확인':<32} {fmt(switch_boost(cal3_def_d, rule_3day), str(count_sw(rule_3day)))}")
print(f"{'Cal3↔Boost 2%히스테리시스':<32} {fmt(switch_boost(cal3_def_d, rule_hyst), str(count_sw(rule_hyst)))}")
print(f"{'Cal3 E4X10↔E3X4 기본':<32} {fmt(switch_param(cal3_def_d, cal3_agg_d, base_rule), str(count_sw(base_rule)))}")
print(f"{'Cal3 E4X10↔E3X4 3일확인':<32} {fmt(switch_param(cal3_def_d, cal3_agg_d, rule_3day), str(count_sw(rule_3day)))}")
print(f"{'Cal3 E4X10↔E3X4 2%히스테리시스':<32} {fmt(switch_param(cal3_def_d, cal3_agg_d, rule_hyst), str(count_sw(rule_hyst)))}")

# Boost 기준
print()
print(f"{'Boost 단독':<32} {fmt(TurboRunner(tsim_bt).run(3,4,3,corr_threshold=None), '0')}")

print('\n완료!')
