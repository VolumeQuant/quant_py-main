# -*- coding: utf-8 -*-
"""자작corpaction ON(현재 production state/) vs OFF(_corpoff_boost/) Calmar 결판 (2026-06-24).
같은 가격(raw=수정주가)·같은 페널티/lumpiness 오버레이, 자작보정만 차이. 둘 다 7.4년."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices = pd.read_parquet(sorted(glob.glob(P + '/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
kc = pd.read_parquet(P + '/data_cache/kospi_yf.parquet').iloc[:, 0]
ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()
G3 = ('rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)

def calc_reg(ds):
    reg = {}; md = True; stk = 0; ss = None
    for d in ds:
        ts = pd.Timestamp(d[:4] + '-' + d[4:6] + '-' + d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts, np.nan)): reg[d] = md; continue
        s = bool(ma20[ts] > ma80[ts]); stk = stk + 1 if s == ss else 1; ss = s
        if stk >= 5 and md != s: md = s
        reg[d] = md
    return reg

def load(folder):
    ar, dates = {}, []
    for f in sorted(glob.glob(os.path.join(P, folder, 'ranking_*.json'))):
        dt = os.path.basename(f)[8:16]
        if dt.isdigit() and len(dt) == 8 and dt >= '20190102':
            ar[dt] = json.load(open(f, encoding='utf-8'))['rankings']; dates.append(dt)
    return ar, sorted(dates)

def runbt(folder, sub=None):
    ar, days = load(folder)
    if sub: days = [d for d in days if d in sub]
    reg = calc_reg(days)
    t = TurboSimulator({d: ar[d] for d in days}, days, prices, overheat_w=0.2)
    t._use_overlay = True; t._use_stored_growth = True
    for d in days:
        tks = t._preextracted[d][0]; fd = {x['ticker']: x for x in ar[d]}
        t._overlay_pre[d] = np.array([0.2*(fd[tk].get('overheat_pen') or 0)+0.05*(fd[tk].get('mom_10_z') or 0)
                                      +0.06*(fd[tk].get('vol_low_z') or 0)-0.3*(fd[tk].get('recent_ca') or 0) for tk in tks])
    t._cached_key = None; t._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
    flat = list(t._cached_flat)
    r = _run_regime_inner(flat, flat, 0, 6, 3, 3, 6, 3, reg, days, t._price_arr, t._bench_arr, t._has_bench,
                          t._date_row_indices, len(days), None, None, None, None,
                          stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None)
    return r.get('calmar', 0), r.get('cagr', 0), r.get('mdd', 0), len(days)

# 공통 날짜만 (정합)
_, days_on = load('state'); _, days_off = load('_corpoff_boost')
common = sorted(set(days_on) & set(days_off))
print(f"공통 {len(common)}일 ({common[0]}~{common[-1]})")
print(f"  state(ON) {len(days_on)}일 / _corpoff(OFF) {len(days_off)}일\n")
on = runbt('state', common); off = runbt('_corpoff_boost', common)
print(f"{'설정':<28}{'Calmar':>8}{'CAGR':>8}{'MDD':>7}")
print("-"*52)
print(f"{'자작보정 ON (현재 production)':<28}{on[0]:>8.3f}{on[1]*100:>7.0f}%{on[2]*100:>6.1f}%")
print(f"{'자작보정 OFF (의도)':<28}{off[0]:>8.3f}{off[1]*100:>7.0f}%{off[2]*100:>6.1f}%")
print(f"\n차이(ON-OFF): Calmar {on[0]-off[0]:+.3f}")
nd = abs(on[0]-off[0])
print(f"→ {'동일(노이즈 ±0.10 내) = 자작보정 무해, 불일치 문제없음' if nd<=0.10 else ('ON 우위' if on[0]>off[0] else 'OFF(의도) 우위 — 자작보정 끄는 게 나음')}")
# 매수종목 차이 (top6 wr) 몇 일
ar_on, _ = load('state'); ar_off, _ = load('_corpoff_boost')
def top6(ar, d):
    s = sorted(ar[d], key=lambda x: (x.get('weighted_rank', x['rank']), x.get('composite_rank', x['rank'])))[:6]
    return tuple(x['ticker'] for x in s)
diff_days = sum(1 for d in common if top6(ar_on, d) != top6(ar_off, d))
print(f"\n매수권(top6) 다른 날: {diff_days}/{len(common)}일 ({diff_days/len(common)*100:.1f}%)")
print("→ 0%면 자작보정이 매수결정 전혀 안 바꿈 = 완전 무해 확정")
