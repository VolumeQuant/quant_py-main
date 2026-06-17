# -*- coding: utf-8 -*-
"""CA 타입 분해 BT: 신호 가격 변형별 Calmar 비교. RETURN은 항상 V_all(수정주가) 고정.
V_none(원주가/4.31) vs V_all(전부수정) vs V_down(무상증자·분할만) vs V_up(병합만).
형 가설: V_down≈4.31 > V_all 이면 '병합 미보정(약세종목 회피)'이 알파 = 가설 확증."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

VALL = sorted(glob.glob(os.path.join(PROJ, 'data_cache', 'all_ohlcv_adj_*.parquet')))[-1]
prices = pd.read_parquet(VALL).replace(0, np.nan)  # RETURN = 수정주가, NO ba
def ba(s):
    r = s.pct_change(fill_method=None); ev = r[(r < -0.33) | (r > 0.45)]; s2 = s.copy()
    for d, rt in ev.items():
        f = 1 + rt
        if 0.02 < abs(f) < 50: s2.loc[s2.index < d] *= f
    return s2
RAW = sorted(glob.glob(os.path.join(PROJ, 'data_cache', 'all_ohlcv_2017*_2026061*.parquet')))[-1]
prices_ba = pd.read_parquet(RAW).replace(0, np.nan).apply(ba)

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
def runbt(folder, sub, reg, px):
    ar, _ = load(folder)
    t = TurboSimulator({d: ar[d] for d in sub}, sub, px, overheat_w=0.2); t._use_overlay = True; t._use_stored_growth = True
    t._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
    flat = list(t._cached_flat)
    r = _run_regime_inner(flat, flat, 0, 6, 3, 3, 6, 3, reg, sub, t._price_arr, t._bench_arr, t._has_bench,
                          t._date_row_indices, len(sub), None, None, None, None,
                          stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None)
    return r.get('calmar', 0), r.get('cagr', 0), r.get('mdd', 0)

cand = [('V_none(원주가/4.31)', '_sp0b_co'), ('V_all(전부수정/정직)', '_var_adj'),
        ('V_down(무상증자·분할만)', '_var_vdown'), ('V_up(병합만)', '_var_vup')]
variants = [(nm, fol) for nm, fol in cand if glob.glob(os.path.join(PROJ, fol, 'ranking_*.json'))]
allsets = [set(load(fol)[1]) for nm, fol in variants]
common = sorted(set.intersection(*allsets))
reg = calc_reg(common)
print(f"공통 {common[0]}~{common[-1]} {len(common)}일 | 존재 변형 {len(variants)}/4")
print(f"{'변형':<24}{'Calmar':>8}{'CAGR':>7}{'MDD':>7}   (RETURN=V_all 수정주가)")
for nm, fol in variants:
    c = runbt(fol, common, reg, prices)
    print(f"{nm:<24}{c[0]:>8.3f}{c[1]*100:>6.0f}%{c[2]*100:>6.0f}%")
ca = runbt('_sp0b_co', common, reg, prices_ba)
print(f"\n[참고] V_none + ba수익률(어제 4.31 앵커): Calmar {ca[0]:.3f}")
print("\n→ V_down≈V_none(높음) & V_all 낮으면: '병합 미보정=약세종목 회피'가 알파(형 가설 ✓)")
print("→ 다 비슷하거나 V_all 최고면: CA타입 무관, 수정주가가 정답")
