# -*- coding: utf-8 -*-
"""TTM vs annual full-grid 공정비교 (2026-06-16, 회사PC 재검증).
같은배치 _sp0b(annual) vs _sp2b(TTM). 그리드: V/Q/G/M(V>=10) × 모멘텀4종 × 슬롯3종. regime 20/80/5 고정(공통).
★max-selection 편향 방지: best-vs-best + 고정 운영config 둘 다 보고.
usage: python _sp_fullgrid.py [LO HI]  (기본 전기간)"""
import sys, io, os, glob, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LO = sys.argv[1] if len(sys.argv) > 1 else '20190102'
HI = sys.argv[2] if len(sys.argv) > 2 else '20261231'
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
        if dt.isdigit() and len(dt) == 8 and LO <= dt <= HI:
            ar[dt] = json.load(open(f, encoding='utf-8'))['rankings']; dates.append(dt)
    return ar, sorted(dates)
COMBOS = [(v, q, g, 100-v-q-g) for v in [10, 15, 20, 25, 30] for q in [0, 5, 10]
          for g in range(15, 70, 5) if 10 <= 100-v-q-g <= 60]
MOMS = ['6m', '6m-1m', '12m', '12m-1m']
SLOTS = [(3, 3, 6), (5, 5, 10), (10, 10, 20)]  # (slots, entry, exit)
ar0, d0 = load('_sp0c'); ar2, d2 = load('_sp3')  # Q2: 균등기준 annual(_sp0c) vs TTM(_sp3)
common = sorted(set(d0) & set(d2)); reg = calc_reg(common)
arc0 = {d: ar0[d] for d in common}; arc2 = {d: ar2[d] for d in common}
print(f"[기간 {common[0]}~{common[-1]} {len(common)}일] grid={len(COMBOS)}w × {len(MOMS)}mom × {len(SLOTS)}slot = {len(COMBOS)*len(MOMS)*len(SLOTS)}/base")

def run_base(ar, lbl):
    t = TurboSimulator(ar, common, prices, overheat_w=0.2); t._use_overlay = True; t._use_stored_growth = True
    overall = (None, -9); per_mom = {mm: (None, -9) for mm in MOMS}
    t0 = time.time()
    for v, q, g, m in COMBOS:
        for mm in MOMS:
            t._ensure_cache(v/100, q/100, g/100, m/100, 0.4, 20, mm, *G3[:3], *G3[3:])
            flat = list(t._cached_flat)
            for slots, entry, exit_ in SLOTS:
                cal = _run_regime_inner(flat, flat, 0, exit_, slots, entry, exit_, slots, reg, common,
                    t._price_arr, t._bench_arr, t._has_bench, t._date_row_indices, len(common),
                    None, None, None, None, stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None).get('calmar', 0)
                cfg = (v, q, g, m, mm, slots, entry, exit_)
                if cal > overall[1]: overall = (cfg, cal)
                if cal > per_mom[mm][1]: per_mom[mm] = (cfg, cal)
    # 고정 운영config (V15Q0G55M30, 12m, E3X6S3)
    t._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
    flat = list(t._cached_flat)
    prodcal = _run_regime_inner(flat, flat, 0, 6, 3, 3, 6, 3, reg, common, t._price_arr, t._bench_arr,
        t._has_bench, t._date_row_indices, len(common), None, None, None, None,
        stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None).get('calmar', 0)
    print(f"  [{lbl}] {time.time()-t0:.0f}초")
    return overall, per_mom, prodcal

(ov0, pm0, prod0) = run_base(arc0, 'annual')
(ov2, pm2, prod2) = run_base(arc2, 'TTM')
def fmt(c): return f"V{c[0]}Q{c[1]}G{c[2]}M{c[3]} {c[4]} S{c[5]}(E{c[6]}X{c[7]})"
print(f"\n{'='*70}")
print(f"★ 고정 운영config (V15Q0G55M30 12m E3X6S3) — 공정비교(편향無):")
print(f"   annual {prod0:.3f}  vs  TTM {prod2:.3f}   Δ(TTM-ann) {prod2-prod0:+.3f}")
print(f"\n전체 best (V>=10 강제, full grid):")
print(f"   annual best: {fmt(ov0[0])} = {ov0[1]:.3f}")
print(f"   TTM    best: {fmt(ov2[0])} = {ov2[1]:.3f}   Δ(TTM-ann best-vs-best) {ov2[1]-ov0[1]:+.3f}")
print(f"\n모멘텀별 best (annual vs TTM):")
print(f"{'mom':<8}{'annual best':<30}{'TTM best':<30}{'Δ':>7}")
for mm in MOMS:
    a = pm0[mm]; tt = pm2[mm]
    print(f"{mm:<8}{fmt(a[0])+f'={a[1]:.2f}':<30}{fmt(tt[0])+f'={tt[1]:.2f}':<30}{tt[1]-a[1]:>+7.2f}")
print(f"\n→ 판정: 고정config Δ가 핵심(편향無). best-vs-best Δ만 크고 고정config Δ 작으면 = max-selection 편향(어제 함정). 둘 다 TTM>annual이면 진짜 우위.")
