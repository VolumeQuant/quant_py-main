# -*- coding: utf-8 -*-
"""USE_SELF_PER 0(annual) vs 1(TTM) — 가중치 재최적화 비교 (TurboSim regimefull 재사용).
각 base(_sp0/_sp1)에서 V/Q/G/M 전체 그리드 × defense=cash 스윕 → best-vs-best.
_q_weight_bt.py regimefull 모드 그대로, 폴더+날짜범위만 파라미터화.
usage: python _sp_sweep.py <lo> <hi>   (예: 20250601 20260611 = 표본)"""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LO = sys.argv[1] if len(sys.argv) > 1 else '20250601'
HI = sys.argv[2] if len(sys.argv) > 2 else '20260611'

# 권리락 보정 가격 (production 정합)
def ba(s):
    r = s.pct_change(fill_method=None); ev = r[(r < -0.33) | (r > 0.45)]; s2 = s.copy()
    for d, rt in ev.items():
        f = 1 + rt
        if 0.02 < abs(f) < 50: s2.loc[s2.index < d] *= f
    return s2
praw = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ, 'data_cache', 'all_ohlcv_*_2026061*.parquet')))[0]).replace(0, np.nan)
prices = praw.apply(ba)

kdf = pd.read_parquet(os.path.join(PROJ, 'data_cache', 'kospi_yf.parquet'))
kc = kdf.iloc[:, 0] if kdf.shape[1] else kdf['Close']
ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()
def calc_reg(dsub):
    reg = {}; md = True; stk = 0; ss = None
    for d in dsub:
        ts = pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts, np.nan)):
            reg[d] = md; continue
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
        if not (dt.isdigit() and len(dt) == 8 and LO <= dt <= HI): continue
        try:
            d = json.load(open(f, encoding='utf-8'))
            ar[dt] = d.get('rankings', d) if isinstance(d, dict) else d
            dates.append(dt)
        except Exception: pass
    return ar, sorted(dates)

combos = []
for v in range(0, 45, 5):
    for q in range(0, 45, 5):
        for g in range(10, 75, 5):
            m = 100 - v - q - g
            if 10 <= m <= 60: combos.append((v, q, g, m))

print(f'[기간] {LO}~{HI}  그리드 {len(combos)}조합')
results = {}
for folder, lbl in [('_sp0', 'annual(현행)'), ('_sp1', 'TTM')]:
    ar, dates = load(folder)
    if len(dates) < 30:
        print(f'{lbl}: 데이터부족 {len(dates)}일'); continue
    tsim = TurboSimulator(ar, dates, prices)
    reg = calc_reg(dates)
    def rbt(v, q, g, m):
        tsim._ensure_cache(v/100, q/100, g/100, m/100, 0.4, 20, '12m', *G3[:3], *G3[3:])
        flat = list(tsim._cached_flat)
        return _run_regime_inner(flat, flat, 0, 6, 3, 3, 6, 3, reg, dates,
            tsim._price_arr, tsim._bench_arr, tsim._has_bench, tsim._date_row_indices, len(dates),
            None, None, None, None, stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None)
    res = []
    for (v, q, g, m) in combos:
        r = rbt(v, q, g, m)
        res.append((v, q, g, m, r.get('calmar', 0), r.get('cagr', 0), r.get('mdd', 0)))
    res.sort(key=lambda x: -x[4])
    base = rbt(15, 0, 55, 30)
    results[lbl] = (res, base)
    print(f'\n=== {lbl} ({folder}, {len(dates)}일, boost {sum(reg.values())}일) ===')
    print(f"  baseline V15Q0G55M30: Calmar {base['calmar']:.3f} (CAGR {base['cagr']:.0f} MDD {base['mdd']:.0f})")
    print(f"  재최적화 best:")
    print(f"  {'V':>3}{'Q':>3}{'G':>3}{'M':>3}{'Calmar':>8}{'CAGR':>7}{'MDD':>7}")
    for v, q, g, m, cal, cg, md in res[:6]:
        print(f"  {v:>3}{q:>3}{g:>3}{m:>3}{cal:>8.3f}{cg:>7.0f}{md:>7.0f}")
    # Q 임계별 (ROE TTM 가치 판단용 — best가 Q>0 원하나?)
    for qm in [0, 10, 20]:
        c = [x for x in res if x[1] >= qm]
        if c:
            v, q, g, m, cal, cg, md = max(c, key=lambda x: x[4])
            print(f"    Q>={qm}: V{v}Q{q}G{g}M{m} Cal {cal:.3f}")

# best-vs-best 결론
if 'annual(현행)' in results and 'TTM' in results:
    ab = results['annual(현행)'][0][0]; tb = results['TTM'][0][0]
    print(f"\n{'='*50}")
    print(f"best-vs-best: annual {ab[4]:.3f} (V{ab[0]}Q{ab[1]}G{ab[2]}M{ab[3]}) vs TTM {tb[4]:.3f} (V{tb[0]}Q{tb[1]}G{tb[2]}M{tb[3]})")
    print(f"→ TTM 재최적화가 annual 재최적화 대비: {tb[4]-ab[4]:+.3f} Calmar")
