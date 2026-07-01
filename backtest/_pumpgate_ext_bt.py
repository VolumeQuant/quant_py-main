# -*- coding: utf-8 -*-
"""펌프게이트 성장임계 확장 BT — 이격도>1.4 & growth<X (X 스윕). 미래산업 고성장과열 잡기."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ=os.path.dirname(os.path.dirname(os.path.abspath(__file__)));RC=0.3
def ba(s):
    r=s.pct_change(fill_method=None);ev=r[(r<-0.33)|(r>0.45)];s2=s.copy()
    for d,rt in ev.items():
        f=1+rt
        if 0.02<abs(f)<50:s2.loc[s2.index<d]*=f
    return s2
praw=pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_2017*_20260*.parquet')))[-1]).replace(0,np.nan)
prices=praw.apply(ba)
disp=(praw/praw.rolling(20).mean()).values
di={d:i for i,d in enumerate(praw.index.strftime('%Y%m%d'))};pcol={c:j for j,c in enumerate(praw.columns)}
def dsp(t,d):
    i=di.get(d);j=pcol.get(t)
    return float(disp[i,j]) if (i is not None and j is not None and disp[i,j]==disp[i,j]) else None
kc=pd.read_parquet(os.path.join(PROJ,'data_cache','kospi_yf.parquet')).iloc[:,0];m20=kc.rolling(20).mean();m80=kc.rolling(80).mean()
def calc_reg(ds):
    reg={};md=True;stk=0;ss=None
    for d in ds:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(m80.get(ts,np.nan)):reg[d]=md;continue
        s=bool(m20[ts]>m80[ts])
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
def patch(t,sd,gthr=None):
    for date,arr in t._overlay_pre.items():
        if arr is None:continue
        rk=sd.get(date)
        if rk is None:continue
        for j,s in enumerate(rk):
            if s.get('recent_ca'):arr[j]-=RC*float(s['recent_ca'])
            if gthr is not None:
                dv=dsp(s['ticker'],date)
                if dv is not None and dv>1.4 and (s.get('growth_s') or 0)<gthr: arr[j]-=100.0
def run(sub,gthr=None,exclude=None):
    sd={d:[r for r in ar_all[d] if not exclude or r['ticker'] not in exclude] for d in sub}
    t=TurboSimulator(sd,sub,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True
    patch(t,sd,gthr)
    t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:])
    f=list(t._cached_flat);reg=calc_reg(sub)
    r=_run_regime_inner(f,f,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    return r.get('calmar',0),r.get('mdd',0),r.get('total',0)
base=run(dall)
print(f"base: Calmar {base[0]:.3f} MDD {base[1]:.1f}%\n[이격도>1.4 & 성장<X 매수차단 (X 스윕)]")
for g in [0.5,1.0,1.3,1.5,1.7,2.0]:
    blk=sum(1 for d in dall for r in ar_all[d] if r.get('rank',99)<=6 and (dsp(r['ticker'],d) or 0)>1.4 and (r.get('growth_s') or 0)<g)
    c=run(dall,g)
    print(f"  성장<{g}: Calmar {c[0]:.3f} (Δ{c[0]-base[0]:+.3f}) MDD {c[1]:.1f}% 차단 {blk}건")
print("[LOWO @ 성장<1.5]")
for tk,nm in [('000660','SK'),('080220','제주'),('033100','제룡'),('042700','한미'),('131290','티에스이'),('039030','이오'),('025560','미래산업')]:
    b=run(dall,None,{tk})[0];f=run(dall,1.5,{tk})[0]
    print(f"  −{nm}: {b:.3f}→{f:.3f} Δ{f-b:+.3f}")
print("[완료]")
