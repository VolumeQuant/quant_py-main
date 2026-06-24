# -*- coding: utf-8 -*-
"""일회성 필터 3변형 오버레이 BT (2026-06-25, 효율적: 풀재생성 대신 growth_s 조정).
baseline(현 production: 매출lump+계절성+accruals) 대비:
 B: +영익lump (영익 4분기 전부양수 & min/max<0.25 → growth_s ×0.3)
 C: 계절성제거 (min/max≤0.2 종목 = 계절성발동분 → growth_s ÷0.5 페널티되돌림)
 D: B+C
TurboSim _use_stored_growth=True에 조정된 growth_s 주입. 5분."""
import sys, io, os, glob, json, bisect
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices = pd.read_parquet(sorted(glob.glob(P + '/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
kc = pd.read_parquet(P + '/data_cache/kospi_yf.parquet').iloc[:, 0]
ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()
G3 = ('rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)
def calc_reg(ds):
    reg = {}; md = True; stk = 0; ss = None
    for d in ds:
        ts = pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts, np.nan)): reg[d] = md; continue
        s = bool(ma20[ts] > ma80[ts]); stk = stk+1 if s == ss else 1; ss = s
        if stk >= 5 and md != s: md = s
        reg[d] = md
    return reg

# state 로드
ar0, days = {}, []
for f in sorted(glob.glob(P + '/state/ranking_*.json')):
    dt = os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt) == 8 and dt >= '20190102':
        ar0[dt] = json.load(open(f, encoding='utf-8'))['rankings']; days.append(dt)
days = sorted(days)
# 등장 종목 fs 로드 (영익/매출 분기 시계열, rcept_dt 정렬)
tickers = set(x['ticker'] for d in days for x in ar0[d])
fs_op = {}; fs_rev = {}
for tk in tickers:
    f = f'{P}/data_cache/fs_dart_{tk}.parquet'
    if not os.path.exists(f): continue
    d = pd.read_parquet(f)
    for acct, store in [('영업이익', fs_op), ('매출액', fs_rev)]:
        q = d[(d['공시구분'] == 'q') & (d['계정'] == acct)]
        q = q[q['rcept_dt'].notna()]
        if len(q) >= 4:
            q = q.sort_values('rcept_dt')
            store[tk] = (list(q['rcept_dt']), q['값'].astype(float).values)
def last4(store, tk, base_ts):
    if tk not in store: return None
    dts, vals = store[tk]
    i = bisect.bisect_right(dts, base_ts)
    if i < 8: return None  # 8분기 이상 (lumpiness 정합)
    return vals[i-4:i]
print(f"state {len(days)}일, fs 로드 영익 {len(fs_op)}·매출 {len(fs_rev)}종목")

# 변형별 growth_s 조정맵 (날짜별 {ticker: multiplier})
def build_adj(mode):
    adj = {}
    for d in days:
        base_ts = pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        m = {}
        for x in ar0[d]:
            tk = x['ticker']; mult = 1.0
            if mode in ('B', 'D'):  # 영익lump 추가
                o = last4(fs_op, tk, base_ts)
                if o is not None and (o > 0).all() and o.min()/o.max() < 0.25:
                    mult *= 0.3
            if mode in ('C', 'D'):  # 계절성제거 (min/max<=0.2 되돌림 ÷0.5)
                r = last4(fs_rev, tk, base_ts)
                if r is not None and (r > 0).all() and r.min()/r.max() <= 0.2:
                    mult /= 0.5
            if mult != 1.0: m[tk] = mult
        adj[d] = m
    return adj

def runbt(adj=None):
    ar = ar0 if adj is None else {d: [{**x, 'growth_s': (x.get('growth_s') or 0)*adj[d].get(x['ticker'], 1.0)} for x in ar0[d]] for d in days}
    reg = calc_reg(days)
    t = TurboSimulator(ar, days, prices, overheat_w=0.2); t._use_overlay = True; t._use_stored_growth = True
    for d in days:
        tks = t._preextracted[d][0]; fd = {x['ticker']: x for x in ar[d]}
        t._overlay_pre[d] = np.array([0.2*(fd[tk].get('overheat_pen') or 0)+0.05*(fd[tk].get('mom_10_z') or 0)
                                      +0.06*(fd[tk].get('vol_low_z') or 0)-0.3*(fd[tk].get('recent_ca') or 0) for tk in tks])
    t._cached_key = None; t._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
    flat = list(t._cached_flat)
    def cal(lo, hi):
        sub = [d for d in days if lo <= d <= hi]
        fl = [flat[days.index(d)] for d in sub]
        r = _run_regime_inner(fl, fl, 0, 6, 3, 3, 6, 3, reg, sub, t._price_arr, t._bench_arr, t._has_bench,
                              t._date_row_indices, len(sub), None, None, None, None, stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None)
        return r.get('calmar', 0), r.get('mdd', 0)
    return cal('20190102','20260617'), cal('20220101','20231231')

print(f"\n{'변형':<28}{'전체Cal':>8}{'MDD':>7}{'약세Cal':>8}")
print("-"*52)
b = runbt(None); print(f"{'baseline (현 production)':<28}{b[0][0]:>8.3f}{b[0][1]*100:>6.1f}%{b[1][0]:>8.3f}")
for mode,nm in [('B','+영익lump'),('C','계절성제거'),('D','영익lump+계절성제거')]:
    adj = build_adj(mode); v = runbt(adj)
    nch = sum(len(adj[d]) for d in days)
    print(f"{nm:<28}{v[0][0]:>8.3f}{v[0][1]*100:>6.1f}%{v[1][0]:>8.3f}  (조정 {nch}종목-일)")
print("\n→ baseline 대비 전체Cal↑&약세↑면 채택. 영익lump가 우량주죽여 하락하면 기각.")
