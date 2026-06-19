# -*- coding: utf-8 -*-
"""방어신호 연구: 코스피 국면(mega-cap 착시)을 breadth로 보완.
①7.4년 daily breadth(MA120 위 %) 계산 ②과거 폭락 때 breadth 선행성 EDA
③breadth<임계 → defense 추가한 국면 vs 현행(코스피만) BT 비교(Calmar/MDD/WF)."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices = pd.read_parquet(sorted(glob.glob(P + '/data_cache/all_ohlcv_adj_*.parquet')))[-1] if False else pd.read_parquet(sorted(glob.glob(P + '/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
kc = pd.read_parquet(P + '/data_cache/kospi_yf.parquet').iloc[:, 0]
ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()

# ① breadth: 각 거래일 MA120 위 종목 비율 (영업일만)
biz = prices.dropna(how='all')
biz = biz[biz.notna().sum(axis=1) >= 100]  # 영업일(>=100종목 가격)
ma120 = biz.rolling(120, min_periods=120).mean()
breadth = ((biz >= ma120) & biz.notna()).sum(axis=1) / biz.notna().sum(axis=1) * 100
breadth = breadth.dropna()
print(f"breadth 계산: {breadth.index[0].date()}~{breadth.index[-1].date()} {len(breadth)}일")
print(f"  최근: {[(str(d.date()),round(v)) for d,v in breadth.tail(5).items()]}")
print(f"  분포: 평균{breadth.mean():.0f}% 중앙{breadth.median():.0f}% 하위10%={breadth.quantile(.1):.0f}% 하위25%={breadth.quantile(.25):.0f}%")

# ② 과거 코스피 낙폭 구간에서 breadth 선행성
kret = kc.pct_change(20)  # 20일 코스피 수익
print("\n[EDA] 코스피 20일 −10%↓ 급락일들의 직전 breadth:")
crash = kret[kret < -0.10].index
for d in crash[::max(1, len(crash)//6)][:6]:
    bv = breadth[breadth.index <= d]
    if len(bv): print(f"  {d.date()}: 코스피20d {kret[d]*100:.0f}% | 그날 breadth {bv.iloc[-1]:.0f}% | 20일전 breadth {bv.iloc[-21] if len(bv)>21 else float('nan'):.0f}%")

# ③ BT: 현행(코스피) vs 코스피+breadth<X defense
G3 = ('rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)
ar, days = {}, []
for f in sorted(glob.glob(P + '/state/ranking_*.json')):
    d = os.path.basename(f)[8:16]
    if d.isdigit() and len(d) == 8 and d >= '20190102': ar[d] = json.load(open(f, encoding='utf-8'))['rankings']; days.append(d)
days = sorted(days)
brd = {d.strftime('%Y%m%d'): v for d, v in breadth.items()}
def make_reg(days, breadth_thresh=None):
    reg = {}; md = True; stk = 0; ss = None
    for d in days:
        ts = pd.Timestamp(d[:4] + '-' + d[4:6] + '-' + d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts, np.nan)): reg[d] = md; continue
        s = bool(ma20[ts] > ma80[ts])
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= 5 and md != s: md = s
        r = md
        if breadth_thresh is not None and brd.get(d, 100) < breadth_thresh:
            r = False  # breadth 낮으면 강제 defense
        reg[d] = r
    return reg
def runbt(reg, sub):
    t = TurboSimulator({d: ar[d] for d in sub}, sub, prices, overheat_w=0.2); t._use_overlay = True; t._use_stored_growth = True
    for d in sub:
        tks = t._preextracted[d][0]; fd = {x['ticker']: x for x in ar[d]}
        t._overlay_pre[d] = np.array([0.2*(fd[tk].get('overheat_pen') or 0)+0.05*(fd[tk].get('mom_10_z') or 0)+0.06*(fd[tk].get('vol_low_z') or 0)-0.3*(fd[tk].get('recent_ca') or 0) for tk in tks])
    t._cached_key = None; t._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
    flat = list(t._cached_flat)
    r = _run_regime_inner(flat, flat, 0, 6, 3, 3, 6, 3, reg, sub, t._price_arr, t._bench_arr, t._has_bench, t._date_row_indices, len(sub), None, None, None, None, stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None)
    return r.get('calmar', 0), r.get('cagr', 0), r.get('mdd', 0)
print(f"\n③ BT (현행 코스피국면 vs +breadth defense):")
print(f"{'국면':<24}{'Calmar':>8}{'CAGR':>7}{'MDD':>7}{'defense일%':>10}")
base = make_reg(days)
c = runbt(base, days); dfrac = 100*sum(1 for d in days if not base[d])/len(days)
print(f"{'현행(코스피만)':<24}{c[0]:>8.3f}{c[1]:>6.0f}%{c[2]:>6.1f}%{dfrac:>9.0f}%")
for X in [15, 20, 25, 30]:
    rg = make_reg(days, X); c = runbt(rg, days); dfrac = 100*sum(1 for d in days if not rg[d])/len(days)
    print(f"{'+breadth<'+str(X)+'% defense':<24}{c[0]:>8.3f}{c[1]:>6.0f}%{c[2]:>6.1f}%{dfrac:>9.0f}%")
print("\n→ breadth defense가 Calmar↑·MDD↓면 채택 검토. CAGR만 깎고 MDD 그대로면 기각.")
