# -*- coding: utf-8 -*-
"""V1 워크포워드 (수정판): fold별 TurboSim 새로 빌드(=_penalty_robust 방식, 슬라이스 버그 회피).
fold1에서 W 선택 → fold2(OOS)에서 측정. 양방향 + 전체기간 대조."""
import sys, io, os, glob, json
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
ar_all, days = {}, []
for f in sorted(glob.glob(os.path.join(PROJ, 'state', 'ranking_*.json'))):
    dt = os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt) == 8 and dt >= '20190102':
        ar_all[dt] = json.load(open(f, encoding='utf-8'))['rankings']; days.append(dt)
days = sorted(days)
ca_by_tk = json.load(open(os.path.join(PROJ, 'data_cache', 'ca_events.json'), encoding='utf-8'))['ca_by_ticker']

def runbt(sub, W, K):
    reg = calc_reg(sub)
    t = TurboSimulator({d: ar_all[d] for d in sub}, sub, prices, overheat_w=0.2)
    t._use_overlay = True; t._use_stored_growth = True
    for ii, d in enumerate(sub):
        tks = t._preextracted[d][0]; fd = {x['ticker']: x for x in ar_all[d]}
        cut = sub[max(0, ii - K)]
        ov = np.empty(len(tks))
        for j, tk in enumerate(tks):
            x = fd[tk]
            base = 0.2*(x.get('overheat_pen') or 0) + 0.05*(x.get('mom_10_z') or 0) + 0.06*(x.get('vol_low_z') or 0)
            ds = ca_by_tk.get(tk)
            pen = -W if (W > 0 and ds and any(cut < e <= d for e in ds)) else 0.0
            ov[j] = base + pen
        t._overlay_pre[d] = ov
    t._cached_key = None
    t._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
    flat = list(t._cached_flat)
    r = _run_regime_inner(flat, flat, 0, 6, 3, 3, 6, 3, reg, sub, t._price_arr, t._bench_arr, t._has_bench,
                          t._date_row_indices, len(sub), None, None, None, None,
                          stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None)
    return r.get('calmar', 0)
Ws = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]; K = 126
f1 = [d for d in days if d <= '20221231']; f2 = [d for d in days if d >= '20230101']
print(f"fold1 {f1[0]}~{f1[-1]} ({len(f1)}일) | fold2 {f2[0]}~{f2[-1]} ({len(f2)}일), K={K}")

def pick(fold, name):
    print(f"\n[{name}] W 스윕:")
    best = (-9, None)
    res = {}
    for W in Ws:
        c = runbt(fold, W, K); res[W] = c
        if c > best[0]: best = (c, W)
        print(f"  W={W}: {c:.3f}"); sys.stdout.flush()
    print(f"  → 최적 W={best[1]} (Calmar {best[0]:.3f})")
    return best[1], res

# fold1 선택 → fold2 측정
w1, r1 = pick(f1, "fold1=2019-2022 선택")
c_oos = runbt(f2, w1, K); c_oos0 = runbt(f2, 0.0, K)
print(f"\n→ OOS fold2: fold1선택 W={w1} → Calmar {c_oos:.3f} vs W=0 {c_oos0:.3f} (페널티효과 {c_oos-c_oos0:+.3f})")
# 역방향: fold2 선택 → fold1 측정
w2, r2 = pick(f2, "fold2=2023-2026 선택")
c_oos_b = runbt(f1, w2, K); c_oos_b0 = runbt(f1, 0.0, K)
print(f"\n→ OOS fold1: fold2선택 W={w2} → Calmar {c_oos_b:.3f} vs W=0 {c_oos_b0:.3f} (페널티효과 {c_oos_b-c_oos_b0:+.3f})")
print(f"\n[요약] 배포값 W=0.3 각 fold: fold1 {r1[0.3]:.3f}(vs W0 {r1[0.0]:.3f}), fold2 {r2[0.3]:.3f}(vs W0 {r2[0.0]:.3f})")
