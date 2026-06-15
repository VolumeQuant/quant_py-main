# -*- coding: utf-8 -*-
"""올바른 비교: TurboSim(정확한 entry_fixed sim) + 오버레이 opt-in.
검증: 오버레이 ON 랭킹 vs production composite_rank.
그다음 production-config + 풀스윕을 overlay ON으로 재측정 (내 flawed sim 대체).
usage: python _sp_turbo.py <lo> <hi> [folders...]"""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LO = sys.argv[1] if len(sys.argv) > 1 else '20250601'
HI = sys.argv[2] if len(sys.argv) > 2 else '20260611'
FOLDERS = sys.argv[3:] if len(sys.argv) > 3 else ['_sp0', '_sp1', '_sp2']
LBL = {'_sp0': 'annual(현행)', '_sp1': 'TTM(PER만)', '_sp2': 'TTM(PER+ROE)'}
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
def load(folder):
    ar, dates, jcr = {}, [], {}
    for f in sorted(glob.glob(os.path.join(PROJ, folder, 'ranking_*.json'))):
        dt = os.path.basename(f)[8:16]
        if dt.isdigit() and len(dt) == 8 and LO <= dt <= HI:
            d = json.load(open(f, encoding='utf-8')); ar[dt] = d['rankings']; dates.append(dt)
            jcr[dt] = {str(s['ticker']).zfill(6): int(s.get('composite_rank', s['rank'])) for s in d['rankings']}
    return ar, sorted(dates), jcr
def regbt(tsim, dates, reg, v, q, g, m):
    tsim._ensure_cache(v/100, q/100, g/100, m/100, 0.4, 20, '12m', *G3[:3], *G3[3:])
    flat = list(tsim._cached_flat)
    return _run_regime_inner(flat, flat, 0, 6, 3, 3, 6, 3, reg, dates, tsim._price_arr, tsim._bench_arr,
        tsim._has_bench, tsim._date_row_indices, len(dates), None, None, None, None,
        stop_loss_o=None, trailing_stop_o=None, stop_loss_d=None, trailing_stop_d=None)
combos = [(v, q, g, 100-v-q-g) for v in range(0, 45, 5) for q in range(0, 45, 5)
          for g in range(10, 75, 5) if 10 <= 100-v-q-g <= 60]
print(f'[기간] {LO}~{HI}  풀그리드 {len(combos)}조합 (TurboSim 정확 sim)')
# --- 검증: _sp0 overlay ON 랭킹 vs composite_rank ---
ar0, dates0, jcr0 = load('_sp0')
tv = TurboSimulator(ar0, dates0, prices); tv._use_overlay = True
tv._ensure_cache(0.15, 0.0, 0.55, 0.30, 0.4, 20, '12m', *G3[:3], *G3[3:])
mid = dates0[len(dates0)//2]
i = dates0.index(mid); rw = tv._cached_partials  # 재계산 랭킹 확인
# reweighted 랭킹 직접
tv2 = tv._vectorized_reweight  # not used; use flat rank check via _ensure rebuild
# 간이 검증: overlay ON으로 점수 재계산 후 rank vs jcr
pre = tv._preextracted[mid]; ov = tv._overlay_pre[mid]
(tk, vs, qs, gs, ms, gsub, pr, ci, m6, m61, m12, m121) = pre
graw = 0.4*gsub['rev_z'] + 0.4*gsub['oca_z'] + 0.2*gsub['gp_growth_z']
gstd = (graw - graw.mean())/graw.std() if graw.std() > 0 else graw*0
sc = 0.15*vs + 0.0*qs + 0.55*gstd + 0.30*m12 + ov
order = np.argsort(-sc); myrank = {tk[order[k]]: k+1 for k in range(len(tk))}
common = [t for t in myrank if t in jcr0[mid]]
top10 = sum(1 for t in common if myrank[t] <= 10 and jcr0[mid][t] <= 10)/max(1, sum(1 for v in jcr0[mid].values() if v <= 10))
exact = sum(1 for t in common if myrank[t] == jcr0[mid][t])
print(f'[검증] {mid} TurboSim(overlay ON) vs composite_rank: 정확 {exact}/{len(common)} ({exact/len(common)*100:.0f}%), top10교집합 {top10*100:.0f}%')
print('  (growth는 TurboSim이 서브팩터서 재계산→페널티 종목만 소폭 차이, 상대비교엔 무해)\n')
# --- production-config + 풀스윕, overlay ON ---
print(f"{'base':<16}{'prodCal(V15Q0G55M30)':>22}{'   재최적best':>20}")
best = {}
for folder in FOLDERS:
    ar, dates, jcr = load(folder)
    if len(dates) < 30: print(f'{LBL.get(folder,folder)}: 데이터부족'); continue
    reg = calc_reg(dates)
    tsim = TurboSimulator(ar, dates, prices); tsim._use_overlay = True
    prod = regbt(tsim, dates, reg, 15, 0, 55, 30)
    res = sorted([(v,q,g,m,*[regbt(tsim,dates,reg,v,q,g,m).get(k,0) for k in ['calmar','cagr','mdd']]) for v,q,g,m in combos], key=lambda x:-x[4])
    best[folder] = res[0]
    b = res[0]
    print(f'{LBL.get(folder,folder):<16}{prod["calmar"]:>8.2f} (CAGR{prod["cagr"]:.0f} MDD{prod["mdd"]:.0f})   best {b[4]:.2f} V{b[0]}Q{b[1]}G{b[2]}M{b[3]}')
print(f"\n{'='*55}")
for f in FOLDERS:
    if f in best: b = best[f]; print(f'  {LBL.get(f,f):<16} 재최적 best Cal {b[4]:.2f} (CAGR{b[5]:.0f} MDD{b[6]:.0f})')
