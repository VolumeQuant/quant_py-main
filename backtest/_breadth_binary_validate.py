# -*- coding: utf-8 -*-
"""브레드스 50%스케일 vs binary(전량현금) 배포검증 (2026-07-31).

look-ahead(lag0) 제거 후 binary가 50%를 이기는지 — 배포 철칙대로 WF 3블록 + LOWO 통과 여부.
lag1(정직) 기준으로만 비교. 단일 하니스 결과라 절대값은 production과 다름(상대비교용).
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
colidx = {tk: i for i, tk in enumerate(prices.columns)}


def base_rets(exit_rank=5, exclude_cols=frozenset()):
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
            if cc[k] in exclude_cols: continue
            if cw[k] <= 3 and cc[k] not in port: port[cc[k]] = cp[k]; slots -= 1
        if i+1 < len(days) and port:
            cr = drows[i]; nr = drows[i+1]
            rr = [parr[nr, c]/parr[cr, c]-1 for c in port if parr[cr, c] == parr[cr, c] and parr[nr, c] == parr[nr, c] and parr[cr, c] > 0]
            rets[i+1] = np.mean(rr) if rr else 0
    return rets


cash_d = 0.03/252
bdef = breadth_def_array()


def variant(rets, scale, lag=1):
    r = rets.copy()
    for i in range(len(days)):
        j = i - lag
        if j < 0: continue
        if regA[j] and bdef[j]:
            r[i] = scale*rets[i] + (1-scale)*cash_d
    return r


def metrics(r, lo=None, hi=None):
    if lo is not None:
        m = np.array([(lo <= days[i] <= hi) for i in range(len(days))])
        r = r[m]
    if len(r) < 30: return 0, 0, 0
    eq = np.cumprod(1+r); yrs = len(r)/252
    cagr = eq[-1]**(1/yrs)-1; mdd = (eq/np.maximum.accumulate(eq)-1).min()
    return (cagr/abs(mdd) if mdd < 0 else 0), cagr*100, mdd*100


BLOCKS = [('2019-21', '20190102', '20211231'),
          ('2022-23약세', '20220101', '20231231'),
          ('2024-26', '20240101', '20261231')]

print('='*80)
print('===== WF 3블록 (lag1 정직 기준, 이탈 X5) =====')
rets = base_rets(5)
print(f'{"구간":<14}{"50%스케일":>11}{"binary":>10}{"차이":>9}   판정')
allpass = True
for nm, lo, hi in [('전체', None, None)] + BLOCKS:
    c50 = metrics(variant(rets, 0.5), lo, hi)[0]
    cbi = metrics(variant(rets, 0.0), lo, hi)[0]
    d = cbi - c50
    ok = '✅binary우위' if d > 0.10 else ('~동급' if d > -0.10 else '❌binary열위')
    if d <= -0.10: allpass = False
    print(f'{nm:<14}{c50:>11.3f}{cbi:>10.3f}{d:>+9.3f}   {ok}')

print()
print('='*80)
print('===== LOWO (승자 제외해도 유지되나, lag1 · X5) =====')
name2tk = {}
for d in days[-400:]:
    for x in ar[d]: name2tk[x['name']] = x['ticker']
WIN = ['SK하이닉스', '제주반도체', '디바이스이엔지', '한미반도체', '제룡전기', '이오테크닉스']
print(f'{"제외종목":<16}{"50%스케일":>11}{"binary":>10}{"차이":>9}   판정')
for w in WIN:
    tk = name2tk.get(w)
    if not tk or tk not in colidx:
        print(f'{w:<16}  (티커 매칭 실패, 스킵)'); continue
    r2 = base_rets(5, frozenset({colidx[tk]}))
    c50 = metrics(variant(r2, 0.5))[0]
    cbi = metrics(variant(r2, 0.0))[0]
    d = cbi - c50
    ok = '✅' if d > 0.10 else ('~' if d > -0.10 else '❌')
    if d <= -0.10: allpass = False
    print(f'{w:<16}{c50:>11.3f}{cbi:>10.3f}{d:>+9.3f}   {ok}')

print()
print('='*80)
print('===== 인접 안정성 (스케일 0.0~0.7, lag1 · X5) =====')
print(f'{"스케일":<10}{"Calmar":>10}{"MDD":>10}{"CAGR":>10}')
cals = []
for sc in [0.0, 0.15, 0.3, 0.5, 0.7]:
    c, g, m = metrics(variant(rets, sc))
    cals.append(c)
    print(f'{sc:<10.2f}{c:>10.3f}{m:>9.1f}%{g:>9.1f}%')
print(f'  CV = {np.std(cals)/np.mean(cals):.3f}')
print()
print(f'>>> 배포 게이트: {"통과 (전 블록·LOWO에서 binary 열위 없음)" if allpass else "★미통과 — 일부 구간/종목에서 binary 열위"}')
