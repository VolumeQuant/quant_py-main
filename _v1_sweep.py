# -*- coding: utf-8 -*-
"""V1: 최근 CA 페널티 파라미터 강건성 — 확장 그리드 + 워크포워드.
base = production state/ (수정주가 z-score, 페널티는 점수에만 baked→TurboSim이 z서 재계산하므로 V_all과 동일).
트리거: production과 동일하게 ca_events.json['ca_by_ticker'](raw갭 999종목).
sanity: W=0→~2.76(정직), W0.3/K126(저장flag)→~3.98 재현, 재유도트리거 vs 저장flag 일치 확인.
그리드: W{0,.1,.2,.3,.4,.5,.6,.7} × K{63,126,189} → 3.98이 고원인지(이웃 ±0.3).
WF: fold1(2019-2022) W선택 → fold2(2023-2026) 측정."""
import sys, io, os, glob, json, bisect
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backtest'))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ = os.path.dirname(os.path.abspath(__file__))
prices = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ, 'data_cache', 'all_ohlcv_adj_*.parquet')))[-1]).replace(0, np.nan)
kc = pd.read_parquet(os.path.join(PROJ, 'data_cache', 'kospi_yf.parquet')).iloc[:, 0]
ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()
G3 = ('rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)

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

# --- 한 번만 로드 ---
ar, days = {}, []
for f in sorted(glob.glob(os.path.join(PROJ, 'state', 'ranking_*.json'))):
    dt = os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt) == 8 and dt >= '20190102':
        ar[dt] = json.load(open(f, encoding='utf-8'))['rankings']; days.append(dt)
days = sorted(days)
ca_by_tk = json.load(open(os.path.join(PROJ, 'data_cache', 'ca_events.json'), encoding='utf-8'))['ca_by_ticker']
print(f"state 로드 {len(days)}일 ({days[0]}~{days[-1]}), ca_by_ticker {len(ca_by_tk)}종목 (raw갭)")

# TurboSim 한 번만 빌드 (전체 기간)
fd_by_d = {d: {x['ticker']: x for x in ar[d]} for d in days}
base_ov = {}  # overheat+mom+vol (W무관 고정분)
for d in days:
    tks = None
T_full = TurboSimulator(ar, days, prices, overheat_w=0.2); T_full._use_overlay = True; T_full._use_stored_growth = True
tks_by_d = {d: T_full._preextracted[d][0] for d in days}
for d in days:
    fd = fd_by_d[d]
    base_ov[d] = np.array([0.2*(fd[tk].get('overheat_pen') or 0) + 0.05*(fd[tk].get('mom_10_z') or 0)
                           + 0.06*(fd[tk].get('vol_low_z') or 0) for tk in tks_by_d[d]])

# 트리거 행렬: stored flag, 그리고 K별 재유도(ca_by_ticker)
stored_rc = {d: np.array([1.0 if (fd_by_d[d][tk].get('recent_ca') or 0) else 0.0 for tk in tks_by_d[d]]) for d in days}
def derive_rc(K):
    """K영업일내 CA 트리거 재유도 (production: _cut<e<=base)."""
    out = {}
    for ii, d in enumerate(days):
        cut = days[max(0, ii - K)]
        tks = tks_by_d[d]
        arr = np.zeros(len(tks))
        for j, tk in enumerate(tks):
            ds = ca_by_tk.get(tk)
            if ds and any(cut < e <= d for e in ds):
                arr[j] = 1.0
        out[d] = arr
    return out

def runbt(sub, W, rc_map):
    reg = calc_reg(sub)
    for d in sub:
        T_full._overlay_pre[d] = base_ov[d] - W * rc_map[d]
    T_full._cached_key = None
    T_full._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
    flat = list(T_full._cached_flat)
    flat_sub = [flat[days.index(d)] for d in sub] if sub is not days else flat
    r = _run_regime_inner(flat_sub, flat_sub, 0, 6, 3, 3, 6, 3, reg, sub, T_full._price_arr, T_full._bench_arr,
                          T_full._has_bench, T_full._date_row_indices, len(sub), None, None, None, None,
                          stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None)
    return r.get('calmar', 0), r.get('cagr', 0), r.get('mdd', 0)

# ===== SANITY =====
print("\n=== SANITY ===")
c0 = runbt(days, 0.0, stored_rc); print(f"W=0 (정직 V_all)            : Calmar {c0[0]:.3f}  (기대 ~2.76)")
cs = runbt(days, 0.3, stored_rc); print(f"W=0.3 K126 (저장 recent_ca) : Calmar {cs[0]:.3f}  (기대 ~3.98)")
rc126 = derive_rc(126)
cd = runbt(days, 0.3, rc126);     print(f"W=0.3 K126 (재유도 ca_by_tk): Calmar {cd[0]:.3f}  (저장flag와 일치해야)")
# 트리거 일치율
ns = sum(int(stored_rc[d].sum()) for d in days); nd = sum(int(rc126[d].sum()) for d in days)
match = sum(int(np.sum((stored_rc[d] > 0) == (rc126[d] > 0))) for d in days); tot = sum(len(stored_rc[d]) for d in days)
print(f"트리거 발동: 저장 {ns} 종목-일 / 재유도K126 {nd} / 일치율 {match/tot*100:.2f}%")
sys.stdout.flush()

# ===== V1 그리드 =====
print("\n=== V1 그리드 (Calmar, dir=all, 트리거=ca_by_ticker raw갭) ===")
Ws = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]
Ks = [63, 126, 189]
rc_cache = {K: derive_rc(K) for K in Ks}
grid = {}
hdr = "  W\\K  " + "".join(f"{K:>9}" for K in Ks)
print(hdr)
for W in Ws:
    row = f"{W:>5} "
    for K in Ks:
        c = runbt(days, W, rc_cache[K])[0]; grid[(W, K)] = c
        row += f"{c:>9.3f}"
    print(row); sys.stdout.flush()

# 고원 판정: W0.3/K126 이웃 ±0.3
peak = grid[(0.3, 126)]
neigh = [grid[(w, k)] for w in [0.2, 0.3, 0.4] for k in [63, 126, 189] if (w, k) != (0.3, 126)]
print(f"\nW0.3/K126={peak:.3f}, 이웃8칸 min={min(neigh):.3f} max={max(neigh):.3f}, 최대편차={max(abs(peak-x) for x in neigh):.3f}")
print(f"→ 고원 판정(이웃 모두 ±0.3 안): {'PASS' if max(abs(peak-x) for x in neigh) <= 0.3 else 'FAIL(절벽=오버핏 의심)'}")

# ===== 워크포워드 =====
print("\n=== 워크포워드 (fold1 W선택 → fold2 측정, K=126) ===")
f1 = [d for d in days if d <= '20221231']; f2 = [d for d in days if d >= '20230101']
print(f"fold1 {f1[0]}~{f1[-1]} ({len(f1)}일), fold2 {f2[0]}~{f2[-1]} ({len(f2)}일)")
rc126_full = rc_cache[126]
best_w, best_c = None, -1
for W in Ws:
    c = runbt(f1, W, rc126_full)[0]
    if c > best_c: best_c, best_w = c, W
    print(f"  fold1 W={W}: Calmar {c:.3f}")
print(f"→ fold1 최적 W={best_w} (Calmar {best_c:.3f})")
c_oos = runbt(f2, best_w, rc126_full)
c_oos0 = runbt(f2, 0.0, rc126_full)
print(f"→ fold2(OOS) W={best_w}: Calmar {c_oos[0]:.3f} vs W=0 {c_oos0[0]:.3f} (페널티효과 {c_oos[0]-c_oos0[0]:+.3f})")
