# -*- coding: utf-8 -*-
"""맹점#1 검증: 내 hand-rolled sim(오버레이 OFF) == TurboSim?
같은 _sp0, V15Q0G55M30, 순수4팩터에서 Calmar 일치해야 내 sim 신뢰가능."""
import sys, json, glob, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd, numpy as np
sys.stdout.reconfigure(encoding='utf-8')
from turbo_simulator import TurboSimulator, _run_regime_inner
LO, HI = '20250601', '20260611'
DATA = 'data_cache'
oh = pd.read_parquet(sorted(glob.glob(f'{DATA}/all_ohlcv_*_2026061*.parquet'))[0]).replace(0, np.nan)
oh.index = pd.to_datetime(oh.index)
def ba(s):
    r = s.pct_change(fill_method=None); ev = r[(r < -0.33) | (r > 0.45)]; s2 = s.copy()
    for d, rt in ev.items():
        f = 1 + rt
        if 0.02 < abs(f) < 50: s2.loc[s2.index < d] *= f
    return s2
prices = oh.apply(ba)  # TurboSim용 (백조정)
ADJ = {tk: prices[tk] for tk in prices.columns}
kospi = pd.read_parquet(f'{DATA}/kospi_yf.parquet')['close'].sort_index(); kospi.index = pd.to_datetime(kospi.index)
def regime_cross(ds_list):
    sma = kospi.rolling(20).mean(); lma = kospi.rolling(80).mean(); reg = {}; md = False; stk = 0; ss = None
    for d in ds_list:
        ts = pd.Timestamp(d); sv = sma.get(ts); lv = lma.get(ts)
        if sv is None or pd.isna(sv) or pd.isna(lv): reg[d] = md; continue
        s = sv > lv
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= 5 and md != s: md = s
        reg[d] = md
    return reg
def gp(d, tk):
    ts = pd.Timestamp(d)
    if tk not in ADJ: return None
    s = ADJ[tk]
    if ts not in s.index:
        idx = s.index.searchsorted(ts)
        if idx >= len(s): return None
        ts = s.index[idx]
    v = s.get(ts)
    return v if (v is not None and pd.notna(v) and v > 0) else None
raw = {}; ar = {}
for f in sorted(glob.glob('_sp0/ranking_*.json')):
    ds = os.path.basename(f)[8:16]
    if ds.isdigit() and len(ds) == 8 and LO <= ds <= HI:
        d = json.load(open(f, encoding='utf-8')); raw[ds] = d['rankings']; ar[ds] = d['rankings']
dates = sorted(raw.keys())
reg = regime_cross(dates)
# --- 내 hand-rolled sim (오버레이 전부 OFF = 순수 V/Q/G/M) ---
def recompute_cr(stocks, V, Q, G, M):
    sc = [(str(s['ticker']).zfill(6), V*s.get('value_s',0)+Q*s.get('quality_s',0)+G*s.get('growth_s',0)+M*s.get('momentum_s',0)) for s in stocks]
    sc.sort(key=lambda x: -x[1]); return {tk: i+1 for i, (tk, _) in enumerate(sc)}
def myrun(V, Q, G, M, EB=3, XB=6, SLOTS=3, TOPN=20, PEN=50):
    cr = {ds: recompute_cr(raw[ds], V/100, Q/100, G/100, M/100) for ds in dates}
    pf = {}; eq = 1.0; eh = {}
    def pen(c): return c if c <= TOPN else PEN
    for i, ds in enumerate(dates):
        ib = reg.get(ds, True)
        if i >= 1 and pf:
            rs = [gp(ds, tk)/gp(dates[i-1], tk)-1 for tk in pf if gp(dates[i-1], tk) and gp(ds, tk)]
            if rs: eq *= (1 + np.mean(rs)*len(pf)/SLOTS)
        eh[ds] = eq
        if i >= 1 and reg.get(dates[i-1], True) != ib: pf.clear()
        if not ib: continue
        c0 = cr.get(ds, {}); c1 = cr.get(dates[i-1], {}) if i>=1 else {}; c2 = cr.get(dates[i-2], {}) if i>=2 else {}
        wr = {tk: c*0.4+pen(c1.get(tk,PEN))*0.35+pen(c2.get(tk,PEN))*0.25 for tk, c in c0.items()}
        for tk in list(pf):
            if wr.get(tk, 999) > XB: del pf[tk]
        for tk, _ in sorted(wr.items(), key=lambda x: x[1])[:EB]:
            if tk in pf: continue
            if len(pf) >= SLOTS: break
            cp = gp(ds, tk)
            if cp: pf[tk] = cp
    ea = np.array(list(eh.values()))
    cagr = (ea[-1]**(252/len(ea))-1)*100; p = np.maximum.accumulate(ea); mdd = -((ea-p)/p).min()*100
    return cagr/mdd if mdd > 0 else 0, cagr, mdd
mc = myrun(15, 0, 55, 30)
# --- TurboSim (동일 config, 순수 4팩터) ---
tsim = TurboSimulator(ar, dates, prices)
tsim._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', 'rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)
flat = list(tsim._cached_flat)
tr = _run_regime_inner(flat, flat, 0, 6, 3, 3, 6, 3, reg, dates, tsim._price_arr, tsim._bench_arr,
    tsim._has_bench, tsim._date_row_indices, len(dates), None, None, None, None,
    stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None)
print(f'내 hand-rolled sim (오버레이 OFF): Calmar {mc[0]:.3f}  CAGR {mc[1]:.1f}  MDD {mc[2]:.1f}')
print(f'TurboSim (동일 config)          : Calmar {tr["calmar"]:.3f}  CAGR {tr["cagr"]:.1f}  MDD {tr["mdd"]:.1f}')
diff = abs(mc[0]-tr['calmar'])
print(f'\nCalmar 차이: {diff:.3f} → {"✅ 일치(내 sim 신뢰가능)" if diff < 0.5 else "🔴 불일치(내 sim 기제 점검 필요)"}')
