# -*- coding: utf-8 -*-
"""차단3: 3-fold 워크포워드 — "약세장 +0.41 = n=1" 우려 검증.
fold A(19-21, 코로나), B(22-23, 약세스트레스), C(24-26, 강세). fold별 fresh TurboSim.
B(약세)를 OOS로 두고 W를 A 또는 C서 선택 → B 측정. +값 안 나오면 보험서사 못 씀."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backtest'))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ = os.path.dirname(os.path.abspath(__file__)); DC = os.path.join(PROJ, 'data_cache')
prices = pd.read_parquet(sorted(glob.glob(os.path.join(DC, 'all_ohlcv_adj_*.parquet')))[-1]).replace(0, np.nan)
kc = pd.read_parquet(os.path.join(DC, 'kospi_yf.parquet')).iloc[:, 0]
ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()
G3 = ('rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)
def calc_reg(ds):
    reg = {}; md = True; stk = 0; ss = None
    for d in ds:
        ts = pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts, np.nan)): reg[d] = md; continue
        s = bool(ma20[ts] > ma80[ts]); stk = stk+1 if s == ss else 1; ss = s
        if stk >= 5 and md != s: md = s
        reg[d] = md
    return reg
ar_all, days = {}, []
for f in sorted(glob.glob(os.path.join(PROJ, 'state', 'ranking_*.json'))):
    dt = os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt) == 8 and dt >= '20190102':
        ar_all[dt] = json.load(open(f, encoding='utf-8'))['rankings']; days.append(dt)
days = sorted(days)
ca = json.load(open(os.path.join(DC, 'ca_events.json'), encoding='utf-8'))['ca_by_ticker']
def runbt(sub, W, K=126):
    reg = calc_reg(sub)
    t = TurboSimulator({d: ar_all[d] for d in sub}, sub, prices, overheat_w=0.2); t._use_overlay = True; t._use_stored_growth = True
    for ii, d in enumerate(sub):
        tks = t._preextracted[d][0]; fd = {x['ticker']: x for x in ar_all[d]}; cut = sub[max(0, ii-K)]
        ov = np.empty(len(tks))
        for j, tk in enumerate(tks):
            x = fd[tk]; b = 0.2*(x.get('overheat_pen') or 0)+0.05*(x.get('mom_10_z') or 0)+0.06*(x.get('vol_low_z') or 0)
            ds = ca.get(tk); ov[j] = b + (-W if (W > 0 and ds and any(cut < e <= d for e in ds)) else 0.0)
        t._overlay_pre[d] = ov
    t._cached_key = None
    t._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
    flat = list(t._cached_flat)
    r = _run_regime_inner(flat, flat, 0, 6, 3, 3, 6, 3, reg, sub, t._price_arr, t._bench_arr, t._has_bench,
                          t._date_row_indices, len(sub), None, None, None, None, stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None)
    return r.get('calmar', 0)
folds = {'A(19-21코로나)': ('20190102', '20211231'), 'B(22-23약세)': ('20220101', '20231231'), 'C(24-26강세)': ('20240101', '20261231')}
sub = {k: [d for d in days if lo <= d <= hi] for k, (lo, hi) in folds.items()}
for k in folds: print(f"{k}: {sub[k][0]}~{sub[k][-1]} {len(sub[k])}일")
Ws = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]
print("\n=== fold별 W 스윕 (Calmar) ===")
res = {}
for k in folds:
    res[k] = {W: runbt(sub[k], W) for W in Ws}
    best = max(Ws, key=lambda w: res[k][w])
    print(f"  {k}: " + " ".join(f"W{w}={res[k][w]:.2f}" for w in Ws) + f"  | best W={best}")
    sys.stdout.flush()
print("\n=== 약세폴드 B를 OOS로: W를 다른 폴드서 선택 → B 측정 ===")
wA = max(Ws, key=lambda w: res['A(19-21코로나)'][w]); wC = max(Ws, key=lambda w: res['C(24-26강세)'][w])
print(f"  A서 선택 W={wA} → B Calmar {res['B(22-23약세)'][wA]:.3f} (vs W0 {res['B(22-23약세)'][0.0]:.3f}, 효과 {res['B(22-23약세)'][wA]-res['B(22-23약세)'][0.0]:+.3f})")
print(f"  C서 선택 W={wC} → B Calmar {res['B(22-23약세)'][wC]:.3f} (vs W0 {res['B(22-23약세)'][0.0]:.3f}, 효과 {res['B(22-23약세)'][wC]-res['B(22-23약세)'][0.0]:+.3f})")
print(f"  배포 W0.3 → B Calmar {res['B(22-23약세)'][0.3]:.3f} (vs W0 {res['B(22-23약세)'][0.0]:.3f}, 효과 {res['B(22-23약세)'][0.3]-res['B(22-23약세)'][0.0]:+.3f})")
print("\n=== 각 폴드 배포값 W0.3 효과 (vs W0) ===")
for k in folds:
    print(f"  {k}: {res[k][0.3]:.3f} vs {res[k][0.0]:.3f} = {res[k][0.3]-res[k][0.0]:+.3f}")
