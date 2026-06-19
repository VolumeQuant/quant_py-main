# -*- coding: utf-8 -*-
"""국면지표 OOS 결판 (2026-06-19): 동일가중 우위가 OOS서 살아남나 + 메가캡 집중도 + 시스템유니버스 게이트.
핵심질문: 코스피가 메가캡에 쏠려 시스템 유니버스와 안 맞다면, 더 맞는 게이트(전종목EW/유니버스EW)가 OOS서 이기나?
방법(TTM 사가 규율): 고정 config(생산 20/80/5) + train기간 승자가 test기간서도 이기나(인샘플 과적합 판별)."""
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

# ===== 메가캡 집중도 실측 =====
mc = pd.read_parquet(sorted(glob.glob(P + '/data_cache/market_cap_ALL_*.parquet'))[-1])
cap = mc['시가총액'].astype(float)
top3 = ['005930', '000660', '402340']  # 삼성/하이닉스/SK스퀘어
t3 = cap.reindex(top3).sum(); tot = cap.sum()
print(f"=== 메가캡 집중도(최신 전체시장) ===")
print(f"삼성+하이닉스+SK스퀘어 시총합 {t3/1e12:.0f}조 / 전체 {tot/1e12:.0f}조 = {t3/tot*100:.1f}%")
for tk in top3:
    print(f"   {tk}: {cap.get(tk,0)/1e12:.1f}조 ({cap.get(tk,0)/tot*100:.1f}%)")
# 시총 상위10 (sanity)
print("   상위10 비중:", [f"{t}:{cap.get(t,0)/tot*100:.1f}%" for t in cap.sort_values(ascending=False).index[:10]])

# ===== 국면지표 3종 구성 =====
biz = prices[prices.notna().sum(axis=1) >= 100]
ew_all = (1 + biz.pct_change(fill_method=None).mean(axis=1)).cumprod()  # 전종목 동일가중
# 시스템 유니버스 동일가중: 각 날 ranking 종목들의 일평균수익 누적
uni_ret = pd.Series(0.0, index=pd.to_datetime([f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in days]))
pr_ret = prices.pct_change(fill_method=None)
for i, d in enumerate(days):
    ts = pd.Timestamp(f"{d[:4]}-{d[4:6]}-{d[6:]}")
    tks = [x['ticker'] for x in ar[d] if x['ticker'] in pr_ret.columns]
    if ts in pr_ret.index and tks:
        uni_ret.loc[ts] = pr_ret.loc[ts, tks].mean()
ew_uni = (1 + uni_ret).cumprod()

def reg_idx(idx, sh_, lo_, cf):
    s_ = idx.rolling(sh_).mean(); l_ = idx.rolling(lo_).mean()
    reg = {}; md = True; stk = 0; ss = None
    for d in days:
        ts = pd.Timestamp(d[:4] + '-' + d[4:6] + '-' + d[6:])
        sv = s_.get(ts, np.nan); lv = l_.get(ts, np.nan)
        if pd.isna(sv) or pd.isna(lv):
            reg[d] = md; continue
        s = bool(sv > lv); stk = stk + 1 if s == ss else 1; ss = s
        if stk >= cf and md != s: md = s
        reg[d] = md
    return reg

def bt(reg, sub):
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
    return r.get('calmar', 0)

idxs = [('코스피', kc), ('전종목EW', ew_all), ('유니버스EW', ew_uni)]
cfg = (20, 80, 5)
# 현재 신호
print(f"\n=== 현재 국면 신호 (config {cfg}) ===")
for nm, idx in idxs:
    reg = reg_idx(idx, *cfg); print(f"  {nm}: {'BOOST(공격)' if reg[days[-1]] else 'DEFENSE(방어)'}")

# OOS 결판: train→test 2가지 분할
splits = [('train19-22→test23-26', '20220101', '20221231'), ('train19-23→test24-26', '20240101', '99999999')]
print(f"\n=== OOS 결판 (고정 config {cfg}) — train승자가 test서도 이기나? ===")
for label, cut_lo, _ in [('19-22', '20190102', '20221231'), ('19-23', '20190102', '20231231')]:
    pass
def calmar_period(idx, lo, hi):
    sub = [d for d in days if lo <= d <= hi]
    return bt(reg_idx(idx, *cfg), sub)
for tr_lo, tr_hi, te_lo, te_hi, name in [
    ('20190102','20221231','20230101','20260617','분할A: train 19-22 / test 23-26'),
    ('20190102','20231231','20240101','20260617','분할B: train 19-23 / test 24-26')]:
    print(f"\n[{name}]")
    tr = {nm: calmar_period(idx, tr_lo, tr_hi) for nm, idx in idxs}
    te = {nm: calmar_period(idx, te_lo, te_hi) for nm, idx in idxs}
    tr_win = max(tr, key=tr.get); te_win = max(te, key=te.get)
    for nm in [n for n, _ in idxs]:
        print(f"   {nm:<9} train {tr[nm]:6.3f}  test {te[nm]:6.3f}")
    print(f"   → train 승자: {tr_win} / test 승자: {te_win}  {'★일관' if tr_win==te_win else '★역전(인샘플 과적합)'}")
    print(f"   → 코스피 대비 train최고 {tr_win}({tr[tr_win]:.3f}) 의 test: {te[tr_win]:.3f} vs 코스피 test {te['코스피']:.3f} = {te[tr_win]-te['코스피']:+.3f}")
