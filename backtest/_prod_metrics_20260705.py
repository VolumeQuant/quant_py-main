# -*- coding: utf-8 -*-
"""production 정확 시맨틱스로 최근 3버전 룰 비교 — 전체 성과지표(Sharpe/Sortino 포함).
변형: v80.24~32(X6) / v80.33(X5) / v80.34(X5+쿨다운10 승격금지). 브레드스 전부 ON."""
import sys, os, glob, json
import numpy as np, pandas as pd
from pathlib import Path

R = Path('C:/dev/claude-code/quant_py-main')
STATE = R / 'state'
boost_data = {}; defense_data = {}
for label, dd, rdir in [('boost', boost_data, STATE), ('defense', defense_data, STATE / 'defense')]:
    for fp in sorted(glob.glob(str(rdir / 'ranking_*.json'))):
        d = os.path.basename(fp).replace('ranking_', '').replace('.json', '')
        if not (len(d) == 8 and d.isdigit()):
            continue
        dd[d] = json.load(open(fp, encoding='utf-8'))
kdf = pd.read_parquet(R / 'data_cache' / 'kospi_yf.parquet')
kospi = kdf.iloc[:, 0].copy()
for c in kdf.columns[1:]:
    kospi = kospi.fillna(kdf[c])
kospi = kospi.dropna()
sys.path.insert(0, str(R))
from regime_indicator import SHORT_MA, LONG_MA, CONFIRM_DAYS, get_regime_params
short_ma = kospi.rolling(SHORT_MA).mean(); long_ma = kospi.rolling(LONG_MA).mean()
all_boost_dates = sorted(boost_data.keys())
regime_by_date = {}
_md = False; _stk = 0; _ss = False
for d in all_boost_dates:
    ts = pd.Timestamp(d)
    sv = short_ma.get(ts, None); lv = long_ma.get(ts, None)
    s = (sv > lv) if sv is not None and lv is not None else _md
    if s == _ss: _stk += 1
    else: _stk = 1; _ss = s
    if _stk >= CONFIRM_DAYS and _md != s: _md = s
    regime_by_date[d] = _md
all_data = {}; dates = []
for d in all_boost_dates:
    is_b = regime_by_date.get(d, True)
    if is_b and d in boost_data:
        all_data[d] = boost_data[d]; dates.append(d)
    elif not is_b and d in defense_data:
        all_data[d] = defense_data[d]; dates.append(d)
    elif d in boost_data:
        all_data[d] = boost_data[d]; dates.append(d)
ohlcv_files = sorted(glob.glob(str(R / 'data_cache' / 'all_ohlcv_*.parquet')))
full = [f for f in ohlcv_files if '_full' in f]
if full: ohlcv_files = full
parts = [pd.read_parquet(f).replace(0, np.nan) for f in ohlcv_files]
ohlcv = pd.concat(parts).groupby(level=0).first()
def gp(tk, d):
    ts = pd.Timestamp(d)
    if ts in ohlcv.index and tk in ohlcv.columns:
        v = ohlcv.loc[ts, tk]
        if pd.notna(v) and v > 0: return v
    return 0
try:
    from breadth_diagnostic import breadth_scale_by_date as _bsbd
    BRD = _bsbd(list(dates))
except Exception:
    BRD = {}
CASH_D = 0.03 / 252
rp_b = get_regime_params('boost'); rp_d = get_regime_params('defense')

def sim(exit_rank, K):
    portfolio = {}; rets = []
    last_exit = {}
    for i in range(len(dates)):
        d0 = dates[i]
        r_day = 0.0
        if i >= 1 and portfolio:
            rr = []
            for tk in portfolio:
                pp = gp(tk, dates[i-1]); cp = gp(tk, d0)
                if pp > 0 and cp > 0: rr.append(cp/pp - 1)
            if rr:
                avg = sum(rr)/len(rr)
                sc = BRD.get(d0, 1.0)
                if sc != 1.0 and regime_by_date.get(d0, True):
                    avg = sc*avg + (1-sc)*CASH_D
                r_day = avg
        rets.append((d0, r_day))
        if i < 2: continue
        d1, d2 = dates[i-1], dates[i-2]
        is_b = regime_by_date.get(d0, True)
        rp = rp_b if is_b else rp_d
        _exit = exit_rank if is_b else rp['EXIT_RANK']
        if i >= 1 and regime_by_date.get(dates[i-1], True) != is_b:
            portfolio.clear()
        r0 = all_data[d0].get('rankings', []); r1 = all_data[d1].get('rankings', []); r2 = all_data[d2].get('rankings', [])
        t0 = {r['ticker']: r for r in r0 if r.get('composite_rank', r['rank']) <= 20}
        t1 = {r['ticker']: r for r in r1 if r.get('composite_rank', r['rank']) <= 20}
        t2 = {r['ticker']: r for r in r2 if r.get('composite_rank', r['rank']) <= 20}
        common = set(t0) & set(t1) & set(t2)
        a0 = {r['ticker']: r for r in r0}; a1 = {r['ticker']: r for r in r1}; a2 = {r['ticker']: r for r in r2}
        PEN = 50
        def wr(tk):
            if tk not in a0: return PEN
            c0 = a0[tk].get('composite_rank', a0[tk].get('rank', PEN))
            c1 = a1[tk].get('composite_rank', a1[tk].get('rank', PEN)) if tk in a1 else PEN
            c2 = a2[tk].get('composite_rank', a2[tk].get('rank', PEN)) if tk in a2 else PEN
            return c0*0.4 + c1*0.35 + c2*0.25
        for tk in list(portfolio.keys()):
            if wr(tk) > _exit:
                del portfolio[tk]; last_exit[tk] = i
        verified = []
        for tk in common:
            c0 = t0[tk].get('composite_rank', t0[tk]['rank']); c1 = t1[tk].get('composite_rank', t1[tk]['rank']); c2 = t2[tk].get('composite_rank', t2[tk]['rank'])
            verified.append({'ticker': tk, 'w': c0*0.4+c1*0.35+c2*0.25, 'c': c0})
        verified.sort(key=lambda x: (x['w'], x['c']))
        for v in verified[:rp['ENTRY_RANK']]:
            tk = v['ticker']
            if tk in portfolio: continue
            if len(portfolio) >= rp['MAX_SLOTS']: break
            if K > 0 and tk in last_exit and (i - last_exit[tk]) <= K:
                continue
            ep = gp(tk, d0)
            if ep > 0: portfolio[tk] = ep
    return rets

def metrics(rets, lo='20190102', hi='20261231'):
    a = np.array([r for d, r in rets if lo <= d <= hi])
    eq = np.cumprod(1 + a); peak = np.maximum.accumulate(eq)
    mdd = ((eq - peak) / peak).min() * 100
    n = len(a)
    cagr = (eq[-1] ** (252/n) - 1) * 100
    mu = a.mean(); sd = a.std()
    sharpe = (mu - CASH_D) / sd * np.sqrt(252) if sd > 0 else 0
    dn = a[a < 0]
    sortino = (mu - CASH_D) / dn.std() * np.sqrt(252) if len(dn) > 1 and dn.std() > 0 else 0
    vol = sd * np.sqrt(252) * 100
    win = (a[a != 0] > 0).mean() * 100
    return cagr, mdd, cagr/abs(mdd) if mdd < 0 else 0, sharpe, sortino, vol, win

print(f"{'버전(룰)':28s}{'CAGR%':>8s}{'MDD%':>7s}{'Calmar':>7s}{'Sharpe':>7s}{'Sortino':>8s}{'연변동%':>8s}{'일승률%':>8s}")
variants = [(6, 0, 'v80.24~32 (X6)'), (5, 0, 'v80.33 (X5)'), (5, 10, 'v80.34 (X5+쿨다운10)')]
res = {}
for xr, K, lbl in variants:
    r = sim(xr, K)
    res[lbl] = r
    c, m, cal, sh, so, vol, win = metrics(r)
    print(f"{lbl:28s}{c:>8.1f}{m:>7.1f}{cal:>7.2f}{sh:>7.2f}{so:>8.2f}{vol:>8.1f}{win:>8.1f}")
print("\n[기간분해 Calmar — 강세19-21 / 약세22-23 / 최근24-26]")
for xr, K, lbl in variants:
    r = res[lbl]
    p1 = metrics(r, '20190102', '20211231')[2]
    p2 = metrics(r, '20220101', '20231231')[2]
    p3 = metrics(r, '20240101', '20261231')[2]
    print(f"  {lbl:28s}{p1:>7.2f}{p2:>7.2f}{p3:>7.2f}")
# 코스피 벤치마크
k = kospi[(kospi.index >= '2019-01-02')]
ka = k.pct_change().dropna().values
keq = np.cumprod(1+ka); kpk = np.maximum.accumulate(keq)
km = ((keq-kpk)/kpk).min()*100
kc = (keq[-1]**(252/len(ka))-1)*100
ksh = (ka.mean())/ka.std()*np.sqrt(252)
print(f"\n[벤치마크 KOSPI 동기간] CAGR {kc:.1f}% MDD {km:.1f}% Calmar {kc/abs(km):.2f} Sharpe {ksh:.2f}")
