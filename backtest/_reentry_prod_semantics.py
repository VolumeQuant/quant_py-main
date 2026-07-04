# -*- coding: utf-8 -*-
"""재진입 쿨다운을 production calc_system_returns 정확 시맨틱스로 재검증.
BT 하니스(wr<=3 절대게이트)와 production(verified[:entry_rank], 게이트 없음) 차이 규명.
변형: K=0 / K10+승격(현 구현) / K10+승격금지(슬롯 비움).
지표: Calmar/MDD/기간분해 — production과 동일 데이터소스(boost+defense state, kospi_yf, OHLCV glob)."""
import sys, os, glob, json
import numpy as np, pandas as pd
from pathlib import Path

R = Path('C:/dev/claude-code/quant_py-main')
STATE = R / 'state'

# 데이터 로드 — production 동일
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

def sim(K, promote=True):
    portfolio = {}; equity = 1.0; eqh = []
    last_exit = {}
    for i in range(len(dates)):
        d0 = dates[i]
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
                equity *= (1+avg)
        eqh.append((d0, equity))
        if i < 2: continue
        d1, d2 = dates[i-1], dates[i-2]
        is_b = regime_by_date.get(d0, True)
        rp = rp_b if is_b else rp_d
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
            if wr(tk) > rp['EXIT_RANK']:
                del portfolio[tk]; last_exit[tk] = i
        verified = []
        for tk in common:
            c0 = t0[tk].get('composite_rank', t0[tk]['rank']); c1 = t1[tk].get('composite_rank', t1[tk]['rank']); c2 = t2[tk].get('composite_rank', t2[tk]['rank'])
            verified.append({'ticker': tk, 'w': c0*0.4+c1*0.35+c2*0.25, 'c': c0})
        verified.sort(key=lambda x: (x['w'], x['c']))
        if K > 0 and promote:
            verified = [v for v in verified if v['ticker'] not in last_exit or (i - last_exit[v['ticker']]) > K]
        for v in verified[:rp['ENTRY_RANK']]:
            tk = v['ticker']
            if tk in portfolio: continue
            if len(portfolio) >= rp['MAX_SLOTS']: break
            if K > 0 and not promote and tk in last_exit and (i - last_exit[tk]) <= K:
                continue  # 승격금지: 차단만, 다음 후보 진입 안 함(슬라이스가 이미 top3 한정)
            ep = gp(tk, d0)
            if ep > 0: portfolio[tk] = ep
    eq = pd.Series({pd.Timestamp(d): e for d, e in eqh}).sort_index()
    def stats(lo, hi):
        s = eq[(eq.index >= lo) & (eq.index <= hi)]
        if len(s) < 20: return 0, 0, 0
        r = s / s.iloc[0]
        peak = r.cummax(); mdd = ((r - peak) / peak).min() * 100
        cagr = (r.iloc[-1] ** (252/len(s)) - 1) * 100
        return cagr, mdd, (cagr/abs(mdd) if mdd < 0 else 0)
    return stats, eq

print(f"{'변형':26s}{'전체Cal':>8s}{'MDD':>7s}{'CAGR':>7s}{'강세':>7s}{'약세':>7s}{'최근':>7s}")
for K, pr, lbl in [(0, True, 'K=0 (현행 production)'), (10, True, 'K10+승격 (현 구현)'), (10, False, 'K10+승격금지')]:
    st_, eq = sim(K, pr)
    c, m, cal = st_('2019-01-01', '2026-12-31')
    _, _, p1 = st_('2019-01-01', '2021-12-31')
    _, _, p2 = st_('2022-01-01', '2023-12-31')
    _, _, p3 = st_('2024-01-01', '2026-12-31')
    print(f"{lbl:26s}{cal:>8.2f}{m:>7.1f}{c:>7.1f}{p1:>7.2f}{p2:>7.2f}{p3:>7.2f}")
