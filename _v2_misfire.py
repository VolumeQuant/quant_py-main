# -*- coding: utf-8 -*-
"""V2: 페널티 오발진 감사 — raw갭(production 999) vs genuine KRX-CA(839).
① 각 raw갭 이벤트를 genuine(adj/raw 비율점프 ±5일내)/잡것 분류 → 건수·종목수
② BT 페널티 발동(ticker-day) 중 잡것 기여 건수
③ genuine-only 트리거로 BT 재실행 → Calmar가 3.978서 움직이나"""
import sys, io, os, glob, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backtest'))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ = os.path.dirname(os.path.abspath(__file__))
DC = os.path.join(PROJ, 'data_cache')
prices = pd.read_parquet(sorted(glob.glob(os.path.join(DC, 'all_ohlcv_adj_*.parquet')))[-1]).replace(0, np.nan)
raw = pd.read_parquet(sorted(glob.glob(os.path.join(DC, 'all_ohlcv_2017*_2026*.parquet')))[-1]).replace(0, np.nan)
adj = pd.read_parquet(sorted(glob.glob(os.path.join(DC, 'adjusted_close_*.parquet')))[-1])
kc = pd.read_parquet(os.path.join(DC, 'kospi_yf.parquet')).iloc[:, 0]
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

ca_raw = json.load(open(os.path.join(DC, 'ca_events.json'), encoding='utf-8'))['ca_by_ticker']  # raw갭 999

# ① genuine 이벤트 (adj/raw 비율 점프 THR 0.02) — _ca_events.py와 동일
THR = 0.02
genuine = {}  # tk -> set(date_str)
for tk in adj.columns:
    if tk not in raw.columns:
        continue
    df = pd.DataFrame({'raw': raw[tk], 'adj': adj[tk].reindex(raw.index)}).dropna()
    if len(df) < 2:
        continue
    dlog = np.log(df['adj'] / df['raw']).diff()
    ds = set(d.strftime('%Y%m%d') for d, v in dlog.items() if np.isfinite(v) and abs(v) >= THR)
    if ds:
        genuine[tk] = ds

def near_genuine(tk, d, win=5):
    """tk의 genuine 이벤트가 d 기준 ±win 영업일내 있나."""
    gs = genuine.get(tk)
    if not gs:
        return False
    di = pd.Timestamp(d[:4] + '-' + d[4:6] + '-' + d[6:])
    for g in gs:
        gi = pd.Timestamp(g[:4] + '-' + g[4:6] + '-' + g[6:])
        if abs((di - gi).days) <= win * 1.6:  # 영업일~달력일 여유
            return True
    return False

# raw갭 이벤트 분류
tot_ev = gen_ev = junk_ev = 0
junk_by_tk = {}
gen_by_tk = {}
for tk, ds in ca_raw.items():
    for d in ds:
        tot_ev += 1
        if near_genuine(tk, d):
            gen_ev += 1; gen_by_tk.setdefault(tk, []).append(d)
        else:
            junk_ev += 1; junk_by_tk.setdefault(tk, []).append(d)
print("=== ① raw갭 이벤트 분류 ===")
print(f"raw갭 총 {tot_ev}건 / {len(ca_raw)}종목")
print(f"  genuine(KRX 보정 ±5일내) {gen_ev}건 / {len(gen_by_tk)}종목")
print(f"  잡것(보정無=거래정지/급락/오류) {junk_ev}건 / {len(junk_by_tk)}종목")
print(f"  adj fetch된 종목(genuine 후보 풀): {adj.shape[1]}")
# 잡것 샘플
print("  잡것 샘플:", [(tk, junk_by_tk[tk][:2]) for tk in list(junk_by_tk)[:5]])

# ② state 로드 + BT (full)
ar, days = {}, []
for f in sorted(glob.glob(os.path.join(PROJ, 'state', 'ranking_*.json'))):
    dt = os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt) == 8 and dt >= '20190102':
        ar[dt] = json.load(open(f, encoding='utf-8'))['rankings']; days.append(dt)
days = sorted(days)
genuine_caby = {tk: sorted(gen_by_tk.get(tk, [])) for tk in ca_raw}  # genuine raw갭 날짜만

def runbt(W, K, ca_map, count_junk=False):
    reg = calc_reg(days)
    t = TurboSimulator({d: ar[d] for d in days}, days, prices, overheat_w=0.2)
    t._use_overlay = True; t._use_stored_growth = True
    fire = junkfire = 0
    for ii, d in enumerate(days):
        tks = t._preextracted[d][0]; fd = {x['ticker']: x for x in ar[d]}
        cut = days[max(0, ii - K)]
        ov = np.empty(len(tks))
        for j, tk in enumerate(tks):
            x = fd[tk]
            base = 0.2*(x.get('overheat_pen') or 0) + 0.05*(x.get('mom_10_z') or 0) + 0.06*(x.get('vol_low_z') or 0)
            ds = ca_map.get(tk); pen = 0.0
            if W > 0 and ds and any(cut < e <= d for e in ds):
                pen = -W; fire += 1
                if count_junk:
                    js = junk_by_tk.get(tk)
                    # 발동을 일으킨 이벤트가 전부 잡것이고 genuine이 트리거창에 없으면 잡것발동
                    g_in = any(cut < e <= d for e in gen_by_tk.get(tk, []))
                    if not g_in:
                        junkfire += 1
            ov[j] = base + pen
        t._overlay_pre[d] = ov
    t._cached_key = None
    t._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
    flat = list(t._cached_flat)
    r = _run_regime_inner(flat, flat, 0, 6, 3, 3, 6, 3, reg, days, t._price_arr, t._bench_arr, t._has_bench,
                          t._date_row_indices, len(days), None, None, None, None,
                          stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None)
    return r.get('calmar', 0), fire, junkfire

print("\n=== ② BT 페널티 발동 중 잡것 기여 (W0.3 K126, raw갭 트리거) ===")
c_raw, fire, junkfire = runbt(0.3, 126, ca_raw, count_junk=True)
print(f"raw갭 트리거 BT: Calmar {c_raw:.3f}, 발동 {fire} 종목-일, 그중 잡것발동 {junkfire} ({junkfire/max(fire,1)*100:.1f}%)")

print("\n=== ③ genuine-only 트리거로 재실행 ===")
c_gen, fire_g, _ = runbt(0.3, 126, genuine_caby)
print(f"genuine 트리거 BT: Calmar {c_gen:.3f}, 발동 {fire_g} 종목-일")
print(f"\n[V2 판정] raw갭 {c_raw:.3f} vs genuine {c_gen:.3f} (차이 {c_raw-c_gen:+.3f}) → {'동일(raw갭 OK)' if abs(c_raw-c_gen)<=0.15 else '유의차'}")
