# -*- coding: utf-8 -*-
"""2x2: {annual,TTM} x {과열캡 ON,OFF}. z-score 재조합으로 score 재계산.
먼저 재계산이 production composite_rank와 일치하는지 검증 후 BT.
usage: python _sp_overheat.py <lo> <hi>"""
import sys, json, glob, os
import pandas as pd, numpy as np
sys.stdout.reconfigure(encoding='utf-8')
LO = sys.argv[1] if len(sys.argv) > 1 else '20250601'
HI = sys.argv[2] if len(sys.argv) > 2 else '20260611'
DATA = 'data_cache'
# 권리락 보정
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

# 프로덕션 boost 가중치
W_PROD = dict(V=0.15, Q=0.0, G=0.55, M=0.30, m10=0.05, vl=0.06, oh=0.2)
def recompute_cr(stocks, w):
    """z-score 재조합 → score → cr(1=최고점). production 동일식."""
    scored = []
    for s in stocks:
        tk = str(s['ticker']).zfill(6)
        sc = (w['V']*s.get('value_s', 0) + w['Q']*s.get('quality_s', 0)
              + w['G']*s.get('growth_s', 0) + w['M']*s.get('momentum_s', 0)
              + w['m10']*s.get('mom_10_z', 0) + w['vl']*s.get('vol_low_z', 0)
              + w['oh']*s.get('overheat_pen', 0))
        scored.append((tk, sc))
    scored.sort(key=lambda x: -x[1])
    return {tk: i+1 for i, (tk, _) in enumerate(scored)}

def load_raw(folder):
    raw = {}
    for f in sorted(glob.glob(f'{folder}/ranking_*.json')):
        ds = os.path.basename(f)[8:16]
        if not (ds.isdigit() and len(ds) == 8 and LO <= ds <= HI): continue
        d = json.load(open(f, encoding='utf-8'))
        raw[ds] = d['rankings']
    return raw

# --- 검증: _sp0 재계산 cr vs JSON composite_rank ---
raw0 = load_raw('_sp0')
ds_test = sorted(raw0.keys())[len(raw0)//2]
mine = recompute_cr(raw0[ds_test], W_PROD)
jcr = {str(s['ticker']).zfill(6): int(s.get('composite_rank', s['rank'])) for s in raw0[ds_test]}
common = set(mine) & set(jcr)
exact = sum(1 for t in common if mine[t] == jcr[t])
top10_match = sum(1 for t in common if mine[t] <= 10 and jcr[t] <= 10) / max(1, sum(1 for t in jcr.values() if t <= 10))
print(f'[검증] {ds_test}: 재계산 cr vs production composite_rank')
print(f'  정확일치 {exact}/{len(common)} ({exact/len(common)*100:.0f}%), top10 교집합 {top10_match*100:.0f}%')
sample_diff = [(t, mine[t], jcr[t]) for t in sorted(common, key=lambda x: jcr[x])[:8]]
print('  상위8 (tk: 내cr / prod cr):', [(t, m, j) for t, m, j in sample_diff])

# --- 포트폴리오 시뮬 ---
def run(raw, w, EB=3, XB=6, SLOTS=3, TOPN=20, PEN=50):
    dates = sorted(raw.keys()); reg = regime_cross(dates)
    cr = {ds: recompute_cr(raw[ds], w) for ds in dates}
    pf = {}; eq = 1.0; eh = {}
    def pen(c): return c if c <= TOPN else PEN
    for i, ds in enumerate(dates):
        ib = reg.get(ds, True)
        if i >= 1 and pf:
            rs = []
            for tk in pf:
                pp = gp(dates[i-1], tk); cp = gp(ds, tk)
                if pp and cp: rs.append(cp/pp - 1)
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
    cagr = (ea[-1]**(252/len(ea)) - 1) * 100
    p = np.maximum.accumulate(ea); mdd = -((ea - p)/p).min() * 100
    return cagr/mdd if mdd > 0 else 0, cagr, mdd, ea[-1]

raw1 = load_raw('_sp1')
W_NOOH = dict(W_PROD); W_NOOH['oh'] = 0.0
print(f'\n[기간] {LO}~{HI}  (_sp0 {len(raw0)}일, _sp1 {len(raw1)}일)')
print(f"{'케이스':<22}{'Calmar':>8}{'CAGR':>8}{'MDD':>7}{'배수':>7}")
for lbl, raw, w in [('A.annual+과열캡(현행)', raw0, W_PROD), ('B.TTM+과열캡(중복)', raw1, W_PROD),
                    ('C.TTM+과열캡OFF', raw1, W_NOOH), ('D.annual+과열캡OFF', raw0, W_NOOH)]:
    cal, cg, md, mx = run(raw, w)
    print(f'{lbl:<22}{cal:>8.2f}{cg:>7.0f}%{md:>6.1f}%{mx:>7.2f}')
