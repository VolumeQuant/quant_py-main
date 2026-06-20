# -*- coding: utf-8 -*-
"""Two-of-two stress gate (적대적 검증, 2026-06-20).
후보: RV term-structure backwardation AND HY-spread widening 둘 다일 때만 강제 방어(현금).
주장: 두 독립 stress 채널 AND가 단일신호 휩쏘를 줄인다. user 기각: HY 단독=노이즈, RV 단독=(rvterm_test 참조).
정직 평가: baseline=현행 20/80/5. AND-gate가 MDD↓ & Calmar 비악화(>=4.0대)면 backtest 가치.
주의: hy_spread = US HY (FRED BAMLH0A0HYM2), 한국 신용 아님 — KOSPI 게이트에 쓰는 게 정당한지 결과로 판정."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices = pd.read_parquet(sorted(glob.glob(P + '/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
kc = pd.read_parquet(P + '/data_cache/kospi_yf.parquet').iloc[:, 0]
hy = pd.read_parquet(P + '/data_cache/hy_spread.parquet')['hy_spread']
G3 = ('rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)
ar, days = {}, []
for f in sorted(glob.glob(P + '/state/ranking_*.json')):
    d = os.path.basename(f)[8:16]
    if d.isdigit() and len(d) == 8 and d >= '20190102':
        ar[d] = json.load(open(f, encoding='utf-8'))['rankings']; days.append(d)
days = sorted(days)

lr = np.log(kc / kc.shift(1))
def rv(w): return lr.rolling(w).std() * np.sqrt(252)

# HY momentum: 20d change in HY spread, and its rolling quantile rank
hy_chg = hy - hy.shift(20)
hy_rank = hy_chg.rolling(252, min_periods=60).rank(pct=True)  # 1년창 백분위

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

def rv_hot(short_w, long_w, thr, confirm):
    """RV backwardation 확정 신호 dict."""
    ratio = rv(short_w) / rv(long_w)
    sig = {}; stk = 0
    for d in days:
        t = pd.Timestamp(d[:4] + '-' + d[4:6] + '-' + d[6:])
        v = ratio.get(t, np.nan)
        hot = (not pd.isna(v)) and (v > thr)
        stk = stk + 1 if hot else 0
        sig[d] = (stk >= confirm)
    return sig

def hy_hot(qthr):
    """HY 20d변화 > 0 AND 1년 백분위 > qthr 면 stress."""
    sig = {}
    for d in days:
        t = pd.Timestamp(d[:4] + '-' + d[4:6] + '-' + d[6:])
        # asof: HY는 영업일/달력 다름 → 직전값 사용
        try:
            chg = hy_chg.asof(t); rk = hy_rank.asof(t)
        except Exception:
            chg = np.nan; rk = np.nan
        sig[d] = (not pd.isna(chg)) and (not pd.isna(rk)) and (chg > 0) and (rk > qthr)
    return sig

def and_overlay(base_reg, sigA, sigB):
    """base boost라도 (sigA AND sigB) stress 확정이면 강제 현금."""
    return {d: base_reg[d] and not (sigA[d] and sigB[d]) for d in days}

def or_overlay(base_reg, sigA, sigB):
    return {d: base_reg[d] and not (sigA[d] or sigB[d]) for d in days}

def runbt(reg, lo=None, hi=None):
    sub = [d for d in days if (lo is None or d >= lo) and (hi is None or d <= hi)]
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
    cash = sum(1 for d in sub if not reg[d])
    return r.get('calmar', 0), r.get('cagr', 0)*100, r.get('mdd', 0)*100, cash

base = ma_regime(20, 80, 5)
print(f"{'전략':<40}{'Calmar':>8}{'CAGR':>7}{'MDD':>7}{'현금일':>7}{'약세22-23 Cal/MDD':>20}")
print("-"*92)
def show(nm, reg):
    c = runbt(reg); b = runbt(reg, '20220101', '20231231')
    fire = sum(1 for d in days if base[d] and not reg[d])  # AND-gate가 추가로 끈 일수
    print(f"{nm:<40}{c[0]:>8.3f}{c[1]:>6.0f}%{c[2]:>6.1f}%{c[3]:>6}일   {b[0]:>6.2f} / {b[2]:.1f}%  (+{fire}끔)")

show("baseline 20/80/5(현행)", base)
print("--- 단일채널 참고 (둘 다 user가 노이즈/약 판정한 것 재확인) ---")
show("HY only (chg>0 & q>0.8)", or_overlay(base, hy_hot(0.8), {d: False for d in days}))
show("RV only (5/60>1.6 2d)", or_overlay(base, rv_hot(5,60,1.6,2), {d: False for d in days}))
print("--- AND-gate: RV backwardation AND HY widening 둘 다 ---")
for (sw,lw,thr,cf) in [(5,60,1.5,2),(5,60,1.6,2),(10,60,1.4,2)]:
    for q in [0.7, 0.8]:
        show(f"AND RV{sw}/{lw}>{thr}/{cf}d & HYq>{q}", and_overlay(base, rv_hot(sw,lw,thr,cf), hy_hot(q)))
print("\n[판정] AND-gate가 baseline MDD↓ & Calmar 비악화면 backtest. 거의 안 켜지거나(0~5일) Calmar↓면 reject.")
