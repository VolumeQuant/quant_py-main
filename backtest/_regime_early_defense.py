# -*- coding: utf-8 -*-
"""조기방어 정면검증 (2026-06-20, 사용자 "후행신호 -23%는 방어 아님, 더 일찍 피해라").
질문: 더 일찍 방어하는 신호가 MDD를 줄이되 수익(Calmar)을 안 죽이나?
테스트 A) 빠른 MA크로스  B) 드로다운 서킷브레이커(고점대비 -X% 즉시 현금)  C) 조합.
정직: 보호이득 vs 휩쏘비용 둘 다 측정. baseline=현행 20/80/5."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices = pd.read_parquet(sorted(glob.glob(P + '/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
kc = pd.read_parquet(P + '/data_cache/kospi_yf.parquet').iloc[:, 0]
G3 = ('rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)
ar, days = {}, []
for f in sorted(glob.glob(P + '/state/ranking_*.json')):
    d = os.path.basename(f)[8:16]
    if d.isdigit() and len(d) == 8 and d >= '20190102':
        ar[d] = json.load(open(f, encoding='utf-8'))['rankings']; days.append(d)
days = sorted(days)
dd_series = kc / kc.cummax() - 1  # 고점대비 낙폭 (게이트 지수)

def ma_regime(sh_, lo_, cf):
    s_ = kc.rolling(sh_).mean(); l_ = kc.rolling(lo_).mean()
    reg = {}; md = True; stk = 0; ss = None
    for d in days:
        ts = pd.Timestamp(d[:4] + '-' + d[4:6] + '-' + d[6:])
        sv = s_.get(ts, np.nan); lv = l_.get(ts, np.nan)
        if pd.isna(sv) or pd.isna(lv): reg[d] = md; continue
        s = bool(sv > lv); stk = stk + 1 if s == ss else 1; ss = s
        if stk >= cf and md != s: md = s
        reg[d] = md
    return reg

def with_breaker(base_reg, X):
    """base boost라도 고점대비 -X% 미만이면 강제 방어(현금)."""
    out = {}
    for d in days:
        ts = pd.Timestamp(d[:4] + '-' + d[4:6] + '-' + d[6:])
        ddv = dd_series.get(ts, 0)
        out[d] = base_reg[d] and (ddv >= -X)
    return out

def bt(reg):
    sub = days
    t = TurboSimulator({d: ar[d] for d in sub}, sub, prices, overheat_w=0.2)
    t._use_overlay = True; t._use_stored_growth = True
    for d in sub:
        tks = t._preextracted[d][0]; fd = {x['ticker']: x for x in ar[d]}
        t._overlay_pre[d] = np.array([0.2*(fd[tk].get('overheat_pen') or 0)+0.05*(fd[tk].get('mom_10_z') or 0)
                                      +0.06*(fd[tk].get('vol_low_z') or 0)-0.3*(fd[tk].get('recent_ca') or 0) for tk in tks])
    t._cached_key = None; t._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
    flat = list(t._cached_flat)
    r = _run_regime_inner(flat, flat, 0, 6, 3, 3, 6, 3, reg, sub, t._price_arr, t._bench_arr, t._has_bench,
                          t._date_row_indices, len(sub), None, None, None, None,
                          stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None)
    # 방어일수(현금일수)
    cashdays = sum(1 for d in sub if not reg[d])
    return r.get('calmar', 0), r.get('cagr', 0)*100, r.get('mdd', 0)*100, cashdays

def bt_block(reg, lo, hi):
    sub = [d for d in days if lo <= d <= hi]
    t = TurboSimulator({d: ar[d] for d in sub}, sub, prices, overheat_w=0.2)
    t._use_overlay = True; t._use_stored_growth = True
    for d in sub:
        tks = t._preextracted[d][0]; fd = {x['ticker']: x for x in ar[d]}
        t._overlay_pre[d] = np.array([0.2*(fd[tk].get('overheat_pen') or 0)+0.05*(fd[tk].get('mom_10_z') or 0)
                                      +0.06*(fd[tk].get('vol_low_z') or 0)-0.3*(fd[tk].get('recent_ca') or 0) for tk in tks])
    t._cached_key = None; t._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
    flat = list(t._cached_flat)
    r = _run_regime_inner(flat, flat, 0, 6, 3, 3, 6, 3, reg, sub, t._price_arr, t._bench_arr, t._has_bench,
                          t._date_row_indices, len(sub), None, None, None, None,
                          stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None)
    return r.get('calmar', 0), r.get('mdd', 0)*100

base = ma_regime(20, 80, 5)
print(f"{'전략':<28}{'Calmar':>8}{'CAGR':>7}{'MDD':>7}{'현금일':>7}{'약세22-23 Cal/MDD':>18}")
print("-"*78)
def show(nm, reg):
    c = bt(reg); bb = bt_block(reg, '20220101', '20231231')
    print(f"{nm:<28}{c[0]:>8.3f}{c[1]:>6.0f}%{c[2]:>6.1f}%{c[3]:>6}일   {bb[0]:>6.2f} / {bb[1]:.1f}%")
show("baseline 20/80/5(현행)", base)
print("--- A) 빠른 MA크로스 ---")
for s, l, cf in [(10, 40, 3), (5, 20, 2), (10, 30, 3), (15, 60, 5)]:
    show(f"MA {s}/{l}/{cf}d", ma_regime(s, l, cf))
print("--- B) 드로다운 서킷브레이커(현행 MA + 고점대비 -X% 강제현금) ---")
for X in [0.06, 0.08, 0.10, 0.12, 0.15]:
    show(f"20/80/5 + dd<-{int(X*100)}% 현금", with_breaker(base, X))
print("--- C) 빠른MA + 드로다운 조합 ---")
for (s, l, cf), X in [((10, 40, 3), 0.10), ((10, 40, 3), 0.08)]:
    show(f"MA {s}/{l}/{cf} + dd<-{int(X*100)}%", with_breaker(ma_regime(s, l, cf), X))
print("\n[판정] baseline 대비 MDD↓ & Calmar 비악화면 조기방어 채택. Calmar 무너지면 휩쏘비용>보호이득=기각.")
