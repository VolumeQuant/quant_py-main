# -*- coding: utf-8 -*-
"""최종 클린 (같은배치): _sp0b(annual) vs _sp2b(TTM), 둘 다 오늘데이터+STORE_PEN+최근가중.
같은 배치라 growth/overlay 동일 → 오직 value(annual PER vs TTM PER)만 차이 = 완벽 isolation."""
import sys,io,os,glob,json
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
import numpy as np,pandas as pd
from turbo_simulator import TurboSimulator,_run_regime_inner
PROJ=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def ba(s):
    r=s.pct_change(fill_method=None);ev=r[(r<-0.33)|(r>0.45)];s2=s.copy()
    for d,rt in ev.items():
        f=1+rt
        if 0.02<abs(f)<50:s2.loc[s2.index<d]*=f
    return s2
prices=pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_2017*_2026061*.parquet')))[-1]).replace(0,np.nan).apply(ba)
kc=pd.read_parquet(os.path.join(PROJ,'data_cache','kospi_yf.parquet')).iloc[:,0]
ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
def calc_reg(ds):
    reg={};md=True;stk=0;ss=None
    for d in ds:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)):reg[d]=md;continue
        s=bool(ma20[ts]>ma80[ts])
        if s==ss:stk+=1
        else:stk=1;ss=s
        if stk>=5 and md!=s:md=s
        reg[d]=md
    return reg
G3=('rev_z','oca_z','gp_growth_z',0.4,0.4,0.2)
def load(folder):
    ar,dates={},[]
    for f in sorted(glob.glob(os.path.join(PROJ,folder,'ranking_*.json'))):
        dt=os.path.basename(f)[8:16]
        if dt.isdigit() and len(dt)==8:ar[dt]=json.load(open(f,encoding='utf-8'))['rankings'];dates.append(dt)
    return ar,sorted(dates)
def regbt(t,dates,reg,v,q,g,m):
    t._ensure_cache(v/100,q/100,g/100,m/100,0.4,20,'12m',*G3[:3],*G3[3:])
    flat=list(t._cached_flat)
    return _run_regime_inner(flat,flat,0,6,3,3,6,3,reg,dates,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(dates),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None).get('calmar',0)
combos=[(v,q,g,100-v-q-g) for v in range(0,45,5) for q in range(0,45,5) for g in range(10,75,5) if 10<=100-v-q-g<=60]
ar0,d0=load('_sp0b');ar2,d2=load('_sp2b')
common=sorted(set(d0)&set(d2));reg=calc_reg(common)
print(f"_sp0b {len(d0)} _sp2b {len(d2)} 공통 {len(common)}일 (같은배치)")
gm=[];oh=[]
for d in common[::200]:
    sm={x['ticker']:(x.get('growth_s'),x.get('overheat_pen')) for x in ar0[d]}
    for x in ar2[d][:30]:
        a=sm.get(x['ticker'])
        if a and a[0] is not None and x.get('growth_s') is not None: gm.append(abs(a[0]-x['growth_s']))
        if a and a[1] is not None and x.get('overheat_pen') is not None: oh.append(abs(a[1]-x['overheat_pen']))
print(f"growth_s 차 {np.mean(gm):.4f}, overheat_pen 차 {np.mean(oh):.4f} (둘다~0이면 완벽 클린)\n")
for ow in [0.2,0.0]:
    print(f"=== 과열캡 {ow} (같은배치, value만 차이) ===")
    for ar,lbl in [(ar0,'annual value'),(ar2,'TTM value')]:
        arc={d:ar[d] for d in common}
        t=TurboSimulator(arc,common,prices,overheat_w=ow);t._use_overlay=True;t._use_stored_growth=True
        best=max([(*c,regbt(t,common,reg,*c)) for c in combos],key=lambda x:x[4])
        v0=regbt(t,common,reg,0,0,55,45);v15=regbt(t,common,reg,15,0,55,30)
        print(f"  {lbl:<14}: best V{best[0]}Q{best[1]}G{best[2]}M{best[3]}={best[4]:.3f} | V0={v0:.3f} V15={v15:.3f} 한계={v15-v0:+.3f}")
print("\n→ V0가 양쪽 일치=완벽클린. annual best>TTM best & annual 한계>TTM 한계면 순수 value 우월 확정.")
