# -*- coding: utf-8 -*-
"""배포 검증: 재생성 state_lump/(필터ON) vs 현재 state/(필터없음) — 실제 FG 결과 비교.
Calmar 전체+WF, 디바이스(187870) 2026 매수권 강등, 제주반도체(080220) 보존 확인."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def ba(s):
    r=s.pct_change(fill_method=None);ev=r[(r<-0.33)|(r>0.45)];s2=s.copy()
    for d,rt in ev.items():
        f=1+rt
        if 0.02<abs(f)<50: s2.loc[s2.index<d]*=f
    return s2
prices=pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_2017*_202606*.parquet')))[-1]).replace(0,np.nan).apply(ba)
kc=pd.read_parquet(os.path.join(PROJ,'data_cache','kospi_yf.parquet')).iloc[:,0];ma20=kc.rolling(20).mean();ma80=kc.rolling(80).mean()
def calc_reg(ds):
    reg={};md=True;stk=0;ss=None
    for d in ds:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md;continue
        s=bool(ma20[ts]>ma80[ts])
        if s==ss: stk+=1
        else: stk=1;ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
G3=('rev_z','oca_z','gp_growth_z',0.4,0.4,0.2)
def load(folder):
    ar={}
    for f in sorted(glob.glob(os.path.join(PROJ,folder,'ranking_*.json'))):
        dt=os.path.basename(f)[8:16]
        if dt.isdigit() and len(dt)==8 and dt>='20190102':
            ar[dt]=json.load(open(f,encoding='utf-8'))['rankings']
    return ar
def runbt(ar,sub):
    reg=calc_reg(sub)
    t=TurboSimulator({d:ar[d] for d in sub},sub,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True
    t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:]);flat=list(t._cached_flat)
    r=_run_regime_inner(flat,flat,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    a=np.asarray(r['_daily_rets'],float);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return (cagr/abs(mdd) if mdd<0 else 0),cagr,mdd
base=load('state'); lump=load('state_lump')
common=sorted(set(base)&set(lump))
print(f"[검증] 공통 {common[0]}~{common[-1]} {len(common)}일  (base {len(base)} / lump {len(lump)})\n")
segs=[('전체',common[0],common[-1]),('19-21',common[0],'20211231'),('22-23약세','20220101','20231231'),('24-26','20240101',common[-1])]
print(f"  {'구간':10s}{'base Cal':>9s}{'필터 Cal':>9s}{'ΔCal':>7s}  {'base MDD':>9s}{'필터 MDD':>9s}")
for nm,lo,hi in segs:
    sub=[d for d in common if lo<=d<=hi]
    b=runbt(base,sub); l=runbt(lump,sub)
    print(f"  {nm:10s}{b[0]:>9.2f}{l[0]:>9.2f}{l[0]-b[0]:>+7.2f}  {b[2]:>8.1f}%{l[2]:>8.1f}%")
# 디바이스/제주 진입 비교 (실제 저장 rank)
def entry(ar,tk,lo='20190102',hi='20261231'):
    c=0;ds=[]
    for dt,rows in ar.items():
        if not(lo<=dt<=hi): continue
        for r in rows:
            if r['ticker']==tk and r.get('rank',99)<=3: c+=1; ds.append(dt)
    return c,ds
for tk,nm in [('187870','디바이스'),('080220','제주반도체'),('089970','브이엠')]:
    bc,_=entry(base,tk); lc,lds=entry(lump,tk)
    print(f"\n  {nm}({tk}) rank<=3 진입: base {bc}일 → 필터 {lc}일", end='')
    bc26,_=entry(base,tk,'20260101'); lc26,_=entry(lump,tk,'20260101')
    print(f"  (2026: {bc26}→{lc26}일)")
# 디바이스 2026-05~06 실제 저장순위
print("\n  [디바이스 2026-05~06 state_lump 실제 순위]")
for dt in sorted(d for d in lump if '20260512'<=d<='20260605'):
    dv=[r for r in lump[dt] if r['ticker']=='187870']
    print(f"    {dt}: {'rank '+str(dv[0]['rank'])+' (growth '+format(dv[0]['growth_s'],'.2f')+')' if dv else 'Top밖'}")
