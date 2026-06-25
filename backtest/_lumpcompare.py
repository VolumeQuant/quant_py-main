# -*- coding: utf-8 -*-
"""lumpiness ON(state/) vs OFF(state_lumpoff/) 결판 — production-faithful harness
(adj 가격 + recent_ca 오버레이). 구간별 Calmar/MDD. 24-26 -0.33이 진짜인지 측정artifact인지."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices = pd.read_parquet(sorted(glob.glob(P + '/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0, np.nan)
kc = pd.read_parquet(P + '/data_cache/kospi_yf.parquet').iloc[:, 0]; ma20=kc.rolling(20).mean(); ma80=kc.rolling(80).mean()
G3 = ('rev_z','oca_z','gp_growth_z',0.4,0.4,0.2)
def calc_reg(ds):
    reg={};md=True;stk=0;ss=None
    for d in ds:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md;continue
        s=bool(ma20[ts]>ma80[ts]); stk=stk+1 if s==ss else 1; ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
def load(folder):
    ar,dates={},[]
    for f in sorted(glob.glob(os.path.join(P,folder,'ranking_*.json'))):
        dt=os.path.basename(f)[8:16]
        if dt.isdigit() and len(dt)==8 and dt>='20190102': ar[dt]=json.load(open(f,encoding='utf-8'))['rankings'];dates.append(dt)
    return ar,sorted(dates)
def runbt(ar, sub):
    reg=calc_reg(sub)
    t=TurboSimulator({d:ar[d] for d in sub},sub,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True
    for d in sub:
        tkn=t._preextracted[d][0]; fd={x['ticker']:x for x in ar[d]}
        t._overlay_pre[d]=np.array([0.2*(fd[tk].get('overheat_pen')or 0)+0.05*(fd[tk].get('mom_10_z')or 0)
                                    +0.06*(fd[tk].get('vol_low_z')or 0)-0.3*(fd[tk].get('recent_ca')or 0) for tk in tkn])
    t._cached_key=None; t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:]);flat=list(t._cached_flat)
    r=_run_regime_inner(flat,flat,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    return r.get('calmar',0),r.get('cagr',0)*100,r.get('mdd',0)*100
arON,dON=load('state'); arOFF,dOFF=load('state_lumpoff')
common=sorted(set(dON)&set(dOFF))
print(f"[lumpiness ON vs OFF 풀재생성 결판] 공통 {len(common)}일 ({common[0]}~{common[-1]})")
print(f"  ON(state) {len(dON)}일 / OFF(state_lumpoff) {len(dOFF)}일\n")
print(f"  {'구간':10s}{'OFF Cal':>9s}{'ON Cal':>9s}{'Δ(ON-OFF)':>11s}{'OFF MDD':>9s}{'ON MDD':>9s}")
for nm,lo,hi in [('전체',common[0],common[-1]),('19-21',common[0],'20211231'),('22-23약세','20220101','20231231'),('24-26','20240101',common[-1])]:
    sub=[d for d in common if lo<=d<=hi]
    off=runbt(arOFF,sub); on=runbt(arON,sub)
    print(f"  {nm:10s}{off[0]:>9.3f}{on[0]:>9.3f}{on[0]-off[0]:>+11.3f}{off[2]:>8.1f}%{on[2]:>8.1f}%")
# 디바이스 진입 비교 (저장 rank)
def ent(ar,tk,lo='20240101'):
    return sum(1 for d,rows in ar.items() if d>=lo for r in rows if r['ticker']==tk and r.get('rank',99)<=3)
print(f"\n  디바이스 rank<=3 진입(2024+): OFF {ent(arOFF,'187870')}일 → ON {ent(arON,'187870')}일")
print(f"  제주반도체 rank<=3 진입(2024+): OFF {ent(arOFF,'080220')}일 → ON {ent(arON,'080220')}일")
