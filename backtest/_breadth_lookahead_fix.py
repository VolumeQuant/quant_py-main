# -*- coding: utf-8 -*-
"""브레드스 스케일 look-ahead 재측정 (2026-07-31, US 핸드오프 지적 검증).

지적: variant()가 bdef[i](=d0 종가로 판정한 브레드스 상태)를 rets[i](=d-1→d0 수익)에
      곱한다 → d0 종가 정보를 d0 수익 사이징에 사용 = look-ahead.
수정: rets[i]에는 bdef[i-1](d-1 종가로 알 수 있던 상태)을 적용해야 한다.
"베이스 무영향 확인": 포트폴리오 선택 경로는 브레드스와 무관하므로 rets는 동일, 스케일만 다름.
"""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices = pd.read_parquet(sorted(glob.glob(P + '/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
kc = pd.read_parquet(P + '/data_cache/kospi_yf.parquet').iloc[:, 0]
sec = pd.read_parquet(sorted(glob.glob(P + '/data_cache/krx_sector_*.parquet'))[-1])
sec = sec.rename(columns={sec.columns[0]: 'ticker', sec.columns[1]: 'sector'})
G3 = ('rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)
ar, days = {}, []
for f in sorted(glob.glob(P + '/state/ranking_*.json')):
    d = os.path.basename(f)[8:16]
    if d.isdigit() and len(d) == 8 and d >= '20190102':
        ar[d] = json.load(open(f, encoding='utf-8'))['rankings']; days.append(d)
days = sorted(days)
dts = pd.to_datetime([f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in days])
ret = prices.pct_change(fill_method=None)
idx = {}
for s, g in sec.groupby('sector')['ticker']:
    cols = [t for t in g if t in ret.columns]
    if len(cols) >= 5: idx[s] = (1 + ret[cols].mean(axis=1).fillna(0)).cumprod()
sdf = pd.DataFrame(idx); ma = sdf.rolling(200, min_periods=150).mean()
valid = sdf.notna() & ma.notna()
breadth = ((sdf > ma) & valid).sum(axis=1) / valid.sum(axis=1).replace(0, np.nan)
bser = breadth.reindex(dts).values


def breadth_def_array(thresh=0.35, cf=3):
    out = np.zeros(len(days), bool); md = True; stk = 0; ss = None
    for i in range(len(days)):
        v = bser[i]
        s = (v > thresh) if v == v else ss
        if s is None: out[i] = (not md); continue
        stk = stk + 1 if s == ss else 1; ss = s
        if stk >= cf and md != s: md = s
        out[i] = (not md)
    return out


s_ = kc.rolling(20).mean(); l_ = kc.rolling(80).mean()
regA = np.zeros(len(days), bool); md = True; stk = 0; ss = None
for i, d in enumerate(days):
    ts = pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]); sv = s_.get(ts, np.nan); lv = l_.get(ts, np.nan)
    if pd.isna(sv) or pd.isna(lv): regA[i] = md; continue
    s = bool(sv > lv); stk = stk+1 if s == ss else 1; ss = s
    if stk >= 5 and md != s: md = s
    regA[i] = md

t = TurboSimulator(ar, days, prices, overheat_w=0.2); t._use_overlay = True; t._use_stored_growth = True
for d in days:
    tks = t._preextracted[d][0]; fd = {x['ticker']: x for x in ar[d]}
    t._overlay_pre[d] = np.array([0.2*(fd[tk].get('overheat_pen') or 0)+0.05*(fd[tk].get('mom_10_z') or 0)+0.06*(fd[tk].get('vol_low_z') or 0)-0.3*(fd[tk].get('recent_ca') or 0) for tk in tks])
t._cached_key = None; t._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
flat = list(t._cached_flat); parr = t._price_arr; drows = t._date_row_indices


def base_rets(exit_rank=6):
    port = {}; prev = None; rets = np.zeros(len(days))
    for i in range(2, len(days)):
        cur = regA[i]
        if prev is not None and cur != prev: port = {}
        prev = cur
        if flat[i] is None or not cur:
            if i+1 < len(days) and port:
                cr = drows[i]; nr = drows[i+1]
                rr = [parr[nr, c]/parr[cr, c]-1 for c in port if parr[cr, c] == parr[cr, c] and parr[nr, c] == parr[nr, c] and parr[cr, c] > 0]
                rets[i+1] = np.mean(rr) if rr else 0
            continue
        wr, cc, cp, cw = flat[i]
        for c in list(port):
            if wr[c] > exit_rank: del port[c]
        slots = 3 - len(port)
        for k in range(len(cc)):
            if slots <= 0: break
            if cw[k] <= 3 and cc[k] not in port: port[cc[k]] = cp[k]; slots -= 1
        if i+1 < len(days) and port:
            cr = drows[i]; nr = drows[i+1]
            rr = [parr[nr, c]/parr[cr, c]-1 for c in port if parr[cr, c] == parr[cr, c] and parr[nr, c] == parr[nr, c] and parr[cr, c] > 0]
            rets[i+1] = np.mean(rr) if rr else 0
    return rets


cash_d = 0.03/252


def metrics(r, lo=None, hi=None):
    if lo is not None:
        m = np.array([(lo <= days[i] <= hi) for i in range(len(days))])
        r = r[m]
    eq = np.cumprod(1+r); yrs = len(r)/252
    cagr = eq[-1]**(1/yrs)-1; mdd = (eq/np.maximum.accumulate(eq)-1).min()
    return (cagr/abs(mdd) if mdd < 0 else 0), cagr*100, mdd*100


def variant(rets, bdef, scale, lag):
    """lag=0: 원본(look-ahead) — rets[i]에 bdef[i] 적용
       lag=1: 수정 — rets[i]에 bdef[i-1] 적용 (d-1에 알 수 있던 상태로 사이징)"""
    r = rets.copy()
    for i in range(len(days)):
        j = i - lag
        if j < 0: continue
        if regA[j] and bdef[j]:
            r[i] = scale*rets[i] + (1-scale)*cash_d
    return r


BLOCKS = [('전체', None, None), ('2019-21', '20190102', '20211231'),
          ('2022-23약세', '20220101', '20231231'), ('2024-26', '20240101', '20261231')]
bdef = breadth_def_array()
print(f'[데이터] {days[0]}~{days[-1]} {len(days)}일 | 브레드스 발동 {bdef.sum()}일 ({bdef.sum()/len(days)*100:.0f}%)')
diff = sum(1 for i in range(1, len(days)) if bdef[i] != bdef[i-1])
print(f'[상태 전환일] {diff}회 = look-ahead가 실제로 갈리는 날 수\n')

for XR in (6, 5):
    rets = base_rets(XR)
    print(f'{"="*86}')
    print(f'===== 이탈 X{XR} =====')
    print(f'{"변형":<28}{"Calmar":>9}{"CAGR":>10}{"MDD":>9}   {"약세22-23":>10}{"24-26":>9}')
    rows = [('baseline (브레드스 무)', rets),
            ('50%스케일 lag0 (현행·오염)', variant(rets, bdef, 0.5, 0)),
            ('50%스케일 lag1 (정직)', variant(rets, bdef, 0.5, 1)),
            ('50%스케일 lag2 (보수)', variant(rets, bdef, 0.5, 2)),
            ('binary  lag0 (오염)', variant(rets, bdef, 0.0, 0)),
            ('binary  lag1 (정직)', variant(rets, bdef, 0.0, 1)),
            ('binary  lag2 (보수)', variant(rets, bdef, 0.0, 2))]
    for nm, r in rows:
        c, g, m = metrics(r)
        _, _, _ = 0, 0, 0
        cb = metrics(r, '20220101', '20231231')[0]
        cc2 = metrics(r, '20240101', '20261231')[0]
        print(f'{nm:<28}{c:>9.3f}{g:>9.1f}%{m:>9.1f}%   {cb:>10.2f}{cc2:>9.2f}')
    print()
