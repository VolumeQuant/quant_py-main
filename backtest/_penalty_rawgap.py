# -*- coding: utf-8 -*-
"""production 일관성 검증: 페널티 CA감지를 raw 갭(>33%/+45%, 당일 관측가능=PIT)으로 했을 때
ca_events(genuine 수정주가기반)와 동일 Calmar인가? 같으면 production은 raw-갭 자체완결 감지 사용."""
import sys, io, os, glob, json, bisect
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ, 'data_cache', 'all_ohlcv_adj_*.parquet')))[-1]).replace(0, np.nan)
raw = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ, 'data_cache', 'all_ohlcv_2017*_2026061*.parquet')))[-1]).replace(0, np.nan)
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
# raw-갭 이벤트 (모든 종목, >33%/+45% 하루 변동 = 당일 관측가능)
rawgap = {}
for tk in raw.columns:
    r = raw[tk].pct_change(fill_method=None)
    for d in r.index[(r < -0.33) | (r > 0.45)]:
        rawgap.setdefault(tk, []).append(d.strftime('%Y%m%d'))
ng = sum(len(v) for v in rawgap.values())
print(f"raw-갭 이벤트: {ng}건 {len(rawgap)}종목 (vs ca_events genuine 1969건 839종목)")
ca_ev = json.load(open(os.path.join(PROJ, 'data_cache', 'ca_events.json')))['events']
ca_by_tk_gen = {}
for tk, d, di in ca_ev: ca_by_tk_gen.setdefault(tk, []).append(d)
def runbt_pen(sub, reg, W, K, src):
    ar, _ = load('_var_adj')
    cb = src
    pos_by_tk = {tk: sorted(bisect.bisect_left(sub, d) for d in ds) for tk, ds in cb.items()}
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
_, days = load('_var_adj'); reg = calc_reg(days)
print(f"\n{'config':<24}{'genuine(ca_ev)':>16}{'raw-gap':>10}")
for W, K in [(0.3, 126), (0.5, 126), (0.3, 252)]:
    cg = runbt_pen(days, reg, W, K, ca_by_tk_gen)
    cr = runbt_pen(days, reg, W, K, rawgap)
    print(f"W{W} K{K} all{'':<11}{cg:>16.3f}{cr:>10.3f}")
print("\n→ 둘이 비슷하면 production은 raw-갭 자체완결 감지(파일의존 X, 신규CA 당일 감지 일관)")
