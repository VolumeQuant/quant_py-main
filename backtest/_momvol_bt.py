# -*- coding: utf-8 -*-
"""mom_10 + vol_low 가중치 그리드 BT (효율경로).
baseline 상태(state_momvol_full, mom_10_z/vol_low_z 저장됨)를 읽어
각 가중치별로 score 재계산 → composite_rank 재배열 → v80.22 replay BT.

v80.22 룰:
- regime: KOSPI MA20 > MA80, 5일 확인 (boost/defense)
- boost: entry rank<=3, exit rank>4, 3슬롯, SL/TS 둘 다 None
- defense: cash (entry=0), 보유 종목만 rank>8 청산
- wr = cr_t0*0.4 + cr_t1*0.35 + cr_t2*0.25, T-1/T-2는 Top20 한정 + PENALTY 50
"""
import sys, json, glob, os, time
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')

STATE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r'C:\dev\backtest\_state_momvol_full')
DATA = Path(r'C:\dev\data_cache')
PENALTY = 50
TOP_N = 20
# v80.22 boost
EB, XB, SLOTS_B = 3, 4, 3
# defense (cash: entry 0, 보유만 청산 rank>8, slots 5)
XB_D = 8
BASE_MOM, BASE_VOL = 0.05, 0.06

START, END = '20190102', '20260529'

print('=== 데이터 로드 ===', flush=True)
ohlcv = pd.read_parquet(sorted(DATA.glob('all_ohlcv_2017*.parquet'))[-1]).replace(0, np.nan)
kdf = pd.read_parquet(str(DATA / 'kospi_yf.parquet'))
kospi = kdf.iloc[:, 0].sort_index()

# price lookup: ts -> row of ohlcv
ohlcv_idx = ohlcv.index
ohlcv_pos = {ts: i for i, ts in enumerate(ohlcv_idx)}

def get_price(d, tk):
    ts = pd.Timestamp(d)
    i = ohlcv_pos.get(ts)
    if i is None:
        j = ohlcv_idx.searchsorted(ts)
        if j >= len(ohlcv_idx): return None
        ts = ohlcv_idx[j]
    if tk not in ohlcv.columns: return None
    v = ohlcv.loc[ts, tk]
    return v if pd.notna(v) and v > 0 else None

def calc_regime_cross(dates, kospi, short=20, long_p=80, confirm=5):
    sma = kospi.rolling(short).mean(); lma = kospi.rolling(long_p).mean()
    reg = {}; md = False; stk = 0; ss = None
    for d in dates:
        ts = pd.Timestamp(d); sv = sma.get(ts); lv = lma.get(ts)
        if sv is None or pd.isna(sv) or pd.isna(lv): reg[d] = md; continue
        s = bool(sv > lv)
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= confirm and md != s: md = s
        reg[d] = md
    return reg

# --- load baseline rankings: per day list of (ticker, base_score, mom_z, vol_z) ---
print('=== baseline state 로드 ===', flush=True)
all_dates = sorted([os.path.basename(f).replace('ranking_','').replace('.json','')
                    for f in glob.glob(str(STATE / 'ranking_*.json'))])
all_dates = [d for d in all_dates if len(d)==8 and d.isdigit() and START<=d<=END]
print(f'대상: {len(all_dates)}일 ({all_dates[0]}~{all_dates[-1]})', flush=True)

raw = {}  # d -> list of dict(ticker, score, mom_z, vol_z, price)
miss_z = 0; tot = 0
for d in all_dates:
    data = json.load(open(STATE / f'ranking_{d}.json', encoding='utf-8'))
    lst = []
    for r in data['rankings']:
        tk = str(r['ticker']).zfill(6)
        lst.append((tk, float(r.get('score', 0)),
                    float(r.get('mom_10_z', 0.0)), float(r.get('vol_low_z', 0.0)),
                    r.get('price')))
        tot += 1
        if 'mom_10_z' not in r and 'vol_low_z' not in r:
            miss_z += 1
    raw[d] = lst
print(f'z 누락 비율: {miss_z}/{tot} = {100*miss_z/max(tot,1):.1f}%', flush=True)

def build_cr(w_mom, w_vol):
    """가중치별 composite_rank 맵: d -> {ticker: cr}"""
    cr = {}
    for d in all_dates:
        rows = raw[d]
        scored = []
        for tk, sc, mz, vz, _ in rows:
            new_sc = sc - BASE_MOM*mz - BASE_VOL*vz + w_mom*mz + w_vol*vz
            scored.append((tk, new_sc))
        scored.sort(key=lambda x: -x[1])
        cr[d] = {tk: i+1 for i, (tk, _) in enumerate(scored)}
    return cr

def run_bt(dates, regime, cr_cache):
    portfolio = {}; equity = 1.0; eq_hist = {}
    for i, d in enumerate(dates):
        is_boost = regime.get(d, True)
        entry_r = EB if is_boost else 0
        exit_r = XB if is_boost else XB_D
        slots = SLOTS_B if is_boost else 5
        # daily return (prev day holdings)
        if i >= 1 and portfolio:
            rets = []
            for tk in portfolio:
                pp = get_price(dates[i-1], tk); cp = get_price(d, tk)
                if pp and cp: rets.append(cp/pp - 1)
            if rets:
                slot_pct = len(portfolio) / slots
                equity *= (1 + np.mean(rets) * slot_pct)
        eq_hist[d] = equity
        # regime transition -> liquidate
        if i >= 1:
            pb = regime.get(dates[i-1], True)
            if is_boost != pb: portfolio.clear()
        # wr map
        cr0 = cr_cache.get(d, {})
        cr1 = cr_cache.get(dates[i-1], {}) if i >= 1 else {}
        cr2 = cr_cache.get(dates[i-2], {}) if i >= 2 else {}
        top20_t1 = {tk: c for tk, c in cr1.items() if c <= TOP_N}
        top20_t2 = {tk: c for tk, c in cr2.items() if c <= TOP_N}
        wr_map = {}
        for tk, c0 in cr0.items():
            r1 = top20_t1.get(tk, PENALTY); r2 = top20_t2.get(tk, PENALTY)
            wr_map[tk] = c0 * 0.4 + r1 * 0.35 + r2 * 0.25
        # exit (both boost & defense: 보유 종목 룰대로 청산)
        for tk in list(portfolio.keys()):
            if wr_map.get(tk, 999) > exit_r:
                del portfolio[tk]
        # entry (defense entry_r=0 -> 없음)
        if entry_r > 0:
            sorted_wr = sorted(wr_map.items(), key=lambda x: x[1])[:entry_r]
            for tk, _ in sorted_wr:
                if tk in portfolio: continue
                if len(portfolio) >= slots: break
                cp = get_price(d, tk)
                if cp: portfolio[tk] = cp
    eq_arr = np.array(list(eq_hist.values()))
    if len(eq_arr) < 50: return 0,0,0,[0,0,0,0,0], eq_hist
    cagr = (eq_arr[-1] ** (252/len(eq_arr)) - 1) * 100
    pk = np.maximum.accumulate(eq_arr); dd = (eq_arr - pk)/pk
    mdd = -dd.min()*100
    cal = cagr/mdd if mdd>0 else 0
    # WF blocks
    wf = []
    blocks = [('2019','20190102','20191231'),('20-21','20200101','20211231'),
              ('2022','20220101','20221231'),('2023','20230101','20231231'),
              ('24-26','20240101','20260529')]
    eq_s = pd.Series(eq_hist)
    for nm, st, ed in blocks:
        sub = eq_s[(eq_s.index>=st)&(eq_s.index<=ed)]
        if len(sub) < 30: wf.append(0); continue
        sr = (sub.iloc[-1]/sub.iloc[0]) ** (252/len(sub)) - 1
        spk = np.maximum.accumulate(sub.values); sdd = -((sub.values-spk)/spk).min()
        wf.append((sr*100)/(sdd*100) if sdd>0 else 0)
    return cal, cagr, mdd, wf, eq_hist

regime = calc_regime_cross(all_dates, kospi)

GRID = [
    ('baseline', 0.05, 0.06),
    ('1.5x',     0.075,0.09),
    ('2x',       0.10, 0.12),
    ('2.5x',     0.125,0.15),
    ('3x',       0.15, 0.18),
    ('4x',       0.20, 0.24),
    ('6x',       0.30, 0.36),
    ('mom-only', 0.15, 0.06),
    ('mom2x',    0.10, 0.06),
]

print('\n=== 가중치 그리드 BT (전체) ===', flush=True)
print(f'{"name":<10} {"mom":<6} {"vol":<6} {"Cal":<7} {"CAGR":<8} {"MDD":<7} {"2019":<6} {"20-21":<6} {"2022":<6} {"2023":<6} {"24-26":<6} {"WFmin":<6} {"WFmean":<6}', flush=True)
rows_out = []
for nm, wm, wv in GRID:
    t0 = time.time()
    cr_cache = build_cr(wm, wv)
    cal, cagr, mdd, wf, _ = run_bt(all_dates, regime, cr_cache)
    wfv = [x for x in wf if x>0]
    wfmin = min(wfv) if wfv else 0; wfmean = np.mean(wfv) if wfv else 0
    print(f'{nm:<10} {wm:<6.3f} {wv:<6.3f} {cal:<7.3f} {cagr:<8.1f} {mdd:<7.2f} {wf[0]:<6.2f} {wf[1]:<6.2f} {wf[2]:<6.2f} {wf[3]:<6.2f} {wf[4]:<6.2f} {wfmin:<6.2f} {wfmean:<6.2f} ({time.time()-t0:.0f}s)', flush=True)
    rows_out.append({'name':nm,'mom':wm,'vol':wv,'cal':cal,'cagr':cagr,'mdd':mdd,
                     'wf_2019':wf[0],'wf_2021':wf[1],'wf_2022':wf[2],'wf_2023':wf[3],'wf_2426':wf[4],
                     'wf_min':wfmin,'wf_mean':wfmean})

pd.DataFrame(rows_out).to_csv(r'C:\dev\backtest\_momvol_bt_results.csv', index=False, encoding='utf-8-sig')

# === 단일종목 robustness: dominant winner 제외 후 baseline vs 후보 가중치 ===
# 000660 SK하이닉스, 033100 제룡전기 — 둘 다 매수후보에서 제외 (포트 진입 차단)
EXCLUDE = {'000660', '033100'}
print('\n=== LOWO (SK하이닉스+제룡전기 제외) ===', flush=True)
def build_cr_excl(w_mom, w_vol):
    cr = {}
    for d in all_dates:
        scored = []
        for tk, sc, mz, vz, _ in raw[d]:
            if tk in EXCLUDE: continue
            new_sc = sc - BASE_MOM*mz - BASE_VOL*vz + w_mom*mz + w_vol*vz
            scored.append((tk, new_sc))
        scored.sort(key=lambda x: -x[1])
        cr[d] = {tk: i+1 for i, (tk, _) in enumerate(scored)}
    return cr
print(f'{"name":<10} {"Cal":<7} {"CAGR":<8} {"MDD":<7} {"2022":<6} {"WFmin":<6}', flush=True)
for nm, wm, wv in [('baseline',0.05,0.06),('1.5x',0.075,0.09),('2x',0.10,0.12),('mom-only',0.15,0.06),('mom2x',0.10,0.06)]:
    cr_cache = build_cr_excl(wm, wv)
    cal, cagr, mdd, wf, _ = run_bt(all_dates, regime, cr_cache)
    wfv = [x for x in wf if x>0]; wfmin = min(wfv) if wfv else 0
    print(f'{nm:<10} {cal:<7.3f} {cagr:<8.1f} {mdd:<7.2f} {wf[2]:<6.2f} {wfmin:<6.2f}', flush=True)
print('\nCSV: _momvol_bt_results.csv', flush=True)
