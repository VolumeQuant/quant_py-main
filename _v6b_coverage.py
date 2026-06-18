# -*- coding: utf-8 -*-
"""차단6 정밀: 진짜 CA(|dlog|≥0.15, 배당노이즈 제외)만 혼동행렬 + 임계민감도.
FN = 진짜 CA인데 raw move <33%/45%라 페널티 못잡음. 임계민감도 = 트리거 임계 낮추면 Calmar 변하나."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backtest'))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ = os.path.dirname(os.path.abspath(__file__)); DC = os.path.join(PROJ, 'data_cache')
prices = pd.read_parquet(sorted(glob.glob(os.path.join(DC, 'all_ohlcv_adj_*.parquet')))[-1]).replace(0, np.nan)
raw = pd.read_parquet(sorted(glob.glob(os.path.join(DC, 'all_ohlcv_2017*_2026*.parquet')))[-1]).replace(0, np.nan)
adj = pd.read_parquet(sorted(glob.glob(os.path.join(DC, 'adjusted_close_*.parquet')))[-1])
rawret = raw.pct_change(fill_method=None)

# 진짜 CA 이벤트 (|dlog|≥0.15), 방향 + caught 여부
CA_THR = 0.15
buckets = {'caught': 0, 'missed': 0}
ca_genuine = {}  # tk -> [(date, dlog, down/up, caught)]
for tk in adj.columns:
    if tk not in raw.columns: continue
    df = pd.DataFrame({'raw': raw[tk], 'adj': adj[tk].reindex(raw.index)}).dropna()
    if len(df) < 2: continue
    dlog = np.log(df['adj']/df['raw']).diff()
    for dt, v in dlog.items():
        if not (np.isfinite(v) and abs(v) >= CA_THR): continue
        loc = raw.index.get_loc(dt)
        seg = rawret[tk].iloc[max(0, loc-2):loc+3]
        caught = bool(((seg < -0.33) | (seg > 0.45)).any())
        buckets['caught' if caught else 'missed'] += 1
        ca_genuine.setdefault(tk, []).append((dt.strftime('%Y%m%d'), float(v), 'down' if v > 0 else 'up', caught))
tot = buckets['caught'] + buckets['missed']
print(f"=== 진짜 CA(|dlog|≥{CA_THR}) 혼동행렬 ===")
print(f"  진짜 CA {tot}건 | caught(raw갭 발동) {buckets['caught']} | missed(FN) {buckets['missed']}")
print(f"  → 커버리지 {buckets['caught']/tot*100:.1f}%, FN {buckets['missed']/tot*100:.1f}%")
# missed의 dlog 분포 (작은 CA여야)
missed_dl = [abs(v) for tk in ca_genuine for (_, v, _, c) in ca_genuine[tk] if not c]
caught_dl = [abs(v) for tk in ca_genuine for (_, v, _, c) in ca_genuine[tk] if c]
print(f"  missed dlog 중앙값 {np.median(missed_dl):.2f}(작은CA) vs caught 중앙값 {np.median(caught_dl):.2f}")

# 임계민감도: down-CA 트리거를 dlog 임계별로 만들어 BT
def caby_from(thr, direction='down'):
    out = {}
    for tk in adj.columns:
        if tk not in raw.columns: continue
        df = pd.DataFrame({'raw': raw[tk], 'adj': adj[tk].reindex(raw.index)}).dropna()
        if len(df) < 2: continue
        dlog = np.log(df['adj']/df['raw']).diff()
        ds = [dt.strftime('%Y%m%d') for dt, v in dlog.items()
              if np.isfinite(v) and abs(v) >= thr and ((v > 0) if direction == 'down' else (v < 0))]
        if ds: out[tk] = sorted(ds)
    return out

ar, days = {}, []
for f in sorted(glob.glob(os.path.join(PROJ, 'state', 'ranking_*.json'))):
    dt = os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt) == 8 and dt >= '20190102':
        ar[dt] = json.load(open(f, encoding='utf-8'))['rankings']; days.append(dt)
days = sorted(days)
kc = pd.read_parquet(os.path.join(DC, 'kospi_yf.parquet')).iloc[:, 0]
ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()
def calc_reg(ds):
    reg = {}; md = True; stk = 0; ss = None
    for d in ds:
        ts = pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts, np.nan)): reg[d] = md; continue
        s = bool(ma20[ts] > ma80[ts]); stk = stk+1 if s == ss else 1; ss = s
        if stk >= 5 and md != s: md = s
        reg[d] = md
    return reg
reg = calc_reg(days)
G3 = ('rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)
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
                          T._date_row_indices, len(days), None, None, None, None, stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None)
    return r.get('calmar', 0)
print("\n=== 임계민감도 (down-CA 트리거, dlog 임계 낮추면 커버리지↑) W0.3 K126 ===")
for thr in [0.10, 0.15, 0.25, 0.40]:
    cb = caby_from(thr, 'down'); ntrig = sum(len(v) for v in cb.values())
    print(f"  dlog≥{thr}: 트리거 {ntrig}건/{len(cb)}종목 → Calmar {runbt(0.3,126,cb):.3f}")
print("  (raw갭 기준 production=3.978, down-only=4.050)")
print("→ 임계 낮춰 커버리지 키워도 Calmar 비슷하면 33/45 임계에 둔감 = robust")
