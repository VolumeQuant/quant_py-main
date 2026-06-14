# -*- coding: utf-8 -*-
"""메타 버퍼 크기 + 비대칭 재진입 BT (2026-06-14).
production boost(V15Q0G55M30 E3X6S3) regime BT 기반.
BT#1: 시스템곡선 + 현금(4%/yr) 블렌드 버퍼 스윕.
BT#2: exit confirm 5일 고정, entry confirm 스윕(빠른 재진입).
"""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 데이터 로드 (2019-01-02~)
files = sorted(glob.glob(os.path.join(PROJ, 'state', 'ranking_2019*.json'))
             + glob.glob(os.path.join(PROJ, 'state', 'ranking_202[0-6]*.json')))
all_rankings, dates = {}, []
for f in files:
    dt = os.path.basename(f).replace('ranking_', '').replace('.json', '')
    if dt < '20190102':
        continue
    try:
        d = json.load(open(f, encoding='utf-8'))
        all_rankings[dt] = d.get('rankings', d)
        dates.append(dt)
    except Exception:
        pass
dates = sorted(dates)
prices = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ, 'data_cache', 'all_ohlcv_*.parquet')),
                                key=lambda f: f.split('_')[-1])[-1]).replace(0, np.nan)
tsim = TurboSimulator(all_rankings, dates, prices)
print(f'[데이터] {dates[0]}~{dates[-1]} {len(dates)}일')

# KOSPI MA20/MA80
kc = pd.read_parquet(os.path.join(PROJ, 'data_cache', 'kospi_yf.parquet')).iloc[:, 0]
ma20, ma80 = kc.rolling(20).mean(), kc.rolling(80).mean()

def calc_reg(exit_confirm=5, entry_confirm=5):
    reg = {}; md = True; stk = 0; ss = None
    for d in dates:
        ts = pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts, np.nan)):
            reg[d] = md; continue
        s = bool(ma20[ts] > ma80[ts])
        if s == ss: stk += 1
        else: stk = 1; ss = s
        need = entry_confirm if s else exit_confirm  # 비대칭
        if stk >= need and md != s:
            md = s
        reg[d] = md
    return reg

G3 = ('rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)
def regime_bt(reg):
    tsim._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
    flat = list(tsim._cached_flat)
    return _run_regime_inner(flat, flat, 0, 6, 3, 3, 6, 3, reg, dates,
        tsim._price_arr, tsim._bench_arr, tsim._has_bench, tsim._date_row_indices, len(dates),
        None, None, None, None, stop_loss_o=None, trailing_stop_o=None,
        stop_loss_d=None, trailing_stop_d=None)

def metrics(rets):
    a = np.asarray(rets, dtype=float); eq = np.cumprod(1+a); n = len(a)
    cagr = (eq[-1]**(252/max(n, 1))-1)*100
    peak = np.maximum.accumulate(np.concatenate([[1.0], eq]))
    mdd = abs(((np.concatenate([[1.0], eq])-peak)/peak).min())*100
    return cagr, mdd, (cagr/mdd if mdd > 0 else 0)

# ===== BT#1: 버퍼 크기 =====
print('\n========== BT#1: 메타 버퍼 크기 (시스템 + 현금4%/yr 블렌드) ==========')
sys_r = np.array(regime_bt(calc_reg(5, 5))['_daily_rets'], dtype=float)
cash_d = 1.03**(1/252) - 1
print(f"{'버퍼(현금%)':>10}{'시스템%':>8}{'Calmar':>8}{'CAGR':>8}{'MDD':>8}")
for b in [0.0, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50]:
    blend = (1-b)*sys_r + b*cash_d
    cg, md, cal = metrics(blend)
    tag = ' ← 현행70/30' if abs(b-0.30) < 0.01 else ''
    print(f"{int(b*100):>9}%{int((1-b)*100):>7}%{cal:>8.2f}{cg:>8.1f}{md:>8.1f}{tag}")

# ===== BT#2: 비대칭 재진입 =====
print('\n========== BT#2: 비대칭 재진입 (exit 5일 고정, entry confirm 스윕) ==========')
print(f"{'재진입confirm':>12}{'Calmar':>8}{'CAGR':>8}{'MDD':>8}{'전환/whipsaw':>12}")
for ec in [1, 2, 3, 5]:
    reg = calc_reg(exit_confirm=5, entry_confirm=ec)
    vals = [reg[d] for d in dates]
    switches = sum(1 for i in range(1, len(vals)) if vals[i] != vals[i-1])
    r = regime_bt(reg)
    tag = ' ← 현행(5/5대칭)' if ec == 5 else ''
    print(f"{ec:>11}일{r['calmar']:>8.3f}{r['cagr']:>8.1f}{r['mdd']:>8.1f}{switches:>10}회{tag}")

# WF 검증: 5일(현행) vs 2일(최적) 기간분할 — 과적합 체크 (M상향처럼 최근구간 깨지나)
print('\n  [WF 검증] 재진입 5일 vs 2일, 기간분할 Calmar (M상향처럼 2024-26 깨지나?)')
splits = [('2019-21', '20190102', '20211231'), ('2022-23', '20220101', '20231231'),
          ('2024-26', '20240101', '20261231')]
for nm, lo, hi in splits:
    dsub = [d for d in dates if lo <= d <= hi]
    if len(dsub) < 30:
        continue
    sub = TurboSimulator({d: all_rankings[d] for d in dsub}, sorted(dsub), prices)
    sub._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
    flat = list(sub._cached_flat)
    def sub_bt(reg_full):
        reg = {d: reg_full[d] for d in dsub}
        return _run_regime_inner(flat, flat, 0, 6, 3, 3, 6, 3, reg, dsub,
            sub._price_arr, sub._bench_arr, sub._has_bench, sub._date_row_indices, len(dsub),
            None, None, None, None, stop_loss_o=None, trailing_stop_o=None,
            stop_loss_d=None, trailing_stop_d=None)
    r5 = sub_bt(calc_reg(5, 5)); r2 = sub_bt(calc_reg(5, 2))
    print(f"   {nm}: 5일 Cal {r5['calmar']:.2f} → 2일 Cal {r2['calmar']:.2f}  (Δ{r2['calmar']-r5['calmar']:+.2f})")

# ===== BT#3: HY스프레드/VIX 국면 추가 =====
print('\n========== BT#3: HY/VIX 국면 추가 (defense if MA-defense OR VIX>th OR HY>th) ==========')
vix = pd.read_parquet(os.path.join(PROJ, 'data_cache', 'vix_yf_full.parquet')).iloc[:, 0]
hy = pd.read_parquet(os.path.join(PROJ, 'data_cache', 'hy_spread.parquet')).iloc[:, 0]
# 일별 ffill (날짜 정렬)
didx = pd.to_datetime([d[:4]+'-'+d[4:6]+'-'+d[6:] for d in dates])
vix_a = vix.reindex(didx, method='ffill'); hy_a = hy.reindex(didx, method='ffill')
vixmap = {d: vix_a.iloc[i] for i, d in enumerate(dates)}
hymap = {d: hy_a.iloc[i] for i, d in enumerate(dates)}

def calc_reg_aug(vix_th=None, hy_th=None):
    base = calc_reg(5, 5)  # 현행 MA cross
    if vix_th is None and hy_th is None:
        return base
    reg = {}
    for d in dates:
        boost = bool(base[d])
        if vix_th and not pd.isna(vixmap[d]) and vixmap[d] > vix_th: boost = False
        if hy_th and not pd.isna(hymap[d]) and hymap[d] > hy_th: boost = False
        reg[d] = boost
    return reg

print(f"{'국면 룰':<28}{'Calmar':>8}{'CAGR':>8}{'MDD':>8}{'전환':>7}")
variants = [('MA만 (현행)', None, None), ('MA + VIX>30', 30, None), ('MA + VIX>36', 36, None),
            ('MA + HY>5', None, 5.0), ('MA + HY>6', None, 6.0),
            ('MA + VIX>36 + HY>6', 36, 6.0), ('MA + VIX>30 + HY>5', 30, 5.0)]
base_cal = None
for nm, vt, ht in variants:
    reg = calc_reg_aug(vt, ht)
    sw = sum(1 for i in range(1, len(dates)) if reg[dates[i]] != reg[dates[i-1]])
    r = regime_bt(reg)
    if base_cal is None: base_cal = r['calmar']
    d = '' if nm.startswith('MA만') else f"  Δ{r['calmar']-base_cal:+.2f}"
    print(f"{nm:<28}{r['calmar']:>8.3f}{r['cagr']:>8.1f}{r['mdd']:>8.1f}{sw:>6}회{d}")
