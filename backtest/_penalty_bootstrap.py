# -*- coding: utf-8 -*-
"""블록 부트스트랩: 0.4/180 vs 0.3/126 Calmar 차이가 노이즈(0)를 넘는지 정량 판정.
페어드(같은 재표본 경로) → 경로 노이즈 제거하고 전략차만 격리. 전문가 1순위 검증."""
import sys, io, os, glob, json, bisect
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
np.random.seed(42)
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
ar, days = {}, []
for f in sorted(glob.glob(P + '/state/ranking_*.json')):
    d = os.path.basename(f)[8:16]
    if d.isdigit() and len(d) == 8 and d >= '20190102': ar[d] = json.load(open(f, encoding='utf-8'))['rankings']; days.append(d)
days = sorted(days); R = reg(days)
ca = json.load(open(P + '/data_cache/ca_events.json', encoding='utf-8'))['ca_by_ticker']
def daily_rets(W, K):
    pos = {tk: sorted(bisect.bisect_left(days, d) for d in ds) for tk, ds in ca.items()}
    t = TurboSimulator(ar, days, prices, overheat_w=0.2); t._use_overlay = True; t._use_stored_growth = True
    for ii, d in enumerate(days):
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
    r = _run_regime_inner(flat, flat, 0, 6, 3, 3, 6, 3, R, days, t._price_arr, t._bench_arr, t._has_bench,
                          t._date_row_indices, len(days), None, None, None, None,
                          stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None)
    return np.asarray(r['_daily_rets'], dtype=float), r['calmar']
rB, cB = daily_rets(0.3, 126)   # 현행
rA, cA = daily_rets(0.4, 180)   # 후보
print(f"점추정 Calmar: 0.3/126={cB:.3f}  0.4/180={cA:.3f}  차이={cA-cB:+.3f}")
def calmar(r):
    eq = np.cumprod(1 + r); n = len(r)
    cagr = eq[-1] ** (252 / n) - 1
    peak = np.maximum.accumulate(eq); mdd = -((eq - peak) / peak).min()
    return cagr / mdd if mdd > 1e-9 else 0
n = len(rA)
for L in [40, 60, 120]:
    nb = int(np.ceil(n / L)); diffs = []; dA = []; dB = []
    for _ in range(2000):
        starts = np.random.randint(0, n, nb)
        idx = np.concatenate([np.arange(s, s + L) % n for s in starts])[:n]
        a = calmar(rA[idx]); b = calmar(rB[idx]); diffs.append(a - b); dA.append(a); dB.append(b)
    diffs = np.array(diffs)
    print(f"\n[블록 L={L}일, 2000회] Calmar차(0.4/180 − 0.3/126):")
    print(f"  평균 {diffs.mean():+.3f}  중앙 {np.median(diffs):+.3f}  5~95% CI [{np.percentile(diffs,5):+.3f}, {np.percentile(diffs,95):+.3f}]")
    print(f"  P(0.4/180 > 0.3/126) = {(diffs>0).mean()*100:.1f}%   (90%+ 면 robust 우위)")
