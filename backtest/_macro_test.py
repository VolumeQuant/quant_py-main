# -*- coding: utf-8 -*-
"""거시 온도계 1차 배치 — '어떤 거시국면에서 밸류틸트가 먹히나' 여러 가설 동시 테스트.
production-faithful(recent_ca ON). 밸류틸트=V25G45M30 vs base V15G55M30. flat stitching."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
import _macro_features as MF
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
BASE=(15,0,55,30);VAL=(25,0,45,30)
mac=MF.build(dall)
def run(t,sub,reg,mask):
    fb=flat_of(t,BASE);fv=flat_of(t,VAL)
    st=[ (fv[i] if mask.get(sub[i],False) else fb[i]) for i in range(len(sub)) ]
    r=_run_regime_inner(fb,st,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    return r.get('calmar',0),r.get('mdd',0),r.get('total',0)
tF=make(dall);regF=calc_reg(dall)
base_cal=run(tF,dall,regF,{})[0]
# 거시 boost일만 (defense는 cash라 무의미) — 조건은 boost일에만 ON
boost=set(d for d in dall if regF[d])
def cond_mask(fn):
    return {d:(fn(mac.loc[d]) and d in boost) for d in dall}
CONDS=[
 ('금리 인하중 아님 rate_dir>=0',      lambda r: r.rate_dir>=0),
 ('금리 인하중(반대) rate_dir<-0.1',   lambda r: r.rate_dir<-0.1),
 ('시장금리 상승 ktb3_dir>0',          lambda r: r.ktb3_dir>0),
 ('고금리레벨 rate>=2.5',              lambda r: r.rate>=2.5),
 ('인플레 높음 cpi_yoy>2.5',           lambda r: r.cpi_yoy>2.5),
 ('인플레 가속 infl_chg>0',            lambda r: r.infl_chg>0),
 ('수익률곡선 평탄/역전 curve<0.2',    lambda r: r.curve<0.2),
 ('원화약세 fx_mom>2',                 lambda r: r.fx_mom>2),
 ('미제조업 둔화 mfg_yoy<0',           lambda r: r.mfg_yoy<0),
 ('복합:고금리&인플레 rate>=2&cpi>2.5',lambda r: r.rate>=2.0 and r.cpi_yoy>2.5),
]
print(f"base(틸트無) full Calmar {base_cal:.3f} | 밸류틸트 ON 조건별 (boost일만)\n")
print(f"{'조건':<32}{'ON일수':>6}{'full Cal':>9}{'Δ':>7}{'MDD':>6}  연도Δ")
yrs=['2019','2020','2021','2022','2023','2024','2025','2026']
for nm,fn in CONDS:
    mask=cond_mask(fn)
    non=sum(mask.values())
    c=run(tF,dall,regF,mask)
    # 연도별 Δ
    yd=[]
    for y in yrs:
        sub=[d for d in dall if d[:4]==y]
        if len(sub)<20:continue
        t=make(sub);reg=calc_reg(sub)
        b=run(t,sub,reg,{})[0]; o=run(t,sub,reg,{d:mask[d] for d in sub})[0]
        if abs(o-b)>=0.05: yd.append(f"{y[2:]}{o-b:+.1f}")
    print(f"{nm:<32}{non:>6}{c[0]:>9.3f}{c[0]-base_cal:>+7.3f}{c[1]:>6.1f}  {' '.join(yd)}")
print("\n[완료]")
