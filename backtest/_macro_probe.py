# -*- coding: utf-8 -*-
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
import _macro_features as MF
PROJ=os.path.dirname(os.path.dirname(os.path.abspath(__file__)));RC=0.3
def ba(s):
    r=s.pct_change(fill_method=None);ev=r[(r<-0.33)|(r>0.45)];s2=s.copy()
    for d,rt in ev.items():
        f=1+rt
        if 0.02<abs(f)<50:s2.loc[s2.index<d]*=f
    return s2
prices=pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_2017*_20260*.parquet')))[-1]).replace(0,np.nan).apply(ba)
kc=pd.read_parquet(os.path.join(PROJ,'data_cache','kospi_yf.parquet')).iloc[:,0];ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
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
ar_all={};dall=[]
for f in sorted(glob.glob(os.path.join(PROJ,'state','ranking_*.json'))):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102':ar_all[dt]=json.load(open(f,encoding='utf-8'))['rankings'];dall.append(dt)
dall=sorted(dall)
def patch(t,sd):
    for date,arr in t._overlay_pre.items():
        if arr is None:continue
        rk=sd.get(date)
        if rk is None:continue
        for j,s in enumerate(rk):
            if s.get('recent_ca'):arr[j]-=RC*float(s['recent_ca'])
def make(sub):
    sd={d:ar_all[d] for d in sub};t=TurboSimulator(sd,sub,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True;patch(t,sd);return t
def fl(t,w):
    t._ensure_cache(w[0]/100,w[1]/100,w[2]/100,w[3]/100,0.4,20,'12m',*G3[:3],*G3[3:]);return list(t._cached_flat)
BASE=(15,0,55,30);VALW=(20,0,55,25)
mac=MF.build(dall)
def run(t,sub,reg,mask):
    fb=fl(t,BASE);fv=fl(t,VALW);st=[(fv[i] if mask.get(sub[i],False) else fb[i]) for i in range(len(sub))]
    r=_run_regime_inner(fb,st,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    return r.get('calmar',0),r.get('mdd',0)
tF=make(dall);regF=calc_reg(dall);boost=set(d for d in dall if regF[d]);bc=run(tF,dall,regF,{})[0]
print(f"base {bc:.3f} | 인플레가속→약밸류(V20G55M25) 정밀\n")
print("[임계 민감도] infl_chg>thr (full Δ)")
for thr in [0.1,0.2,0.3,0.4,0.5]:
    m={d:(mac.loc[d].infl_chg>thr and d in boost) for d in dall}
    c=run(tF,dall,regF,m);print(f"  thr {thr}: ON {sum(m.values())}일  Cal {c[0]:.3f}  Δ{c[0]-bc:+.3f}  MDD{c[1]:.1f}%")
print("\n[연도별 Δ] thr0.3 (한 해만 +면 노이즈)")
m3={d:(mac.loc[d].infl_chg>0.3 and d in boost) for d in dall}
for y in ['2019','2020','2021','2022','2023','2024','2025','2026']:
    sub=[d for d in dall if d[:4]==y]
    if len(sub)<20:continue
    t=make(sub);reg=calc_reg(sub);b=run(t,sub,reg,{})[0];o=run(t,sub,reg,{d:m3[d] for d in sub})[0]
    on=sum(1 for d in sub if m3.get(d))
    print(f"  {y}: ON {on:>3}일  {b:.2f}→{o:.2f}  Δ{o-b:+.2f}")
print("\n[완료]")
