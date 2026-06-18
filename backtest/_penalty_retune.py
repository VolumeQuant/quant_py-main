# -*- coding: utf-8 -*-
"""페널티 W/K 재튜닝 robustness: down-only state로 0.3/126(현행) vs 0.4/252(그리드최대) 등
후보를 WF(3블록)+LOWO 검증. 그리드 최대가 과적합인지, robust 개선인지 판정."""
import sys, io, os, glob, json, bisect
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices = pd.read_parquet(sorted(glob.glob(P + '/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
kc = pd.read_parquet(P + '/data_cache/kospi_yf.parquet').iloc[:, 0]; ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()
def reg(ds):
    r = {}; md = True; stk = 0; ss = None
    for d in ds:
        ts = pd.Timestamp(d[:4] + '-' + d[4:6] + '-' + d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts, np.nan)): r[d] = md; continue
        s = bool(ma20[ts] > ma80[ts]); stk = stk + 1 if s == ss else 1; ss = s
        if stk >= 5 and md != s: md = s
        r[d] = md
    return r
G3 = ('rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)
ALL = {}
alldays = []
for f in sorted(glob.glob(P + '/state/ranking_*.json')):
    d = os.path.basename(f)[8:16]
    if d.isdigit() and len(d) == 8 and d >= '20190102': ALL[d] = json.load(open(f, encoding='utf-8'))['rankings']; alldays.append(d)
alldays = sorted(alldays)
ca = json.load(open(P + '/data_cache/ca_events.json', encoding='utf-8'))['ca_by_ticker']
def run(W, K, sub, drop=None):
    drop = set(drop or [])
    ar = {d: ([x for x in ALL[d] if x['ticker'] not in drop] if drop else ALL[d]) for d in sub}
    R = reg(sub)
    pos = {tk: sorted(bisect.bisect_left(sub, d) for d in ds) for tk, ds in ca.items()}
    t = TurboSimulator(ar, sub, prices, overheat_w=0.2); t._use_overlay = True; t._use_stored_growth = True
    for ii, d in enumerate(sub):
        tks = t._preextracted[d][0]; fd = {x['ticker']: x for x in ar[d]}
        ov = np.empty(len(tks))
        for j, tk in enumerate(tks):
            x = fd[tk]; base = 0.2 * (x.get('overheat_pen') or 0) + 0.05 * (x.get('mom_10_z') or 0) + 0.06 * (x.get('vol_low_z') or 0)
            pen = 0.0; ps = pos.get(tk)
            if ps and W > 0:
                lo = bisect.bisect_left(ps, ii - K)
                if lo < len(ps) and ps[lo] <= ii: pen = -W
            ov[j] = base + pen
        t._overlay_pre[d] = ov
    t._cached_key = None; t._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
    flat = list(t._cached_flat)
    r = _run_regime_inner(flat, flat, 0, 6, 3, 3, 6, 3, R, sub, t._price_arr, t._bench_arr, t._has_bench,
                          t._date_row_indices, len(sub), None, None, None, None,
                          stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None)
    return r.get('calmar', 0)
cfgs = [('0.3/126 현행', 0.3, 126), ('0.3/252', 0.3, 252), ('0.4/180', 0.4, 180), ('0.4/252 최대', 0.4, 252)]
print("① Walk-Forward (블록별 Calmar):")
blocks = [('전체', '20190102', '20261231'), ('19-21', '20190102', '20211231'), ('22-23약세', '20220101', '20231231'), ('24-26', '20240101', '20261231')]
print(f"  {'config':<14}" + "".join(f"{b[0]:>11}" for b in blocks))
for nm, W, K in cfgs:
    vals = [run(W, K, [d for d in alldays if lo <= d <= hi]) for _, lo, hi in blocks]
    print(f"  {nm:<14}" + "".join(f"{v:>11.3f}" for v in vals))
print("\n② LOWO (전체기간, 슈퍼위너 제외):")
full = alldays
print(f"  {'제외':<22}{'0.3/126':>10}{'0.4/252':>10}")
for nm, dr in [('없음', []), ('-SK하이닉스', ['000660']), ('-제주반도체', ['080220']), ('-디바이스', ['187870']), ('-3대장', ['000660', '080220', '187870'])]:
    a = run(0.3, 126, full, dr); b = run(0.4, 252, full, dr)
    print(f"  {nm:<22}{a:>10.3f}{b:>10.3f}{'  ('+f'{b-a:+.2f}'+')':>10}")
print("\n→ 0.4/252가 약세장+LOWO 전부 0.3/126 이상이면 robust 개선 → 재배포. 약세장/LOWO서 깨지면 현행 유지.")
