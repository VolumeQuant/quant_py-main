# -*- coding: utf-8 -*-
"""1.6(최신분기가중) vs 균등TTM 격차가 어디서 오나 — 과열캡(진짜) vs 밸류(노이즈) 분리.
corp-OFF: _sp0b_co(1.6) vs _sp0c_co(균등). 고정 config.
overlay ON(과열캡포함) 격차 vs overlay OFF(밸류만) 격차. 차이 = 과열캡 기여."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def ba(s):
    r = s.pct_change(fill_method=None); ev = r[(r < -0.33) | (r > 0.45)]; s2 = s.copy()
    for d, rt in ev.items():
        f = 1 + rt
        if 0.02 < abs(f) < 50: s2.loc[s2.index < d] *= f
    return s2
prices = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_2017*_2026061*.parquet')))[-1]).replace(0,np.nan).apply(ba)
kc = pd.read_parquet(os.path.join(PROJ,'data_cache','kospi_yf.parquet')).iloc[:,0]
ma20=kc.rolling(20).mean(); ma80=kc.rolling(80).mean()
def calc_reg(ds):
    reg={}; md=True; stk=0; ss=None
    for d in ds:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md; continue
        s=bool(ma20[ts]>ma80[ts])
        if s==ss: stk+=1
        else: stk=1; ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
G3=('rev_z','oca_z','gp_growth_z',0.4,0.4,0.2)
def load(folder):
    ar,dates={}, []
    for f in sorted(glob.glob(os.path.join(PROJ,folder,'ranking_*.json'))):
        dt=os.path.basename(f)[8:16]
        if dt.isdigit() and len(dt)==8 and dt>='20190102': ar[dt]=json.load(open(f,encoding='utf-8'))['rankings']; dates.append(dt)
    return ar,sorted(dates)
A,dA=load('_sp0b_co'); B,dB=load('_sp0c_co')
common=sorted(set(dA)&set(dB)); reg=calc_reg(common)
def cal(ar, overlay):
    t=TurboSimulator({d:ar[d] for d in common}, common, prices, overheat_w=0.2); t._use_overlay=overlay; t._use_stored_growth=True
    t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:])
    flat=list(t._cached_flat)
    return _run_regime_inner(flat,flat,0,6,3,3,6,3,reg,common,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(common),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None).get('calmar',0)
print(f"[{common[0]}~{common[-1]} {len(common)}일] 1.6 vs 균등TTM 격차 분해")
for ovl,lbl in [(True,'overlay ON (과열캡+mom10+vollow 포함)'),(False,'overlay OFF (밸류·성장·모멘텀만)')]:
    a=cal(A,ovl); b=cal(B,ovl)
    print(f"\n{lbl}:")
    print(f"  1.6 {a:.3f}  vs  균등 {b:.3f}   격차(1.6−균등) {a-b:+.3f}")
print(f"\n→ overlay ON 격차 >> OFF 격차 면 = 1.6 이점은 과열캡에서 옴(진짜, 유지정당). 둘 다 비슷/작으면 노이즈.")
