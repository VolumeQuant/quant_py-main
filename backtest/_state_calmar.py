# -*- coding: utf-8 -*-
"""재생성된 production state/ 로 고정config BT → 어제 보고한 Calmar(corp-OFF≈4.31) 재현 확인.
state/(현재전략 재생성) vs _sp0b_co(어제 기준) 직접 비교. 같으면 재생성 정합."""
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
def runbt(folder, sub, reg):
    ar,_=load(folder)
    t=TurboSimulator({d:ar[d] for d in sub}, sub, prices, overheat_w=0.2); t._use_overlay=True; t._use_stored_growth=True
    t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:])
    flat=list(t._cached_flat)
    r=_run_regime_inner(flat,flat,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    return r.get('calmar',0), r.get('cagr',0), r.get('mdd',0)
_,dS=load('state'); _,dC=load('_sp0b_co')
common=sorted(set(dS)&set(dC)); reg=calc_reg(common)
print(f"[공통 {common[0]}~{common[-1]} {len(common)}일] 고정config V15Q0G55M30 12m E3X6S3")
cs=runbt('state',common,reg); cc=runbt('_sp0b_co',common,reg)
print(f"\n  재생성 state/ (현재전략)  : Calmar {cs[0]:.3f}  CAGR {cs[1]*100:.0f}%  MDD {cs[2]*100:.0f}%")
print(f"  _sp0b_co (어제 기준 4.31) : Calmar {cc[0]:.3f}  CAGR {cc[1]*100:.0f}%  MDD {cc[2]*100:.0f}%")
print(f"  차이 {cs[0]-cc[0]:+.3f}")
# state/ 단독 전체기간(최신일까지)도
_,dSf=load('state'); regf=calc_reg(dSf)
csf=runbt('state',dSf,regf)
print(f"\n  재생성 state/ 전체({dSf[0]}~{dSf[-1]} {len(dSf)}일): Calmar {csf[0]:.3f}")
print(f"\n→ state≈_sp0b_co(4.31)면 재생성 정합 + 어제 보고 재현. 문서값 4.43은 gold-standard 미세차(권리락보정 등).")
