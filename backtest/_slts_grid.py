"""SL/TS 스위트 스팟 — v80.18 환경 (MA20x80x5, eb=3, xb=4, slots=4) 고정.

stop_loss × trailing_stop 그리드 + IS/OOS/WF + 인접 안정성.
defense는 cash(entry=0)이므로 SL/TS는 boost에서만 적용 → boost SL/TS만 스윕.

baseline 재현 체크: SL-10/TS-8 → v80.18 Cal ~3.23 이어야 harness 유효.
"""
import sys, json, time
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(r'C:\dev\claude-code\quant_py-main')
STATE = ROOT / 'state'
DATA = ROOT / 'data_cache'
PENALTY = 50
TOP_N = 20
EB, XB, SLOTS = 3, 4, 4   # v80.18 고정

print('=== 데이터 로드 ===', flush=True)
ohlcv = pd.read_parquet(sorted(DATA.glob('all_ohlcv_2017*.parquet'))[-1]).replace(0, np.nan)
kdf = pd.read_parquet(str(DATA / 'kospi_yf.parquet'))
kospi = kdf.iloc[:, 0].sort_index()


def calc_regime_cross(dates, kospi, short, long_p, confirm):
    sma = kospi.rolling(short).mean(); lma = kospi.rolling(long_p).mean()
    reg = {}; md = False; stk = 0; ss = None
    for d in dates:
        ts = pd.Timestamp(d); sv = sma.get(ts); lv = lma.get(ts)
        if sv is None or pd.isna(sv) or pd.isna(lv): reg[d] = md; continue
        s = sv > lv
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= confirm and md != s: md = s
        reg[d] = md
    return reg


def get_price(d, tk):
    ts = pd.Timestamp(d)
    if ts not in ohlcv.index:
        idx = ohlcv.index.searchsorted(ts)
        if idx >= len(ohlcv): return None
        ts = ohlcv.index[idx]
    if tk not in ohlcv.columns: return None
    v = ohlcv.loc[ts, tk]
    return v if pd.notna(v) and v > 0 else None


def load_cr(d):
    fp = STATE / f'ranking_{d}.json'
    if not fp.exists(): return {}
    data = json.load(open(fp, 'r', encoding='utf-8'))
    return {str(r['ticker']).zfill(6): r.get('composite_rank', r.get('rank', 999)) for r in data['rankings']}


all_dates = sorted([fp.stem.replace('ranking_', '') for fp in STATE.glob('ranking_*.json')
                    if fp.stem.replace('ranking_', '').isdigit()
                    and len(fp.stem.replace('ranking_', '')) == 8
                    and '20190102' <= fp.stem.replace('ranking_', '') <= '20260522'])
print(f'대상: {len(all_dates)} 일', flush=True)
cr_cache = {d: load_cr(d) for d in all_dates}
is_dates = [d for d in all_dates if d <= '20221231']
oos_dates = [d for d in all_dates if d >= '20230102']


def run_bt(dates, regime, sl, ts):
    """sl/ts: None=미사용, 음수=발동 임계 (예: -0.10)."""
    portfolio = {}; peak = {}; equity = 1.0; eq_hist = {}
    for i, d in enumerate(dates):
        is_boost = regime.get(d, True)
        entry_r = EB if is_boost else 0
        exit_r = XB if is_boost else 8
        if i >= 1 and portfolio:
            rets = []
            for tk in portfolio:
                pp = get_price(dates[i-1], tk); cp = get_price(d, tk)
                if pp and cp: rets.append(cp/pp - 1)
            if rets:
                slot_pct = len(portfolio) / SLOTS
                equity *= (1 + np.mean(rets) * slot_pct)
        eq_hist[d] = equity
        if i >= 1:
            pb = regime.get(dates[i-1], True)
            if is_boost != pb: portfolio.clear(); peak.clear()
        if not is_boost: continue
        for tk in list(portfolio.keys()):
            cp = get_price(d, tk); ep = portfolio[tk]
            if cp and ep:
                if tk in peak:
                    if cp > peak[tk]: peak[tk] = cp
                else: peak[tk] = max(cp, ep)
                if sl is not None and cp/ep - 1 <= sl:
                    del portfolio[tk]; peak.pop(tk, None)
                elif ts is not None and peak.get(tk, 0) > 0 and cp/peak[tk] - 1 <= ts:
                    del portfolio[tk]; peak.pop(tk, None)
        cr0 = cr_cache.get(d, {})
        cr1 = cr_cache.get(dates[i-1], {}) if i >= 1 else {}
        cr2 = cr_cache.get(dates[i-2], {}) if i >= 2 else {}
        top20_t1 = {tk: c for tk, c in cr1.items() if c <= TOP_N}
        top20_t2 = {tk: c for tk, c in cr2.items() if c <= TOP_N}
        wr_map = {}
        for tk, c0 in cr0.items():
            r1 = top20_t1.get(tk, PENALTY); r2 = top20_t2.get(tk, PENALTY)
            wr_map[tk] = c0 * 0.4 + r1 * 0.35 + r2 * 0.25
        for tk in list(portfolio.keys()):
            if wr_map.get(tk, 999) > exit_r: del portfolio[tk]; peak.pop(tk, None)
        sorted_wr = sorted(wr_map.items(), key=lambda x: x[1])[:entry_r]
        for tk, _ in sorted_wr:
            if tk in portfolio: continue
            if len(portfolio) >= SLOTS: break
            cp = get_price(d, tk)
            if cp: portfolio[tk] = cp; peak[tk] = cp
    eq_arr = np.array(list(eq_hist.values()))
    if len(eq_arr) < 50: return 0, 0, 0, [0,0,0,0]
    cagr = (eq_arr[-1] ** (252/len(eq_arr)) - 1) * 100
    pk = np.maximum.accumulate(eq_arr); dd = (eq_arr - pk) / pk
    mdd = -dd.min() * 100
    cal = cagr / mdd if mdd > 0 else 0
    wf = []
    for nm, st, ed in [('2019','20190102','20191231'),('20-21','20200101','20211231'),
                        ('22-23','20220101','20231231'),('24-26','20240101','20260522')]:
        eq_s = pd.Series(eq_hist); sub = eq_s[(eq_s.index >= st) & (eq_s.index <= ed)]
        if len(sub) < 50: wf.append(0); continue
        sub_ret = (sub.iloc[-1]/sub.iloc[0]) ** (252/len(sub)) - 1
        sub_pk = np.maximum.accumulate(sub.values); sub_dd = -((sub.values - sub_pk)/sub_pk).min()
        wf.append((sub_ret*100)/(sub_dd*100) if sub_dd > 0 else 0)
    return cal, cagr, mdd, wf


regime_all = calc_regime_cross(all_dates, kospi, 20, 80, 5)
regime_is = calc_regime_cross(is_dates, kospi, 20, 80, 5)
regime_oos = calc_regime_cross(oos_dates, kospi, 20, 80, 5)

# baseline 재현
bc, bcagr, bmdd, bwf = run_bt(all_dates, regime_all, -0.10, -0.08)
print(f'\n[baseline 재현] SL-10/TS-8 → Cal {bc:.3f} CAGR {bcagr:.1f}% MDD {bmdd:.2f}% (v80.18 기대 ~3.23)', flush=True)

# 그리드
SL_GRID = [None, -0.05, -0.07, -0.08, -0.10, -0.12, -0.15, -0.20, -0.25]
TS_GRID = [None, -0.05, -0.06, -0.08, -0.10, -0.12, -0.15, -0.20, -0.25]

print(f'\n=== SL × TS 그리드 ({len(SL_GRID)}×{len(TS_GRID)}={len(SL_GRID)*len(TS_GRID)}) ===', flush=True)
t0 = time.time()
results = []
for sl in SL_GRID:
    for ts in TS_GRID:
        cal, cagr, mdd, wf = run_bt(all_dates, regime_all, sl, ts)
        is_cal, _, _, _ = run_bt(is_dates, regime_is, sl, ts)
        oos_cal, _, _, _ = run_bt(oos_dates, regime_oos, sl, ts)
        wf_vals = [c for c in wf if c > 0]
        wf_min = min(wf_vals) if wf_vals else 0
        wf_cv = np.std(wf_vals)/np.mean(wf_vals) if wf_vals else 999
        score = cal*0.3 + is_cal*0.2 + oos_cal*0.2 + wf_min*0.2 + (10/mdd if mdd>0 else 0)*0.1
        results.append({'sl': sl, 'ts': ts, 'cal': cal, 'cagr': cagr, 'mdd': mdd,
                        'is_cal': is_cal, 'oos_cal': oos_cal, 'wf_min': wf_min, 'wf_cv': wf_cv,
                        'wf_2019': wf[0], 'wf_2021': wf[1], 'wf_bear': wf[2], 'wf_2025': wf[3],
                        'score': score})
print(f'완료: {time.time()-t0:.0f}초', flush=True)

df = pd.DataFrame(results)
def fmt(x): return 'none' if x is None else f'{x*100:.0f}%'
cell = {(r['sl'], r['ts']): r for r in results}

# Cal heatmap
print('\n=== Cal heatmap (행 SL × 열 TS) ===', flush=True)
hdr = 'SL\\TS  ' + ''.join(f'{fmt(ts):>8}' for ts in TS_GRID)
print(hdr, flush=True)
for sl in SL_GRID:
    row = f'{fmt(sl):<6} '
    for ts in TS_GRID:
        row += f"{cell[(sl,ts)]['cal']:>8.3f}"
    print(row, flush=True)

# MDD heatmap
print('\n=== MDD% heatmap (행 SL × 열 TS) ===', flush=True)
print(hdr, flush=True)
for sl in SL_GRID:
    row = f'{fmt(sl):<6} '
    for ts in TS_GRID:
        row += f"{cell[(sl,ts)]['mdd']:>8.2f}"
    print(row, flush=True)

# Top 15 종합 점수
print('\n=== Top 15 (종합 점수) ===', flush=True)
print(f'{"#":<3} {"SL":<6} {"TS":<6} {"Cal":<7} {"CAGR":<7} {"MDD":<7} {"IS":<6} {"OOS":<6} {"WFmin":<7} {"점수":<7}', flush=True)
for i, r in enumerate(df.nlargest(15, 'score').to_dict('records')):
    print(f"{i+1:<3} {fmt(r['sl']):<6} {fmt(r['ts']):<6} {r['cal']:>6.3f} {r['cagr']:>5.1f}% {r['mdd']:>5.2f}% {r['is_cal']:>5.2f} {r['oos_cal']:>5.2f} {r['wf_min']:>5.2f} {r['score']:>6.3f}", flush=True)

# Cal Top 10
print('\n=== Cal Top 10 ===', flush=True)
for i, r in enumerate(df.nlargest(10, 'cal').to_dict('records')):
    print(f"{i+1:<3} SL={fmt(r['sl'])} TS={fmt(r['ts'])} → Cal {r['cal']:.3f} CAGR {r['cagr']:.1f}% MDD {r['mdd']:.2f}% IS {r['is_cal']:.2f} OOS {r['oos_cal']:.2f} WFmin {r['wf_min']:.2f}", flush=True)

df_save = df.copy()
df_save['sl'] = df_save['sl'].apply(fmt); df_save['ts'] = df_save['ts'].apply(fmt)
df_save.to_csv(ROOT / '_slts_grid_results.csv', index=False, encoding='utf-8-sig')
print(f'\nCSV: _slts_grid_results.csv ({len(df)} 시나리오)', flush=True)
