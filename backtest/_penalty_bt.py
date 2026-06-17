# -*- coding: utf-8 -*-
"""명시 페널티 팩터 검증: V_all(정직 수정주가) 기반에 '최근 K영업일내 CA 발생→감점' 오버레이.
가격왜곡(V_none/V_down) 없이 'post-CA 부실주 회피' 알파를 깨끗하게 재포착하는가?
W·K 스윕 + 방향별(all/down/up). 목표: V_all(2.76) 대비 상승, 가능하면 V_down(3.30) 도달."""
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
def load(folder):
    ar, dates = {}, []
    for f in sorted(glob.glob(os.path.join(PROJ, folder, 'ranking_*.json'))):
        dt = os.path.basename(f)[8:16]
        if dt.isdigit() and len(dt) == 8 and dt >= '20190102':
            ar[dt] = json.load(open(f, encoding='utf-8'))['rankings']; dates.append(dt)
    return ar, sorted(dates)
ev = json.load(open(os.path.join(PROJ, 'data_cache', 'ca_events.json')))['events']
def runbt_pen(folder, sub, reg, W, K, which='all'):
    ar, _ = load(folder)
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
                lo = bisect.bisect_left(ps, ii - K);
                if lo < len(ps) and ps[lo] <= ii: pen = -W
            ov[j] = base + pen
        t._overlay_pre[d] = ov
    t._cached_key = None
    t._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
    flat = list(t._cached_flat)
    r = _run_regime_inner(flat, flat, 0, 6, 3, 3, 6, 3, reg, sub, t._price_arr, t._bench_arr, t._has_bench,
                          t._date_row_indices, len(sub), None, None, None, None,
                          stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None)
    return r.get('calmar', 0), r.get('cagr', 0), r.get('mdd', 0)
_, days = load('_var_adj'); reg = calc_reg(days)
print(f"V_all 기반 명시페널티 스윕 ({days[0]}~{days[-1]} {len(days)}일)")
print(f"baseline W=0: ", end=''); c = runbt_pen('_var_adj', days, reg, 0, 126); print(f"Calmar {c[0]:.3f} (=V_all 2.76 확인)")
print(f"\n{'W':>5}{'K':>5}{'dir':>6}{'Calmar':>9}{'CAGR':>7}{'MDD':>7}")
best = (0, None)
for which in ['all', 'down', 'up']:
    for K in [60, 126, 252]:
        for W in [0.1, 0.2, 0.3, 0.5]:
            c = runbt_pen('_var_adj', days, reg, W, K, which)
            tag = ' ←best' if c[0] > best[0] else ''
            if c[0] > best[0]: best = (c[0], (W, K, which))
            print(f"{W:>5}{K:>5}{which:>6}{c[0]:>9.3f}{c[1]:>6.0f}%{c[2]:>6.1f}%{tag}")
print(f"\n최고: Calmar {best[0]:.3f} @ W={best[1][0]} K={best[1][1]} dir={best[1][2]}")
print(f"비교: V_none 4.31(착시) / V_down 3.30(병합왜곡) / V_all 2.76(정직) / V_all+페널티 {best[0]:.3f}")
