# -*- coding: utf-8 -*-
"""TTM 우위 견고성 검증 (2026-06-16): 가격민감도 + 인접CV + LOWO. 같은배치 _sp0b/_sp2b."""
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
def load(folder,drop=None):
    ar,dates={},[]
    for f in sorted(glob.glob(os.path.join(PROJ,folder,'ranking_*.json'))):
        dt=os.path.basename(f)[8:16]
        if dt.isdigit() and len(dt)==8:
            r=json.load(open(f,encoding='utf-8'))['rankings']
            if drop: r=[x for x in r if x['ticker'] not in drop]
            ar[dt]=r;dates.append(dt)
    return ar,sorted(dates)
def mk(ar,dates,px):
    t=TurboSimulator(ar,dates,px,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True;return t
def cal(t,dates,reg,v,q,g,m,slots=3,entry=3,exit_=6):
    t._ensure_cache(v/100,q/100,g/100,m/100,0.4,20,'12m',*G3[:3],*G3[3:])
    flat=list(t._cached_flat)
    return _run_regime_inner(flat,flat,0,exit_,slots,entry,exit_,slots,reg,dates,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(dates),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None).get('calmar',0)
AB=(10,5,55,30); TB=(15,0,45,40); PROD=(15,0,55,30)  # annual_best, ttm_best, production
ar0,d0=load('_sp0b');ar2,d2=load('_sp2b');common=sorted(set(d0)&set(d2));reg=calc_reg(common)
arc0={d:ar0[d] for d in common};arc2={d:ar2[d] for d in common}
pxfiles=sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_*_2026061*.parquet')))
print("=== ① 가격파일 민감도 (annual-best vs TTM-best, S3) ===")
for pf in pxfiles:
    px=pd.read_parquet(pf).replace(0,np.nan).apply(ba)
    a=cal(mk(arc0,common,px),common,reg,*AB); tt=cal(mk(arc2,common,px),common,reg,*TB)
    ap=cal(mk(arc0,common,px),common,reg,*PROD); tp=cal(mk(arc2,common,px),common,reg,*PROD)
    print(f"  {os.path.basename(pf)[10:]}: best→ ann {a:.2f} TTM {tt:.2f} (Δ{tt-a:+.2f}) | 운영config→ ann {ap:.2f} TTM {tp:.2f} (Δ{tp-ap:+.2f})")
px=pd.read_parquet(pxfiles[-1]).replace(0,np.nan).apply(ba)
print("\n=== ② 인접CV (TTM-best V15Q0G45M40 주변, S3) ===")
t2=mk(arc2,common,px); cals=[]
for dv in(-5,0,5):
    for dg in(-5,0,5):
        v=15+dv; g=45+dg; m=100-v-0-g
        if 10<=m<=60 and v>=10:
            c=cal(t2,common,reg,v,0,g,m); cals.append(c)
print(f"  인접 {len(cals)}개: {[f'{c:.2f}' for c in cals]}")
print(f"  평균 {np.mean(cals):.2f}, CV {np.std(cals)/np.mean(cals):.3f} (<0.10~0.30=안정)")
print("\n=== ③ LOWO (최대수익 종목 제외 후 annual-best vs TTM-best, S3) ===")
WINNERS={'000660':'SK하이닉스','080220':'제주반도체','187870':'디바이스','042700':'한미반도체'}
a0=cal(mk(arc0,common,px),common,reg,*AB); t0=cal(mk(arc2,common,px),common,reg,*TB)
print(f"  (없음): ann {a0:.2f} TTM {t0:.2f} Δ{t0-a0:+.2f}")
for tk,nm in WINNERS.items():
    a0b,d0b=load('_sp0b',drop={tk}); a2b,d2b=load('_sp2b',drop={tk})
    cm=sorted(set(d0b)&set(d2b)); rg=calc_reg(cm)
    aa=cal(mk({d:a0b[d] for d in cm},cm,px),cm,rg,*AB); tt=cal(mk({d:a2b[d] for d in cm},cm,px),cm,rg,*TB)
    print(f"  -{nm}: ann {aa:.2f} TTM {tt:.2f} Δ{tt-aa:+.2f}")
print("\n→ 가격민감도서 부호 유지 + 인접CV 안정 + LOWO 모두 TTM>annual이면 진짜. 하나라도 뒤집히면 노이즈.")
