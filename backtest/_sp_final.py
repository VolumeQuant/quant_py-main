# -*- coding: utf-8 -*-
"""최종 판정 (7.4년): annual(_sp0) vs 완전TTM(_sp2).
TurboSim 정확 sim + 오버레이 ON. production-config + 풀스윕653 best + 인접CV + 연도별(WF).
usage: python _sp_final.py"""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
class _Tee:
    def __init__(self, *fs): self.fs = fs
    def write(self, x):
        for f in self.fs:
            try: f.write(x); f.flush()
            except Exception: pass
    def flush(self):
        for f in self.fs:
            try: f.flush()
            except Exception: pass
_resf = open(r'C:\dev\_sp_final_result.txt', 'w', encoding='utf-8')
sys.stdout = _Tee(sys.stdout, _resf)
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FOLDERS = [('_sp0', 'annual(현행)'), ('_sp2', '완전TTM(PER+ROE)')]
def ba(s):
    r = s.pct_change(fill_method=None); ev = r[(r < -0.33) | (r > 0.45)]; s2 = s.copy()
    for d, rt in ev.items():
        f = 1 + rt
        if 0.02 < abs(f) < 50: s2.loc[s2.index < d] *= f
    return s2
prices = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ, 'data_cache', 'all_ohlcv_*_2026061*.parquet')))[0]).replace(0, np.nan).apply(ba)
kdf = pd.read_parquet(os.path.join(PROJ, 'data_cache', 'kospi_yf.parquet'))
kc = kdf.iloc[:, 0] if kdf.shape[1] else kdf['Close']
ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()
def calc_reg(dsub):
    reg = {}; md = True; stk = 0; ss = None
    for d in dsub:
        ts = pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts, np.nan)): reg[d] = md; continue
        s = bool(ma20[ts] > ma80[ts])
        if s == ss: stk += 1
        else: stk = 1; ss = s
        if stk >= 5 and md != s: md = s
        reg[d] = md
    return reg
G3 = ('rev_z', 'oca_z', 'gp_growth_z', 0.4, 0.4, 0.2)
def load(folder, lo='20190102', hi='20261231'):
    ar, dates = {}, []
    for f in sorted(glob.glob(os.path.join(PROJ, folder, 'ranking_*.json'))):
        dt = os.path.basename(f)[8:16]
        if dt.isdigit() and len(dt) == 8 and lo <= dt <= hi:
            ar[dt] = json.load(open(f, encoding='utf-8'))['rankings']; dates.append(dt)
    return ar, sorted(dates)
def regbt(tsim, dates, reg, v, q, g, m):
    tsim._ensure_cache(v/100, q/100, g/100, m/100, 0.4, 20, '12m', *G3[:3], *G3[3:])
    flat = list(tsim._cached_flat)
    return _run_regime_inner(flat, flat, 0, 6, 3, 3, 6, 3, reg, dates, tsim._price_arr, tsim._bench_arr,
        tsim._has_bench, tsim._date_row_indices, len(dates), None, None, None, None,
        stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None)
combos = [(v, q, g, 100-v-q-g) for v in range(0, 45, 5) for q in range(0, 45, 5)
          for g in range(10, 75, 5) if 10 <= 100-v-q-g <= 60]
YEARS = ['2019', '2020', '2021', '2022', '2023', '2024', '2025', '2026']
REG_LBL = {'2019':'회복','2020':'코로나','2021':'강세','2022':'약세','2023':'회복','2024':'강세','2025':'강세','2026':'초강세'}
data = {}
for folder, lbl in FOLDERS:
    ar, dates = load(folder)
    print(f'[{lbl}] {dates[0]}~{dates[-1]} {len(dates)}일')
    data[folder] = (ar, dates, lbl)
print(f'풀그리드 {len(combos)}조합 × 오버레이 ON\n')
best = {}
for folder, lbl in FOLDERS:
    ar, dates, _ = data[folder]
    reg = calc_reg(dates)
    tsim = TurboSimulator(ar, dates, prices); tsim._use_overlay = True; tsim._use_stored_growth = True
    prod = regbt(tsim, dates, reg, 15, 0, 55, 30)
    res = sorted([(v,q,g,m,*[regbt(tsim,dates,reg,v,q,g,m).get(k,0) for k in ['calmar','cagr','mdd']]) for v,q,g,m in combos], key=lambda x:-x[4])
    best[folder] = (res, prod, tsim, dates, reg)
    b = res[0]
    # 인접 CV
    bv,bq,bg,bm = b[:4]
    adj=[regbt(tsim,dates,reg,max(0,bv+dv),max(0,bq+dq),bg,100-max(0,bv+dv)-max(0,bq+dq)-bg).get('calmar',0)
         for dv in(-5,0,5) for dq in(-5,0,5) if 10<=100-max(0,bv+dv)-max(0,bq+dq)-bg<=60]
    adj=[a for a in adj if a>0]; cv=np.std(adj)/np.mean(adj) if len(adj)>2 else 0
    print(f'=== {lbl} (7.4년) ===')
    print(f'  production V15Q0G55M30: Cal {prod["calmar"]:.3f} (CAGR {prod["cagr"]:.0f} MDD {prod["mdd"]:.0f})')
    print(f'  재최적 best: V{b[0]}Q{b[1]}G{b[2]}M{b[3]} Cal {b[4]:.3f} (CAGR {b[5]:.0f} MDD {b[6]:.0f}), 인접CV {cv:.3f}')
    print(f'  best 상위3: ' + ' / '.join(f'V{r[0]}Q{r[1]}G{r[2]}M{r[3]}={r[4]:.2f}' for r in res[:3]))
# 연도별 WF (production config)
print(f'\n=== 연도별 production-config Calmar (annual vs 완전TTM) ===')
print(f"{'연도':<14}" + ''.join(f'{y[2:]}({REG_LBL[y]})'.rjust(13) for y in YEARS))
for folder, lbl in FOLDERS:
    ar, dates, _ = data[folder]
    row = f'{lbl:<14}'
    for y in YEARS:
        dsub = [d for d in dates if d[:4] == y]
        if len(dsub) < 20: row += 'n/a'.rjust(13); continue
        sim = TurboSimulator({d: ar[d] for d in dsub}, sorted(dsub), prices); sim._use_overlay = True; sim._use_stored_growth = True
        r = regbt(sim, sorted(dsub), calc_reg(sorted(dsub)), 15, 0, 55, 30)
        row += f"{r.get('cagr',0):>+8.0f}%".rjust(13)
    print(row)
print(f"\n{'='*55}")
for folder, lbl in FOLDERS:
    b = best[folder][0][0]; pr = best[folder][1]
    print(f'  {lbl:<18} production Cal {pr["calmar"]:.3f} / 재최적 best {b[4]:.3f}')
