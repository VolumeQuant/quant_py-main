# -*- coding: utf-8 -*-
"""① 2026년 매매신호 전수 (현행 X5+K10 production 시맨틱스 리플레이)
② wr 평활 창 길이 스윕 (1~5일) — 진입검증/이탈 공통 적용."""
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
try:
    NAMES = json.load(open(R / 'data_cache' / 'ticker_names_cache.json', encoding='utf-8'))
except Exception:
    NAMES = {}
def nm(t):
    v = NAMES.get(t, t)
    return v if isinstance(v, str) else t

# CR 맵 사전구축 (전 날짜)
CRM = {}
for d in dates:
    CRM[d] = {r['ticker']: r.get('composite_rank', r.get('rank', 50)) for r in all_data[d].get('rankings', [])}
PEN = 50

def sim(weights, X=5, K=10, log_trades=False):
    n = len(weights)
    portfolio = {}; rets = []; last_exit = {}; trades = []
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
        if i < max(n, 3): continue
        is_b = regime_by_date.get(d0, True)
        rp = rp_b if is_b else rp_d
        _exit = X if is_b else rp['EXIT_RANK']
        if regime_by_date.get(dates[i-1], True) != is_b:
            if log_trades:
                for tk, info in portfolio.items():
                    cp = gp(tk, d0)
                    trades.append({'t': tk, 'ed': info['d'], 'xd': d0,
                                   'ret': cp/info['px']-1 if (cp and info['px']) else np.nan, 'why': '국면전환'})
            portfolio = {}
        maps = [CRM[dates[i-k]] for k in range(n)]
        def wr(tk):
            if tk not in maps[0]: return PEN
            return sum(w * maps[k].get(tk, PEN) for k, w in enumerate(weights))
        for tk in list(portfolio.keys()):
            if wr(tk) > _exit:
                info = portfolio.pop(tk); last_exit[tk] = i
                if log_trades:
                    cp = gp(tk, d0)
                    trades.append({'t': tk, 'ed': info['d'], 'xd': d0,
                                   'ret': cp/info['px']-1 if (cp and info['px']) else np.nan, 'why': '순위이탈'})
        # ✅ 3일 top20 교집합 (검증룰 고정 — wr 창과 별개)
        t20 = lambda m: {t for t, r in m.items() if r <= 20}
        m0 = CRM[dates[i]]; m1 = CRM[dates[i-1]]; m2 = CRM[dates[i-2]]
        common = t20(m0) & t20(m1) & t20(m2)
        verified = sorted(common, key=lambda t: (wr(t), m0.get(t, PEN)))
        for tk in verified[:rp['ENTRY_RANK']]:
            if tk in portfolio: continue
            if len(portfolio) >= rp['MAX_SLOTS']: break
            if K > 0 and tk in last_exit and (i - last_exit[tk]) <= K:
                continue
            ep = gp(tk, d0)
            if ep > 0:
                portfolio[tk] = {'px': ep, 'd': d0}
    return rets, trades

def metrics(rets, lo='20190102', hi='20261231'):
    a = np.array([r for d, r in rets if lo <= d <= hi])
    if len(a) < 20: return 0, 0, 0
    eq = np.cumprod(1 + a); peak = np.maximum.accumulate(eq)
    mdd = ((eq - peak) / peak).min() * 100
    cagr = (eq[-1] ** (252/len(a)) - 1) * 100
    return cagr, mdd, cagr/abs(mdd) if mdd < 0 else 0

# ===== ① 2026년 매매 전수 =====
rets, trades = sim([0.4, 0.35, 0.25], log_trades=True)
t26 = [t for t in trades if t['xd'] >= '20260101' or t['ed'] >= '20260101']
buys = sorted({(t['ed'], t['t']) for t in t26 if t['ed'] >= '20260101'})
print(f"===== ① 2026년 매매 (현행 X5+K10 리플레이, ~6/29 데이터) =====")
print(f"진입 {len(buys)}건 / 청산 {len([t for t in t26 if t['xd']>='20260101'])}건")
print(f"\n{'매수일':10s} {'종목':14s} {'매도일':10s} {'보유':>5s} {'수익률':>8s} {'사유':6s}")
for t in sorted(t26, key=lambda x: x['ed']):
    hold = (pd.Timestamp(t['xd']) - pd.Timestamp(t['ed'])).days
    r = f"{t['ret']*100:+.1f}%" if t['ret'] == t['ret'] else '?'
    print(f"{t['ed']:10s} {nm(t['t'])[:12]:14s} {t['xd']:10s} {hold:>4d}d {r:>8s} {t['why']:6s}")
# 현재 보유 (미청산)
print("\n(위는 청산 완료건. 현재 보유 중인 미청산 포지션은 제외)")

# ===== ② wr 창 스윕 =====
print("\n===== ② wr 평활 창 스윕 (진입검증 ✅3일 고정, wr만 변경 / X5 K10) =====")
variants = [
    ([1.0], '1일 (당일 cr만)'),
    ([0.6, 0.4], '2일 60/40'),
    ([0.5, 0.3, 0.2], '3일 50/30/20 (구 v80.12)'),
    ([0.4, 0.35, 0.25], '3일 40/35/25 (현행)'),
    ([1/3, 1/3, 1/3], '3일 균등'),
    ([0.35, 0.3, 0.2, 0.15], '4일 35/30/20/15'),
    ([0.3, 0.25, 0.2, 0.15, 0.1], '5일 30/25/20/15/10'),
]
print(f"  {'변형':26s}{'전체Cal':>8s}{'MDD':>7s}{'CAGR':>7s}{'강세':>7s}{'약세':>7s}{'최근':>7s}{'진입수':>6s}")
for w, lbl in variants:
    r, tr = sim(w, log_trades=True)
    c, m, cal = metrics(r)
    p1 = metrics(r, '20190102', '20211231')[2]; p2 = metrics(r, '20220101', '20231231')[2]; p3 = metrics(r, '20240101', '20261231')[2]
    ne = len([t for t in tr if t['why'] == '순위이탈']) + 3
    cur = ' ←현행' if lbl.endswith('(현행)') else ''
    print(f"  {lbl:26s}{cal:>8.2f}{m:>7.1f}{c:>7.1f}{p1:>7.2f}{p2:>7.2f}{p3:>7.2f}{len(tr):>6d}{cur}")
