# -*- coding: utf-8 -*-
"""명시 페널티 팩터 robustness: WF(3블록) + LOWO(슈퍼위너 제외) + 인접안정.
배포 게이트: 페널티가 모든 regime에서 baseline(V_all) 대비 개선 & 단일종목 착시 아님 확인."""
import sys, io, os, glob, json, bisect
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ, 'data_cache', 'all_ohlcv_adj_*.parquet')))[-1]).replace(0, np.nan)
kc = pd.read_parquet(os.path.join(PROJ, 'data_cache', 'kospi_yf.parquet')).iloc[:, 0]
ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()
def calc_reg(ds):
    reg = {}; md = True; stk = 0; ss = None
    for d in ds:
        ts = pd.Timestamp(d[:4] + '-' + d[4:6] + '-' + d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts, np.nan)): reg[d] = md; continue
        s = bool(ma20[ts] > ma80[ts])
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= 5 and md != s: md = s
        reg[d] = md
    return reg
G3 = ('rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)
def load(folder, drop=None):
    ar, dates = {}, []
    drop = set(drop or [])
    for f in sorted(glob.glob(os.path.join(PROJ, folder, 'ranking_*.json'))):
        dt = os.path.basename(f)[8:16]
        if dt.isdigit() and len(dt) == 8 and dt >= '20190102':
            r = json.load(open(f, encoding='utf-8'))['rankings']
            if drop: r = [x for x in r if x['ticker'] not in drop]
            ar[dt] = r; dates.append(dt)
    return ar, sorted(dates)
ev = json.load(open(os.path.join(PROJ, 'data_cache', 'ca_events.json')))['events']
def runbt_pen(folder, sub, reg, W, K, which='all', drop=None):
    ar, _ = load(folder, drop)
    ca_by_tk = {}
    for tk, d, di in ev:
        if which != 'all' and di != which: continue
        ca_by_tk.setdefault(tk, []).append(d)
    pos_by_tk = {tk: sorted(bisect.bisect_left(sub, d) for d in ds) for tk, ds in ca_by_tk.items()}
    t = TurboSimulator({d: ar[d] for d in sub}, sub, prices, overheat_w=0.2); t._use_overlay = True; t._use_stored_growth = True
    for ii, d in enumerate(sub):
        tks = t._preextracted[d][0]; fd = {x['ticker']: x for x in ar[d]}
        ov = np.empty(len(tks))
        for j, tk in enumerate(tks):
            x = fd[tk]
            base = 0.2 * (x.get('overheat_pen') or 0) + 0.05 * (x.get('mom_10_z') or 0) + 0.06 * (x.get('vol_low_z') or 0)
            pen = 0.0
            ps = pos_by_tk.get(tk)
            if ps and W > 0:
                lo = bisect.bisect_left(ps, ii - K)
                if lo < len(ps) and ps[lo] <= ii: pen = -W
            ov[j] = base + pen
        t._overlay_pre[d] = ov
    t._cached_key = None
    t._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
    flat = list(t._cached_flat)
    r = _run_regime_inner(flat, flat, 0, 6, 3, 3, 6, 3, reg, sub, t._price_arr, t._bench_arr, t._has_bench,
                          t._date_row_indices, len(sub), None, None, None, None,
                          stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None)
    return r.get('calmar', 0)
_, days = load('_var_adj')
# ① WF 3블록
print("① Walk-Forward (V_all baseline vs +페널티 W0.3 K126 dir=all):")
blocks = [('19-21', '20190102', '20211231'), ('22-23약세', '20220101', '20231231'), ('24-26', '20240101', '20261231')]
for nm, lo, hi in blocks:
    sub = [d for d in days if lo <= d <= hi]; rg = calc_reg(sub)
    b = runbt_pen('_var_adj', sub, rg, 0, 126); p = runbt_pen('_var_adj', sub, rg, 0.3, 126, 'all')
    print(f"  {nm:<8} baseline {b:.3f} → +페널티 {p:.3f}  ({p-b:+.3f})")
# ② LOWO
print("\n② Leave-One-Winner-Out (전체기간, +페널티 W0.3 K126 all):")
reg = calc_reg(days)
base_full = runbt_pen('_var_adj', days, reg, 0.3, 126, 'all')
print(f"  전체: {base_full:.3f}")
for w in [['000660'], ['080220'], ['187870'], ['000660', '080220', '187870']]:
    c = runbt_pen('_var_adj', days, reg, 0.3, 126, 'all', drop=w)
    cb = runbt_pen('_var_adj', days, reg, 0, 126, drop=w)
    print(f"  제외 {','.join(w):<22}: +페널티 {c:.3f} vs baseline {cb:.3f} ({c-cb:+.3f})")
# ③ 인접 안정 (W,K plateau CV)
print("\n③ 인접 안정 (dir=all):")
vals = []
for W in [0.2, 0.3, 0.4]:
    for K in [90, 126, 180]:
        c = runbt_pen('_var_adj', days, reg, W, K, 'all'); vals.append(c)
print(f"  W{{0.2,0.3,0.4}}×K{{90,126,180}} 9조합: 평균 {np.mean(vals):.3f}, CV {np.std(vals)/np.mean(vals):.3f}, 최소 {min(vals):.3f}")
