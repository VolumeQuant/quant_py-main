# -*- coding: utf-8 -*-
"""제대로된 가중치 재최적화: 653 풀그리드 × 오버레이 포함(검증된 재계산) × 인접CV.
_sp_overheat의 recompute(과열캡/mom10/vol_low 포함, production 100% 일치)를 그리드로.
usage: python _sp_optsweep.py <lo> <hi> [folders...]   기본 _sp0,_sp1,_sp2"""
import sys, json, glob, os
import pandas as pd, numpy as np
sys.stdout.reconfigure(encoding='utf-8')
LO = sys.argv[1] if len(sys.argv) > 1 else '20250601'
HI = sys.argv[2] if len(sys.argv) > 2 else '20260611'
FOLDERS = sys.argv[3:] if len(sys.argv) > 3 else ['_sp0', '_sp1', '_sp2']
LBL = {'_sp0': 'annual(현행)', '_sp1': 'TTM(PER만)', '_sp2': 'TTM(PER+ROE)'}
DATA = 'data_cache'
oh = pd.read_parquet(sorted(glob.glob(f'{DATA}/all_ohlcv_*_2026061*.parquet'))[0]).replace(0, np.nan)
oh.index = pd.to_datetime(oh.index)
def ba(s):
    r = s.pct_change(fill_method=None); ev = r[(r < -0.33) | (r > 0.45)]; s2 = s.copy()
    for d, rt in ev.items():
        f = 1 + rt
        if 0.02 < abs(f) < 50: s2.loc[s2.index < d] *= f
    return s2
ADJ = {tk: ba(oh[tk]) for tk in oh.columns if oh[tk].dropna().shape[0] > 30}
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
# 오버레이 가중치 고정 (production)
OH_W, M10_W, VL_W = 0.2, 0.05, 0.06
def recompute_cr(stocks, V, Q, G, M):
    scored = []
    for s in stocks:
        tk = str(s['ticker']).zfill(6)
        sc = (V*s.get('value_s', 0) + Q*s.get('quality_s', 0) + G*s.get('growth_s', 0) + M*s.get('momentum_s', 0)
              + M10_W*s.get('mom_10_z', 0) + VL_W*s.get('vol_low_z', 0) + OH_W*s.get('overheat_pen', 0))
        scored.append((tk, sc))
    scored.sort(key=lambda x: -x[1])
    return {tk: i+1 for i, (tk, _) in enumerate(scored)}
def load_raw(folder):
    raw = {}
    for f in sorted(glob.glob(f'{folder}/ranking_*.json')):
        ds = os.path.basename(f)[8:16]
        if ds.isdigit() and len(ds) == 8 and LO <= ds <= HI:
            raw[ds] = json.load(open(f, encoding='utf-8'))['rankings']
    return raw
def run(raw, V, Q, G, M, reg=None, EB=3, XB=6, SLOTS=3, TOPN=20, PEN=50):
    dates = sorted(raw.keys())
    if reg is None: reg = regime_cross(dates)
    cr = {ds: recompute_cr(raw[ds], V/100, Q/100, G/100, M/100) for ds in dates}
    pf = {}; eq = 1.0; eh = {}
    def pen(c): return c if c <= TOPN else PEN
    for i, ds in enumerate(dates):
        ib = reg.get(ds, True)
        if i >= 1 and pf:
            rs = [gp(ds, tk)/gp(dates[i-1], tk) - 1 for tk in pf if gp(dates[i-1], tk) and gp(ds, tk)]
            if rs: eq *= (1 + np.mean(rs) * len(pf) / SLOTS)
        eh[ds] = eq
        if i >= 1 and reg.get(dates[i-1], True) != ib: pf.clear()
        if not ib: continue
        c0 = cr.get(ds, {}); c1 = cr.get(dates[i-1], {}) if i >= 1 else {}; c2 = cr.get(dates[i-2], {}) if i >= 2 else {}
        wr = {tk: c*0.4 + pen(c1.get(tk, PEN))*0.35 + pen(c2.get(tk, PEN))*0.25 for tk, c in c0.items()}
        for tk in list(pf):
            if wr.get(tk, 999) > XB: del pf[tk]
        for tk, _ in sorted(wr.items(), key=lambda x: x[1])[:EB]:
            if tk in pf: continue
            if len(pf) >= SLOTS: break
            cp = gp(ds, tk)
            if cp: pf[tk] = cp
    ea = np.array(list(eh.values()))
    if len(ea) < 2: return 0, 0, 0
    cagr = (ea[-1]**(252/len(ea)) - 1) * 100
    p = np.maximum.accumulate(ea); mdd = -((ea - p)/p).min() * 100
    return (cagr/mdd if mdd > 0 else 0), cagr, mdd
combos = [(v, q, g, 100-v-q-g) for v in range(0, 45, 5) for q in range(0, 45, 5)
          for g in range(10, 75, 5) if 10 <= 100-v-q-g <= 60]
print(f'[기간] {LO}~{HI}  풀그리드 {len(combos)}조합 × 오버레이 포함')
best = {}
for folder in FOLDERS:
    raw = load_raw(folder)
    if len(raw) < 30: print(f'{LBL.get(folder,folder)}: 데이터부족 {len(raw)}일'); continue
    reg = regime_cross(sorted(raw.keys()))
    res = []
    for (v, q, g, m) in combos:
        cal, cg, md = run(raw, v, q, g, m, reg)
        res.append((v, q, g, m, cal, cg, md))
    res.sort(key=lambda x: -x[4])
    bp = run(raw, 15, 0, 55, 30, reg)
    best[folder] = res[0]
    print(f'\n=== {LBL.get(folder,folder)} ({folder}, {len(raw)}일) ===')
    print(f'  baseline V15Q0G55M30: Cal {bp[0]:.2f} (CAGR {bp[1]:.0f} MDD {bp[2]:.0f})')
    print(f"  {'V':>3}{'Q':>3}{'G':>3}{'M':>3}{'Cal':>7}{'CAGR':>7}{'MDD':>6}")
    for v, q, g, m, cal, cg, md in res[:5]:
        print(f"  {v:>3}{q:>3}{g:>3}{m:>3}{cal:>7.2f}{cg:>7.0f}{md:>6.0f}")
    # 인접 CV (best 주변 ±5)
    bv, bq, bg, bm = res[0][:4]
    adj = [run(raw, max(0,bv+dv), max(0,bq+dq), bg, 100-max(0,bv+dv)-max(0,bq+dq)-bg, reg)[0]
           for dv in (-5,0,5) for dq in (-5,0,5) if 10 <= 100-max(0,bv+dv)-max(0,bq+dq)-bg <= 60]
    adj = [a for a in adj if a > 0]
    if len(adj) > 2:
        cv = np.std(adj)/np.mean(adj)
        print(f'  인접 CV: {cv:.3f} ({"안정" if cv<0.3 else "불안정-과적합의심"})')
if len(best) >= 2:
    print(f"\n{'='*55}")
    for f in FOLDERS:
        if f in best:
            b = best[f]; print(f"  {LBL.get(f,f):<16} best Cal {b[4]:.2f} (V{b[0]}Q{b[1]}G{b[2]}M{b[3]})")
