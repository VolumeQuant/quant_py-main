# -*- coding: utf-8 -*-
"""WF 검증 (2026-06-16): annual best vs TTM best를 기간분할(약세장 포함)로 검증.
강세장 과적합인지 약세장에서도 holding 인지 = 표준 채택기준. 같은배치 _sp0b/_sp2b."""
import sys,io,os,glob,json,time
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
def regbt(t,dates,reg,v,q,g,m,entry=3,exit_=6,slots=3):
    t._ensure_cache(v/100,q/100,g/100,m/100,0.4,20,'12m',*G3[:3],*G3[3:])
    flat=list(t._cached_flat)
    return _run_regime_inner(flat,flat,0,exit_,slots,entry,exit_,slots,reg,dates,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(dates),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None).get('calmar',0)
ar0,d0=load('_sp0b');ar2,d2=load('_sp2b')
common=sorted(set(d0)&set(d2))
# S3 풀그리드로 각 기간 best 찾고 + 전체best config를 각 기간서 평가
combos=[(v,q,g,100-v-q-g) for v in [10,15,20,25,30] for q in [0,5,10] for g in range(15,70,5) if 10<=100-v-q-g<=60]
SPLITS=[('전체','20190102','20261231'),('2019-21','20190102','20211231'),('2022-23약세','20220101','20231231'),('2024-26강세','20240101','20261231')]
print("S3(E3X6) 밸류강제 V>=10, 기간별 best (TurboSim 기간당 1회)\n")
print(f"{'기간':<14}{'annual best':<24}{'TTM best':<24}{'TTM-ann':>8}")
fullbest={}
for nm,lo,hi in SPLITS:
    sub=[d for d in common if lo<=d<=hi]
    if len(sub)<30: continue
    reg=calc_reg(sub)
    res={}
    for ar,lbl in [(ar0,'annual'),(ar2,'TTM')]:
        arc={d:ar[d] for d in sub}
        t=TurboSimulator(arc,sub,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True
        b=max([(*c,regbt(t,sub,reg,*c)) for c in combos],key=lambda x:x[4])
        res[lbl]=b
        if nm=='전체': fullbest[lbl]=b[:4]
    a=res['annual'];tt=res['TTM']
    print(f"{nm:<14}V{a[0]}Q{a[1]}G{a[2]}M{a[3]}={a[4]:.2f}{'':<6}V{tt[0]}Q{tt[1]}G{tt[2]}M{tt[3]}={tt[4]:.2f}{'':<6}{tt[4]-a[4]:>+7.2f}")
# 전체best config를 각 기간서 평가 (overfit 체크: 전체best가 약세장서도 버티나)
print(f"\n[전체-best config를 각 기간서 평가] annual={fullbest.get('annual')} TTM={fullbest.get('TTM')}")
print(f"{'기간':<14}{'annual':>10}{'TTM':>10}{'TTM-ann':>9}")
for nm,lo,hi in SPLITS:
    sub=[d for d in common if lo<=d<=hi]
    if len(sub)<30: continue
    reg=calc_reg(sub)
    row=[]
    for ar,lbl in [(ar0,'annual'),(ar2,'TTM')]:
        arc={d:ar[d] for d in sub}
        t=TurboSimulator(arc,sub,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True
        row.append(regbt(t,sub,reg,*fullbest[lbl]))
    print(f"{nm:<14}{row[0]:>10.2f}{row[1]:>10.2f}{row[1]-row[0]:>+9.2f}")
print("\n→ TTM이 약세장(2022-23) WF서도 annual보다 크면 진짜. 약세장서 붕괴하면 강세장 과적합=기각.")
