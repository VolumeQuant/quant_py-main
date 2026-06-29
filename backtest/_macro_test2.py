# -*- coding: utf-8 -*-
"""거시 온도계 2차 — 국면마다 '다른 옷'(밸류/모멘텀/퀄리티/성장) 양방향 테스트.
가설: 완화기→모멘텀, 긴축/고금리→밸류, 침체우려(역전)→퀄리티. production-faithful."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
import _macro_features as MF
PROJ=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECENT_CA_W=0.3
def ba(s):
    r=s.pct_change(fill_method=None);ev=r[(r<-0.33)|(r>0.45)];s2=s.copy()
    for d,rt in ev.items():
        f=1+rt
        if 0.02<abs(f)<50:s2.loc[s2.index<d]*=f
    return s2
prices=pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_2017*_20260*.parquet')))[-1]).replace(0,np.nan).apply(ba)
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
ar_all={};dall=[]
for f in sorted(glob.glob(os.path.join(PROJ,'state','ranking_*.json'))):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102':
        ar_all[dt]=json.load(open(f,encoding='utf-8'))['rankings'];dall.append(dt)
dall=sorted(dall)
def patch_ca(t,sd):
    for date,arr in t._overlay_pre.items():
        if arr is None:continue
        rk=sd.get(date)
        if rk is None:continue
        for j,s in enumerate(rk):
            if s.get('recent_ca'):arr[j]-=RECENT_CA_W*float(s['recent_ca'])
def make(sub):
    sd={d:ar_all[d] for d in sub}
    t=TurboSimulator(sd,sub,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True
    patch_ca(t,sd);return t
def flat_of(t,w):
    t._ensure_cache(w[0]/100,w[1]/100,w[2]/100,w[3]/100,0.4,20,'12m',*G3[:3],*G3[3:]);return list(t._cached_flat)
BASE=(15,0,55,30)
OUTFITS={'밸류':(25,0,45,30),'모멘텀':(5,0,55,40),'퀄리티':(15,20,45,20),'성장':(10,0,65,25),'밸류약':(20,0,55,25)}
mac=MF.build(dall)
ar_cache={}
def get_t(sub_key,sub):
    if sub_key not in ar_cache: ar_cache[sub_key]=make(sub)
    return ar_cache[sub_key]
def run(t,sub,reg,mask,outfit):
    fb=flat_of(t,BASE);fv=flat_of(t,outfit)
    st=[ (fv[i] if mask.get(sub[i],False) else fb[i]) for i in range(len(sub)) ]
    r=_run_regime_inner(fb,st,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    return r.get('calmar',0),r.get('mdd',0)
tF=make(dall);regF=calc_reg(dall);boost=set(d for d in dall if regF[d])
base_cal=run(tF,dall,regF,{},BASE)[0]
def cmask(fn): return {d:(fn(mac.loc[d]) and d in boost) for d in dall}
# (국면이름, 조건, 후보옷들)
STATES=[
 ('완화기(금리인하) rate_dir<-0.1', lambda r:r.rate_dir<-0.1, ['모멘텀','성장','밸류']),
 ('긴축기 rate_dir>0.2',           lambda r:r.rate_dir>0.2,  ['밸류','밸류약','퀄리티']),
 ('고금리 rate>=3.0',              lambda r:r.rate>=3.0,     ['밸류','밸류약','퀄리티']),
 ('침체우려 curve<0',              lambda r:r.curve<0,       ['퀄리티','밸류','모멘텀']),
 ('인플레둔화 infl_chg<-0.3',      lambda r:r.infl_chg<-0.3, ['모멘텀','성장','퀄리티']),
 ('인플레가속 infl_chg>0.3',       lambda r:r.infl_chg>0.3,  ['밸류','밸류약']),
 ('원화약세 fx_mom>3',             lambda r:r.fx_mom>3,      ['퀄리티','모멘텀']),
]
print(f"base 4.203 | 국면×옷 (full Calmar Δ, +면 그 국면에 그 옷이 맞음)\n")
print(f"{'거시 국면':<26}{'ON일':>5}  "+"  ".join(f"{o:>7}" for o in ['밸류','밸류약','모멘텀','성장','퀄리티']))
for nm,fn,cands in STATES:
    mask=cmask(fn);non=sum(mask.values())
    cells={}
    for o in cands:
        cells[o]=run(tF,dall,regF,mask,OUTFITS[o])[0]-base_cal
    row=f"{nm:<26}{non:>5}  "
    for o in ['밸류','밸류약','모멘텀','성장','퀄리티']:
        row+=f"{(f'{cells[o]:+.2f}' if o in cells else '·'):>7}  "
    print(row)
print("\n[완료]")
