# -*- coding: utf-8 -*-
"""LOWO 로버스트: 지배 승자 1개씩 제외하고 annual(_sp0) vs 완전TTM(_sp2) 재비교.
annual 우세가 단일종목 착시가 아닌지 확인. TurboSim 저장growth+overlay(정확).
결과 _sp_lowo_result.txt 저장."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
class _Tee:
    def __init__(self, *fs): self.fs = fs
    def write(self, x):
        for f in self.fs:
            try: f.write(x); f.flush()
            except Exception: pass
    def flush(self):
        for f in self.fs:
            try: f.flush()
            except Exception: pass
_resf = open(r'C:\dev\_sp_lowo_result.txt', 'w', encoding='utf-8')
sys.stdout = _Tee(sys.stdout, _resf)
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ = r'C:\dev'
WINNERS = [('000660', 'SK하이닉스'), ('080220', '제주반도체'), ('187870', '디바이스'), ('042700', '한미반도체')]
def ba(s):
    r = s.pct_change(fill_method=None); ev = r[(r < -0.33) | (r > 0.45)]; s2 = s.copy()
    for d, rt in ev.items():
        f = 1 + rt
        if 0.02 < abs(f) < 50: s2.loc[s2.index < d] *= f
    return s2
prices = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ, 'data_cache', 'all_ohlcv_*_2026061*.parquet')))[0]).replace(0, np.nan).apply(ba)
kdf = pd.read_parquet(os.path.join(PROJ, 'data_cache', 'kospi_yf.parquet'))
kc = kdf.iloc[:, 0] if kdf.shape[1] else kdf['Close']
ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()
def calc_reg(dsub):
    reg = {}; md = True; stk = 0; ss = None
    for d in dsub:
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
        if dt.isdigit() and len(dt) == 8:
            ar[dt] = json.load(open(f, encoding='utf-8'))['rankings']; dates.append(dt)
    return ar, sorted(dates)
def exclude(ar, tk):
    return {d: [s for s in rk if str(s['ticker']).zfill(6) != tk] for d, rk in ar.items()}
def regbt(ar, dates, reg, v, q, g, m):
    t = TurboSimulator(ar, dates, prices); t._use_overlay = True; t._use_stored_growth = True
    t._ensure_cache(v/100, q/100, g/100, m/100, 0.4, 20, '12m', *G3[:3], *G3[3:])
    flat = list(t._cached_flat)
    return _run_regime_inner(flat, flat, 0, 6, 3, 3, 6, 3, reg, dates, t._price_arr, t._bench_arr,
        t._has_bench, t._date_row_indices, len(dates), None, None, None, None,
        stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None)
ar0, d0 = load('_sp0'); ar2, d2 = load('_sp2')
print(f'[LOWO] _sp0 {len(d0)}일, _sp2 {len(d2)}일')
reg = calc_reg(d0)
print(f'\n{"제외 종목":<16}{"annual Cal":>12}{"TTM Cal":>10}{"annual-TTM":>12}')
b0 = regbt(ar0, d0, reg, 15, 0, 55, 30); b2 = regbt(ar2, d2, calc_reg(d2), 15, 0, 55, 30)
print(f'{"(없음=baseline)":<16}{b0["calmar"]:>12.3f}{b2["calmar"]:>10.3f}{b0["calmar"]-b2["calmar"]:>+12.3f}')
for tk, nm in WINNERS:
    e0 = exclude(ar0, tk); e2 = exclude(ar2, tk)
    r0 = regbt(e0, d0, reg, 15, 0, 55, 30); r2 = regbt(e2, d2, calc_reg(d2), 15, 0, 55, 30)
    tag = '✅annual우세' if r0['calmar'] > r2['calmar'] else '🔴TTM우세'
    print(f'{nm:<16}{r0["calmar"]:>12.3f}{r2["calmar"]:>10.3f}{r0["calmar"]-r2["calmar"]:>+12.3f}  {tag}')
print('\n→ 모든 제외 케이스에서 annual>TTM이면 단일종목 착시 아님(robust). TTM이 이기는 케이스 있으면 그 종목 의존.')
