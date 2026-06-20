# -*- coding: utf-8 -*-
"""브레드스(시장 참여폭) 조기경보 게이트 검증 (2026-06-20 자율주행).
리서치 1순위 테마: 지수는 메가캡이 떠받쳐도 내부 참여폭은 먼저 무너진다(사용자 직감).
신호: b200=%종목>자기MA200, b50=%>MA50, HL=(신고가-신저가)/N (52주). 전부 보유 OHLCV로 계산.
테스트: baseline(MA20/80/5) 대비 — ①breadth 단독게이트 ②MA OR breadth조기방어 ③divergence(지수강세인데 breadth붕괴).
정직: Calmar/MDD/약세/현금일(휩쏘). 합격=MDD↓&Cal 비악화 or Cal↑."""
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
day_ts = pd.to_datetime([f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in days])

# ===== 브레드스 시계열 (캐시) =====
bcache = P + '/data_cache/_breadth_series.parquet'
if os.path.exists(bcache):
    B = pd.read_parquet(bcache)
    print(f"브레드스 캐시 로드 {B.shape}")
else:
    print("브레드스 계산 중(전종목 MA200/MA50/52주 신고가저가)...", flush=True)
    px = prices.copy()
    ma200 = px.rolling(200, min_periods=150).mean()
    ma50 = px.rolling(50, min_periods=40).mean()
    hi252 = px.rolling(252, min_periods=200).max()
    lo252 = px.rolling(252, min_periods=200).min()
    valid200 = ma200.notna() & px.notna()
    valid50 = ma50.notna() & px.notna()
    b200 = ((px > ma200) & valid200).sum(axis=1) / valid200.sum(axis=1).replace(0, np.nan)
    b50 = ((px > ma50) & valid50).sum(axis=1) / valid50.sum(axis=1).replace(0, np.nan)
    validhl = hi252.notna() & px.notna()
    nh = ((px >= hi252) & validhl).sum(axis=1)
    nl = ((px <= lo252) & validhl).sum(axis=1)
    n = validhl.sum(axis=1).replace(0, np.nan)
    hl = (nh - nl) / n
    B = pd.DataFrame({'b200': b200, 'b50': b50, 'hl': hl, 'nh': nh, 'nl': nl, 'n': n})
    B.to_parquet(bcache)
    print(f"브레드스 저장 {B.shape}")

def s_on_days(col):
    return B[col].reindex(day_ts)
b200 = s_on_days('b200'); b50 = s_on_days('b50'); hl = s_on_days('hl')

print(f"\n=== 현재 브레드스 (최근일 {days[-1]}) ===")
print(f"b200(%>MA200) {b200.iloc[-1]*100:.1f}% | b50 {b50.iloc[-1]*100:.1f}% | HL {hl.iloc[-1]*100:+.1f}%")
print(f"  과거 분포 b200: 평균 {b200.mean()*100:.0f}% / 약세장(2022) 최저 {b200['2022-01-01':'2023-06-01'].min()*100:.0f}%")

# ===== 게이트 빌더 =====
def ma_regime(sh_=20, lo_=80, cf=5):
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

def confirm(boolser, k):
    """bool 시계열을 k일 연속 확인 상태머신으로 (게이트 평활)."""
    reg = {}; md = True; stk = 0; ss = None
    for i, d in enumerate(days):
        v = boolser.iloc[i]
        s = bool(v) if not pd.isna(v) else ss
        if s is None: reg[d] = md; continue
        stk = stk + 1 if s == ss else 1; ss = s
        if stk >= k and md != s: md = s
        reg[d] = md
    return reg

def bt(reg, lo='20190102', hi='20260617'):
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
    cash = sum(1 for d in sub if not reg[d])
    return r.get('calmar', 0), r.get('cagr', 0), r.get('mdd', 0), cash

base = ma_regime()
def show(nm, reg):
    c = bt(reg); bb = bt(reg, '20220101', '20231231')
    print(f"{nm:<40}{c[0]:>7.3f}{c[1]:>7.1f}%{c[2]:>7.1f}%{c[3]:>6}일  약세 {bb[0]:>5.2f}/{bb[2]:.1f}%")

print(f"\n{'전략':<40}{'Calmar':>7}{'CAGR':>8}{'MDD':>7}{'현금':>6}  약세장 Cal/MDD")
print("-"*92)
show("baseline MA20/80/5", base)
print("--- A) breadth 단독 게이트 (b200>임계=boost, 5일확인) ---")
for X in [0.35, 0.40, 0.45, 0.50]:
    show(f"b200>{int(X*100)}% (5일확인) 단독", confirm(b200 > X, 5))
print("--- B) MA AND breadth (둘다 boost여야 boost = 조기방어) ---")
for X in [0.35, 0.40, 0.45]:
    reg = {d: base[d] and confirm(b200 > X, 5)[d] for d in days}
    show(f"MA boost AND b200>{int(X*100)}%", reg)
print("--- C) divergence: MA boost인데 b200 급락(MA20 of b200 하향)시 방어 ---")
b200ma = b200.rolling(20).mean()
for X in [0.40, 0.45]:
    div = (b200 < b200ma) & (b200 < X)  # breadth가 자기추세 아래 + 절대 약함
    reg = {d: base[d] and not confirm(div, 5)[d] for d in days}
    show(f"MA boost & NOT(b200<MA20(b200) & <{int(X*100)}%)", reg)
print("--- D) HL(신고가-신저가) 보조 ---")
for X in [-0.02, 0.0]:
    reg = {d: base[d] and confirm(hl > X, 5)[d] for d in days}
    show(f"MA boost AND HL>{X}", reg)
print("\n[판정] baseline(MDD 25.9%) 대비 MDD 줄이되 Calmar>3.9 유지 또는 개선이면 후속 정밀검증.")
