# -*- coding: utf-8 -*-
"""국면 게이트: 코스피종합 vs 코스피200(1028) vs 코스닥150(2203) — 실제 지수로 OOS 결판 (2026-06-19).
사용자 요청. 현재전략=코스피종합 MA20/80/5d. KOSPI200/KOSDAQ150이 더 나은가?"""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, P)
# 1) 지수 fetch (캐시 있으면 재사용)
import krx_auth; krx_auth.login()
from pykrx import stock
def get_idx(code, name):
    fp = os.path.join(P, 'data_cache', f'index_{name}.parquet')
    if os.path.exists(fp):
        return pd.read_parquet(fp).iloc[:, 0]
    df = stock.get_index_ohlcv_by_date('20170101', '20260619', code)
    s = df['종가'].replace(0, np.nan); s.index = pd.to_datetime(s.index)
    s.to_frame('close').to_parquet(fp)
    return s
kc = pd.read_parquet(P + '/data_cache/kospi_yf.parquet').iloc[:, 0]
k200 = get_idx('1028', 'kospi200')
kq150 = get_idx('2203', 'kosdaq150')
print(f"코스피종합 {len(kc)}행 | 코스피200 {len(k200)}행 | 코스닥150 {len(kq150)}행")

prices = pd.read_parquet(sorted(glob.glob(P + '/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
from turbo_simulator import TurboSimulator, _run_regime_inner
G3 = ('rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)
ar, days = {}, []
for f in sorted(glob.glob(P + '/state/ranking_*.json')):
    d = os.path.basename(f)[8:16]
    if d.isdigit() and len(d) == 8 and d >= '20190102':
        ar[d] = json.load(open(f, encoding='utf-8'))['rankings']; days.append(d)
days = sorted(days)

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

idxs = [('코스피종합(현행)', kc), ('코스피200', k200), ('코스닥150', kq150)]
cfg = (20, 80, 5)
print(f"\n=== 현재 신호 (MA20/80/5d) ===")
for nm, idx in idxs:
    print(f"  {nm}: {'BOOST(공격)' if reg_idx(idx,*cfg)[days[-1]] else 'DEFENSE(방어)'}")

def cp(idx, lo, hi):
    return bt(reg_idx(idx, *cfg), [d for d in days if lo <= d <= hi])
print(f"\n=== full-period Calmar (config {cfg}) ===")
for nm, idx in idxs:
    print(f"  {nm}: {cp(idx,'20190102','20260617'):.3f}")
print(f"\n=== OOS 결판: train 승자가 test서도 이기나 ===")
for tr_lo, tr_hi, te_lo, te_hi, name in [
    ('20190102','20221231','20230101','20260617','train 19-22 / test 23-26'),
    ('20190102','20231231','20240101','20260617','train 19-23 / test 24-26')]:
    tr = {nm: cp(idx, tr_lo, tr_hi) for nm, idx in idxs}
    te = {nm: cp(idx, te_lo, te_hi) for nm, idx in idxs}
    print(f"\n[{name}]")
    for nm, _ in idxs:
        print(f"   {nm:<14} train {tr[nm]:6.3f}  test {te[nm]:6.3f}")
    print(f"   → train승자 {max(tr,key=tr.get)} / test승자 {max(te,key=te.get)}")
