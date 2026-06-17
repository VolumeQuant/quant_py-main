# -*- coding: utf-8 -*-
"""프로덕션 state(_prod_boost, 수정주가+페널티 FG생성) 검증: 저장된 recent_ca로 페널티 오버레이 적용 →
honest Calmar(~4.10) 재현 확인. RETURN=V_all(수정주가). TurboSim은 z서 재계산하므로 recent_ca 수동 주입."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ, 'data_cache', 'all_ohlcv_adj_*.parquet')))[-1]).replace(0, np.nan)
kc = pd.read_parquet(os.path.join(PROJ, 'data_cache', 'kospi_yf.parquet')).iloc[:, 0]
ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()
def calc_reg(ds):
    reg = {}; md = True; stk = 0; ss = None
    for d in ds:
        ts = pd.Timestamp(d[:4] + '-' + d[4:6] + '-' + d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts, np.nan)): reg[d] = md; continue
        s = bool(ma20[ts] > ma80[ts])
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= 5 and md != s: md = s
        reg[d] = md
    return reg
G3 = ('rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)
def load(folder):
    ar, dates = {}, []
    for f in sorted(glob.glob(os.path.join(PROJ, folder, 'ranking_*.json'))):
        dt = os.path.basename(f)[8:16]
        if dt.isdigit() and len(dt) == 8 and dt >= '20190102':
            ar[dt] = json.load(open(f, encoding='utf-8'))['rankings']; dates.append(dt)
    return ar, sorted(dates)
def runbt(folder, W=0.3):
    ar, sub = load(folder); reg = calc_reg(sub)
    t = TurboSimulator(ar, sub, prices, overheat_w=0.2); t._use_overlay = True; t._use_stored_growth = True
    for d in sub:
        tks = t._preextracted[d][0]; fd = {x['ticker']: x for x in ar[d]}
        t._overlay_pre[d] = np.array([
            0.2 * (fd[tk].get('overheat_pen') or 0) + 0.05 * (fd[tk].get('mom_10_z') or 0)
            + 0.06 * (fd[tk].get('vol_low_z') or 0) - W * (fd[tk].get('recent_ca') or 0) for tk in tks])
    t._cached_key = None
    t._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
    flat = list(t._cached_flat)
    r = _run_regime_inner(flat, flat, 0, 6, 3, 3, 6, 3, reg, sub, t._price_arr, t._bench_arr, t._has_bench,
                          t._date_row_indices, len(sub), None, None, None, None,
                          stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None)
    return r.get('calmar', 0), r.get('cagr', 0), r.get('mdd', 0), len(sub)
c = runbt('_prod_boost', W=0.3)
print(f"프로덕션 state(_prod_boost) 검증: Calmar {c[0]:.3f} CAGR {c[1]:.0f}% MDD {c[2]:.1f}% ({c[3]}일)")
n_rc = sum(1 for f in glob.glob(os.path.join(PROJ, '_prod_boost', 'ranking_*.json'))
           for x in json.load(open(f, encoding='utf-8'))['rankings'] if x.get('recent_ca'))
print(f"recent_ca 저장된 종목-일 수: {n_rc}")
print("→ ~4.10이면 프로덕션 state가 검증된 페널티 전략과 정합 (배포 OK)")
