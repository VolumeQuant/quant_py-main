# -*- coding: utf-8 -*-
"""범용 2-폴더 비교 (Stage B: 1.6 vs 균등 / Stage C: annual vs TTM).
usage: python _sp_cmp.py <folderA> <labelA> <folderB> <labelB>
출력: 고정config(편향無 핵심) + full-grid best(편향有 참고) + WF 3블록 + 밸류 IC.
같은 harness(overlay+stored_growth, ba prices, regime 20/80/5)."""
import sys, io, os, glob, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fA, lA, fB, lB = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
def ba(s):
    r = s.pct_change(fill_method=None); ev = r[(r < -0.33) | (r > 0.45)]; s2 = s.copy()
    for d, rt in ev.items():
        f = 1 + rt
        if 0.02 < abs(f) < 50: s2.loc[s2.index < d] *= f
    return s2
prices = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ, 'data_cache', 'all_ohlcv_2017*_2026061*.parquet')))[-1]).replace(0, np.nan).apply(ba)
kc = pd.read_parquet(os.path.join(PROJ, 'data_cache', 'kospi_yf.parquet')).iloc[:, 0]
ma20 = kc.rolling(20).mean(); ma80 = kc.rolling(80).mean()
def calc_reg(ds):
    reg = {}; md = True; stk = 0; ss = None
    for d in ds:
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
    ar, dates = {}, []
    for f in sorted(glob.glob(os.path.join(PROJ, folder, 'ranking_*.json'))):
        dt = os.path.basename(f)[8:16]
        if dt.isdigit() and len(dt) == 8 and dt >= '20190102': ar[dt] = json.load(open(f, encoding='utf-8'))['rankings']; dates.append(dt)
    return ar, sorted(dates)
arA, dA = load(fA); arB, dB = load(fB)
common = sorted(set(dA) & set(dB)); reg = calc_reg(common)
COMBOS = [(v, q, g, 100-v-q-g) for v in [10,15,20,25,30] for q in [0,5,10] for g in range(15,70,5) if 10 <= 100-v-q-g <= 60]
MOMS = ['6m','6m-1m','12m','12m-1m']; SLOTS = [(3,3,6),(5,5,10),(10,10,20)]
def mk(ar, sub):
    t = TurboSimulator({d: ar[d] for d in sub}, sub, prices, overheat_w=0.2); t._use_overlay=True; t._use_stored_growth=True
    return t
def cal_fixed(t, sub):
    t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:])
    flat=list(t._cached_flat)
    r=_run_regime_inner(flat,flat,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    return r.get('calmar',0), r.get('cagr',0), r.get('mdd',0)
def best_grid(ar, sub):
    t=mk(ar,sub); best=(-9,None)
    for v,q,g,m in COMBOS:
        for mm in MOMS:
            t._ensure_cache(v/100,q/100,g/100,m/100,0.4,20,mm,*G3[:3],*G3[3:])
            flat=list(t._cached_flat)
            for sl,e,x in SLOTS:
                c=_run_regime_inner(flat,flat,0,x,sl,e,x,sl,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None).get('calmar',0)
                if c>best[0]: best=(c,(v,q,g,m,mm,sl,e,x))
    return best
def value_ic(ar, sub, fwd=20):
    di={d:i for i,d in enumerate(prices.index.strftime('%Y%m%d'))}; arr=prices.values; cols={c:i for i,c in enumerate(prices.columns)}
    ics=[]
    for d in sub:
        if not reg.get(d,True) or d not in di: continue
        i0=di[d]; i1=i0+fwd
        if i1>=len(arr): continue
        vs,fr=[],[]
        for s in ar[d]:
            ci=cols.get(s['ticker'])
            if ci is None: continue
            p0,p1=arr[i0,ci],arr[i1,ci]
            if p0>0 and p1>0 and s.get('value_s') is not None: vs.append(s['value_s']); fr.append(p1/p0-1)
        if len(vs)>30:
            c=np.corrcoef(vs,fr)[0,1]
            if not np.isnan(c): ics.append(c)
    return np.mean(ics) if ics else float('nan')
print(f"[{common[0]}~{common[-1]} {len(common)}일]  A={lA}({fA})  B={lB}({fB})")
print(f"\n=== ① 고정 운영config V15Q0G55M30 12m E3X6S3 (★편향無 핵심지표) ===")
fa=cal_fixed(mk(arA,common),common); fb=cal_fixed(mk(arB,common),common)
print(f"  {lA:<16} Calmar {fa[0]:.3f}  CAGR {fa[1]*100:.1f}%  MDD {fa[2]*100:.1f}%")
print(f"  {lB:<16} Calmar {fb[0]:.3f}  CAGR {fb[1]*100:.1f}%  MDD {fb[2]*100:.1f}%")
print(f"  Δ(B-A) Calmar {fb[0]-fa[0]:+.3f}")
print(f"\n=== ② WF 3블록 고정config Calmar (강건성) ===")
blocks=[('19-21','20190102','20211231'),('22-23','20220101','20231231'),('24-26','20240101','20261231')]
for nm,lo,hi in blocks:
    sub=[d for d in common if lo<=d<=hi]
    if len(sub)<60: continue
    ca=cal_fixed(mk(arA,sub),sub)[0]; cb=cal_fixed(mk(arB,sub),sub)[0]
    print(f"  {nm}: {lA} {ca:.2f}  vs  {lB} {cb:.2f}   Δ {cb-ca:+.2f}")
print(f"\n=== ③ 밸류팩터 IC (value_s vs fwd20d, boost일; 노이즈無 예측력) ===")
print(f"  {lA} {value_ic(arA,common):.4f}  vs  {lB} {value_ic(arB,common):.4f}")
print(f"\n=== ④ full-grid best (V>=10) — ⚠️max-selection 편향 있음, 참고용 ===")
t0=time.time(); ba_=best_grid(arA,common); bb_=best_grid(arB,common)
def fmt(c): return f"V{c[0]}Q{c[1]}G{c[2]}M{c[3]} {c[4]} S{c[5]}(E{c[6]}X{c[7]})"
print(f"  {lA} best {ba_[0]:.3f} @ {fmt(ba_[1])}")
print(f"  {lB} best {bb_[0]:.3f} @ {fmt(bb_[1])}   Δ {bb_[0]-ba_[0]:+.3f}  ({time.time()-t0:.0f}s)")
print(f"\n→ 판정: ①고정config Δ가 결론. ②WF 블록 부호 일관성. ③IC 동등이면 차이는 노이즈. ④best-vs-best는 편향이라 ①과 어긋나면 무시.")
