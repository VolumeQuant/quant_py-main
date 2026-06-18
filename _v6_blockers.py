# -*- coding: utf-8 -*-
"""차단2+6: CA 방향분해 + 혼동행렬.
① raw갭 이벤트 방향 태깅(down=무상/분할/유상 <-33%, up=병합 >+45%)
② 혼동행렬: genuine CA(adj/raw 점프) vs raw갭 발동 → TP/FP/FN (FN=gap<임계라 놓친 진짜CA)
③ 페널티 방향분해 BT(state base, W0.3 K126): down-only / up-only / both(현행) → 병합 기여 측정"""
import sys, io, os, glob, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backtest'))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ = os.path.dirname(os.path.abspath(__file__)); DC = os.path.join(PROJ, 'data_cache')
prices = pd.read_parquet(sorted(glob.glob(os.path.join(DC, 'all_ohlcv_adj_*.parquet')))[-1]).replace(0, np.nan)
raw = pd.read_parquet(sorted(glob.glob(os.path.join(DC, 'all_ohlcv_2017*_2026*.parquet')))[-1]).replace(0, np.nan)
adj = pd.read_parquet(sorted(glob.glob(os.path.join(DC, 'adjusted_close_*.parquet')))[-1])
kc = pd.read_parquet(os.path.join(DC, 'kospi_yf.parquet')).iloc[:, 0]
ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()
G3 = ('rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)
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
ca_raw = json.load(open(os.path.join(DC, 'ca_events.json'), encoding='utf-8'))['ca_by_ticker']

# ① raw갭 방향 태깅 (각 이벤트 날짜의 raw pct_change 부호)
rawret = raw.pct_change(fill_method=None)
ev_dir = {}  # tk -> {date: 'down'/'up'}
dn_caby, up_caby = {}, {}
nd = nu = 0
for tk, ds in ca_raw.items():
    if tk not in rawret.columns: continue
    for d in ds:
        ts = pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in rawret.index: continue
        r = rawret.at[ts, tk]
        if not np.isfinite(r): continue
        if r < -0.33: dn_caby.setdefault(tk, []).append(d); nd += 1
        elif r > 0.45: up_caby.setdefault(tk, []).append(d); nu += 1
print(f"=== ① raw갭 방향분해 ===\n  down(무상/분할/유상) {nd}건/{len(dn_caby)}종목 | up(병합) {nu}건/{len(up_caby)}종목")

# ② 혼동행렬: genuine CA(adj/raw 점프) → raw move 크기로 TP(caught)/FN(missed)
THR = 0.02
TP = FN = 0; fn_samp = []
for tk in adj.columns:
    if tk not in raw.columns: continue
    df = pd.DataFrame({'raw': raw[tk], 'adj': adj[tk].reindex(raw.index)}).dropna()
    if len(df) < 2: continue
    dlog = np.log(df['adj']/df['raw']).diff()
    for dt, v in dlog.items():
        if not (np.isfinite(v) and abs(v) >= THR): continue  # genuine CA event
        # 이 날짜 ±2영업일내 raw갭(>33%/45%) 발생?
        win = rawret[tk].reindex(raw.index)
        loc = raw.index.get_loc(dt)
        seg = rawret[tk].iloc[max(0,loc-2):loc+3]
        caught = ((seg < -0.33) | (seg > 0.45)).any()
        if caught: TP += 1
        else:
            FN += 1
            if len(fn_samp) < 6: fn_samp.append((tk, dt.strftime('%Y%m%d'), round(float(v),3)))
FP = sum(len(v) for v in ca_raw.values())  # placeholder, 정확 FP는 V2서 617
print(f"=== ② 혼동행렬 (genuine CA = adj/raw 점프 기준) ===")
print(f"  TP(genuine이고 raw갭도 발동=잡힘) {TP} | FN(genuine인데 raw갭<임계=놓침) {FN}")
print(f"  → genuine CA 커버리지 {TP/(TP+FN)*100:.1f}% | 놓친비율(FN) {FN/(TP+FN)*100:.1f}%")
print(f"  FN 샘플(작은 CA, dlog): {fn_samp}")
print(f"  (FP=잡것 617건은 V2서 측정, BT발동 0.4%로 무해 확인)")

# ③ 페널티 방향분해 BT (state base)
ar, days = {}, []
for f in sorted(glob.glob(os.path.join(PROJ, 'state', 'ranking_*.json'))):
    dt = os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt) == 8 and dt >= '20190102':
        ar[dt] = json.load(open(f, encoding='utf-8'))['rankings']; days.append(dt)
days = sorted(days); reg = calc_reg(days)
T = TurboSimulator({d: ar[d] for d in days}, days, prices, overheat_w=0.2); T._use_overlay = True; T._use_stored_growth = True
tks_by_d = {d: T._preextracted[d][0] for d in days}
fd_by_d = {d: {x['ticker']: x for x in ar[d]} for d in days}
base_ov = {d: np.array([0.2*(fd_by_d[d][tk].get('overheat_pen') or 0)+0.05*(fd_by_d[d][tk].get('mom_10_z') or 0)
                        +0.06*(fd_by_d[d][tk].get('vol_low_z') or 0) for tk in tks_by_d[d]]) for d in days}
def runbt(W, K, caby):
    for ii, d in enumerate(days):
        cut = days[max(0, ii-K)]; tks = tks_by_d[d]
        pen = np.array([(-W if (caby.get(tk) and any(cut < e <= d for e in caby[tk])) else 0.0) for tk in tks])
        T._overlay_pre[d] = base_ov[d] + pen
    T._cached_key = None
    T._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
    flat = list(T._cached_flat)
    r = _run_regime_inner(flat, flat, 0, 6, 3, 3, 6, 3, reg, days, T._price_arr, T._bench_arr, T._has_bench,
                          T._date_row_indices, len(days), None, None, None, None,
                          stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None)
    return r.get('calmar', 0)
print("\n=== ③ 페널티 방향분해 BT (W0.3 K126) ===")
c_both = runbt(0.3, 126, ca_raw)
c_down = runbt(0.3, 126, dn_caby)
c_up = runbt(0.3, 126, up_caby)
c_none = runbt(0.0, 126, ca_raw)
print(f"  W=0 (페널티없음)            : {c_none:.3f}")
print(f"  both 무상/분할/유상+병합(현행): {c_both:.3f}")
print(f"  down-only 무상/분할/유상     : {c_down:.3f}  (병합 제외)")
print(f"  up-only 병합만               : {c_up:.3f}")
print(f"\n→ 병합 기여 = both − down = {c_both-c_down:+.3f}  (≈0이면 병합 노이즈, 제거 가능)")
print(f"→ 하락CA 기여 = down − none = {c_down-c_none:+.3f}  (페널티 알파의 주력)")
