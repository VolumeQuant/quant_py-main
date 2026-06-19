# -*- coding: utf-8 -*-
"""Q1 EDA: 1.6 가중 TTM 효과 격리 (2026-06-16).
_sp0b(annual, PCR/PSR/과열캡 @1.6가중) vs _sp0c(annual, 전부 균등). PER=annual 동일 → 순수 가중치 효과.
지표: 고정config Calmar + best Calmar + 밸류팩터 IC(fwd 20d) + 연도별."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def ba(s):
    r = s.pct_change(fill_method=None); ev = r[(r < -0.33) | (r > 0.45)]; s2 = s.copy()
    for d, rt in ev.items():
        f = 1 + rt
        if 0.02 < abs(f) < 50: s2.loc[s2.index < d] *= f
    return s2
prices = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ, 'data_cache', 'all_ohlcv_2017*_2026061*.parquet')))[-1]).replace(0, np.nan).apply(ba)
kc = pd.read_parquet(os.path.join(PROJ, 'data_cache', 'kospi_yf.parquet')).iloc[:, 0]
ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()
def calc_reg(ds):
    reg = {}; md = True; stk = 0; ss = None
    for d in ds:
        ts = pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
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
        if dt.isdigit() and len(dt) == 8: ar[dt] = json.load(open(f, encoding='utf-8'))['rankings']; dates.append(dt)
    return ar, sorted(dates)
def mk(ar, dates): t = TurboSimulator(ar, dates, prices, overheat_w=0.2); t._use_overlay = True; t._use_stored_growth = True; return t
def bt(t, dates, reg, v, q, g, m, mom='12m', slots=3, e=3, x=6):
    t._ensure_cache(v/100, q/100, g/100, m/100, 0.4, 20, mom, *G3[:3], *G3[3:])
    flat = list(t._cached_flat)
    return _run_regime_inner(flat, flat, 0, x, slots, e, x, slots, reg, dates, t._price_arr, t._bench_arr,
        t._has_bench, t._date_row_indices, len(dates), None, None, None, None,
        stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None).get('calmar', 0)
# 밸류팩터 IC (value_s vs fwd 20d 수익률, boost일만)
def value_ic(ar, dates, reg, fwd=20):
    px = prices; ics = []
    di = {d: i for i, d in enumerate(px.index.strftime('%Y%m%d'))}
    arr = px.values; cols = {c: i for i, c in enumerate(px.columns)}
    for d in dates:
        if not reg.get(d, True): continue
        if d not in di: continue
        i0 = di[d]; i1 = i0 + fwd
        if i1 >= len(arr): continue
        vs, fr = [], []
        for s in ar[d]:
            tk = s['ticker']; ci = cols.get(tk)
            if ci is None: continue
            p0, p1 = arr[i0, ci], arr[i1, ci]
            if p0 > 0 and p1 > 0 and s.get('value_s') is not None:
                vs.append(s['value_s']); fr.append(p1/p0 - 1)
        if len(vs) > 30:
            c = np.corrcoef(vs, fr)[0, 1]
            if not np.isnan(c): ics.append(c)
    return np.mean(ics) if ics else float('nan')
COMBOS = [(v, q, g, 100-v-q-g) for v in [10, 15, 20, 25, 30] for q in [0, 5, 10] for g in range(15, 70, 5) if 10 <= 100-v-q-g <= 60]
ar0, d0 = load('_sp0b'); arC, dC = load('_sp0c')
common = sorted(set(d0) & set(dC)); reg = calc_reg(common)
a0 = {d: ar0[d] for d in common}; aC = {d: arC[d] for d in common}
print(f"[기간 {common[0]}~{common[-1]} {len(common)}일]  _sp0b(annual 1.6) vs _sp0c(annual 균등)")
t0 = mk(a0, common); tC = mk(aC, common)
print(f"\n=== ① 고정 운영config (V15Q0G55M30 12m E3X6S3) ===")
c0 = bt(t0, common, reg, 15, 0, 55, 30); cC = bt(tC, common, reg, 15, 0, 55, 30)
print(f"  1.6가중 {c0:.3f}  vs  균등 {cC:.3f}   Δ(균등-1.6) {cC-c0:+.3f}")
print(f"\n=== ② best (V>=10 grid, S3) ===")
b0 = max(bt(t0, common, reg, *c) for c in COMBOS); bC = max(bt(tC, common, reg, *c) for c in COMBOS)
print(f"  1.6가중 best {b0:.3f}  vs  균등 best {bC:.3f}   Δ {bC-b0:+.3f}")
print(f"\n=== ③ 밸류팩터 IC (value_s vs fwd 20d, boost일, 노이즈 적은 척도) ===")
ic0 = value_ic(a0, common, reg); icC = value_ic(aC, common, reg)
print(f"  1.6가중 IC {ic0:.4f}  vs  균등 IC {icC:.4f}   Δ {icC-ic0:+.4f}")
print(f"\n=== ④ 연도별 고정config Calmar ===")
for y in ['2019','2020','2021','2022','2023','2024','2025','2026']:
    ds = [d for d in common if d[:4] == y]
    if len(ds) < 20: continue
    s0 = mk({d: a0[d] for d in ds}, ds); sC = mk({d: aC[d] for d in ds}, ds); rg = calc_reg(ds)
    print(f"  {y}: 1.6 {bt(s0,ds,rg,15,0,55,30):>6.2f}  균등 {bt(sC,ds,rg,15,0,55,30):>6.2f}")
print(f"\n→ 고정config·IC 둘 다 차이 작으면 '1.6 가중은 무의미(균등으로 통일해도 무해)'. 균등이 일관 우위면 '1.6은 나쁜 변형'.")
