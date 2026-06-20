# -*- coding: utf-8 -*-
"""적대검증 (candidate: %below-MA50 breadth thrust + index RV expansion 결합):
이미 기각된 ①breadth 단독(%above-MA, Cal 0.43~1.14) ②McClellan ③변동성타겟팅과
'진짜 다른지' = breadth급락 AND index10d RV확장 의 AND 조건이 새 알파인지.
신호: %below-MA50 > thr (breadth악화) AND 5일변화 급증 AND index RV10 확장 → 강제 defense.
EDA(선행성) + 풀 production replay BT(baseline 못넘고 약세장 WF 깨지면 기각)."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices = pd.read_parquet(sorted(glob.glob(P + '/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan).sort_index()
kc = pd.read_parquet(P + '/data_cache/kospi_yf.parquet').iloc[:, 0].sort_index()
ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()

# ① breadth: %below-MA50 (candidate 정의 그대로). 영업일만.
biz = prices.dropna(how='all'); biz = biz[biz.notna().sum(axis=1) >= 100]
ma50 = biz.rolling(50, min_periods=50).mean()
below = ((biz < ma50) & biz.notna()).sum(axis=1) / biz.notna().sum(axis=1) * 100  # %below
below = below.dropna()
below5 = below.diff(5)  # 5일 breadth악화 속도 (+면 더 많은 종목이 MA아래로)

# index 10d realized vol (연율화) + 그 60일 백분위 (확장 판정)
kret = kc.pct_change()
rv10 = kret.rolling(10).std() * np.sqrt(252) * 100
rv10_pctl = rv10.rolling(252, min_periods=60).apply(lambda w: (w[-1] >= w).mean(), raw=True)  # 1년내 백분위

print(f"%below-MA50: {below.index[0].date()}~{below.index[-1].date()} {len(below)}일")
print(f"  분포: 평균{below.mean():.0f}% 중앙{below.median():.0f}% 상위10%(악화)={below.quantile(.9):.0f}% 상위25%={below.quantile(.75):.0f}%")
print(f"  최근: {[(str(d.date()),round(v)) for d,v in below.tail(4).items()]}")
print(f"  RV10 최근: {[(str(d.date()),round(v)) for d,v in rv10.dropna().tail(4).items()]}")

# ② EDA: 코스피 급락 직전 breadth/RV 선행성
kret20 = kc.pct_change(20)
print("\n[EDA] 코스피 20일 −10%↓ 급락 '직전(10일전)' breadth·RV (선행성 테스트):")
crash = kret20[kret20 < -0.10].index
for d in crash[::max(1, len(crash)//6)][:6]:
    bv = below[below.index <= d]; rv = rv10[rv10.index <= d]
    if len(bv) > 11 and len(rv) > 11:
        print(f"  {d.date()}: 코스피20d {kret20[d]*100:.0f}% | %below 당일{bv.iloc[-1]:.0f}% 10일전{bv.iloc[-11]:.0f}% | RV10 당일{rv.iloc[-1]:.0f} 10일전{rv.iloc[-11]:.0f}")

# ③ BT
G3 = ('rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)
ar, days = {}, []
for f in sorted(glob.glob(P + '/state/ranking_*.json')):
    d = os.path.basename(f)[8:16]
    if d.isdigit() and len(d) == 8 and d >= '20190102':
        ar[d] = json.load(open(f, encoding='utf-8'))['rankings']; days.append(d)
days = sorted(days)
belowd = {d.strftime('%Y%m%d'): v for d, v in below.items()}
below5d = {d.strftime('%Y%m%d'): v for d, v in below5.items()}
rvpctd = {d.strftime('%Y%m%d'): v for d, v in rv10_pctl.dropna().items()}

def make_reg(days, mode='base', bthr=None, b5thr=None, rvthr=None):
    reg = {}; md = True; stk = 0; ss = None
    for d in days:
        ts = pd.Timestamp(d[:4] + '-' + d[4:6] + '-' + d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts, np.nan)): reg[d] = md; continue
        s = bool(ma20[ts] > ma80[ts])
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= 5 and md != s: md = s
        r = md
        if mode == 'below_only' and belowd.get(d, 0) > (bthr or 60):
            r = False
        elif mode == 'combo':
            b_bad = belowd.get(d, 0) > (bthr or 55)
            b_fast = below5d.get(d, 0) > (b5thr or 8)
            rv_up = rvpctd.get(d, 0) > (rvthr or 0.7)
            if b_bad and b_fast and rv_up:
                r = False
        reg[d] = r
    return reg

def runbt(reg, sub):
    t = TurboSimulator({d: ar[d] for d in sub}, sub, prices, overheat_w=0.2)
    t._use_overlay = True; t._use_stored_growth = True
    for d in sub:
        tks = t._preextracted[d][0]; fd = {x['ticker']: x for x in ar[d]}
        t._overlay_pre[d] = np.array([0.2*(fd[tk].get('overheat_pen') or 0)+0.05*(fd[tk].get('mom_10_z') or 0)+0.06*(fd[tk].get('vol_low_z') or 0)-0.3*(fd[tk].get('recent_ca') or 0) for tk in tks])
    t._cached_key = None; t._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
    flat = list(t._cached_flat)
    r = _run_regime_inner(flat, flat, 0, 6, 3, 3, 6, 3, reg, sub, t._price_arr, t._bench_arr, t._has_bench, t._date_row_indices, len(sub), None, None, None, None, stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None)
    return r.get('calmar', 0), r.get('cagr', 0), r.get('mdd', 0)

def wf(reg):
    blocks = [('19-21', '20190102', '20211231'), ('22bear', '20220101', '20221231'),
              ('23-24', '20230101', '20241231'), ('25-26', '20250101', '20261231')]
    out = []
    for nm, a, b in blocks:
        sub = [d for d in days if a <= d <= b]
        if len(sub) > 60: c = runbt(reg, sub); out.append((nm, c[0]))
    return out

print(f"\n③ BT (현행 vs breadth+RV combo). baseline 못넘거나 약세장 WF 깨지면 기각:")
print(f"{'국면':<30}{'Calmar':>8}{'CAGR':>7}{'MDD':>7}{'def일%':>8}")
base = make_reg(days)
c = runbt(base, days); dfb = 100*sum(1 for d in days if not base[d])/len(days)
print(f"{'현행(코스피MA만)':<30}{c[0]:>8.3f}{c[1]:>6.0f}%{c[2]:>6.1f}%{dfb:>7.0f}%")
configs = [
    ('below_only', dict(bthr=60), '%below>60 단독(재확인)'),
    ('below_only', dict(bthr=70), '%below>70 단독(재확인)'),
    ('combo', dict(bthr=55, b5thr=8, rvthr=0.7), 'combo b55/Δ5>8/RVp70'),
    ('combo', dict(bthr=60, b5thr=10, rvthr=0.7), 'combo b60/Δ5>10/RVp70'),
    ('combo', dict(bthr=50, b5thr=6, rvthr=0.6), 'combo b50/Δ5>6/RVp60(느슨)'),
    ('combo', dict(bthr=65, b5thr=12, rvthr=0.8), 'combo b65/Δ5>12/RVp80(엄격)'),
]
results = {}
for mode, kw, lab in configs:
    rg = make_reg(days, mode, **kw); c = runbt(rg, days)
    df_ = 100*sum(1 for d in days if not rg[d])/len(days)
    print(f"{lab:<30}{c[0]:>8.3f}{c[1]:>6.0f}%{c[2]:>6.1f}%{df_:>7.0f}%")
    results[lab] = rg

print("\n[WF 연도별 Calmar] (약세장 22bear 깨지면 강세장 과적합):")
hdr = wf(base)
print(f"{'config':<30}" + ''.join(f"{nm:>9}" for nm,_ in hdr))
print(f"{'base':<30}" + ''.join(f"{v:>9.2f}" for _,v in hdr))
for lab in results:
    w = wf(results[lab])
    print(f"{lab:<30}" + ''.join(f"{v:>9.2f}" for _,v in w))
print("\n판정: combo가 baseline Calmar 초과(>noise 0.10) + MDD↓ + 약세장 WF 비악화면 backtest 추천. 아니면 reject.")
