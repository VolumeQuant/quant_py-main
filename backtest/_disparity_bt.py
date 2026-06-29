# -*- coding: utf-8 -*-
"""이격도20 매수차단 풀 BT — 임계 스윕 + base대비 + 제주/SK LOWO. production-faithful(recent_ca ON)."""
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
disp=praw/praw.rolling(20).mean()  # 이격도20 (원주가 기준)
di={d:i for i,d in enumerate(praw.index.strftime('%Y%m%d'))}; pcol={c:j for j,c in enumerate(praw.columns)}; darr=disp.values
def disp_of(tk,d):
    i=di.get(d);j=pcol.get(tk)
    if i is None or j is None: return None
    v=darr[i,j]; return float(v) if v==v else None
kc=pd.read_parquet(os.path.join(PROJ,'data_cache','kospi_yf.parquet')).iloc[:,0];ma20k=kc.rolling(20).mean();ma80k=kc.rolling(80).mean()
def calc_reg(ds):
    reg={};md=True;stk=0;ss=None
    for d in ds:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80k.get(ts,np.nan)):reg[d]=md;continue
        s=bool(ma20k[ts]>ma80k[ts])
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
def patch(t,sd,thr=None):
    for date,arr in t._overlay_pre.items():
        if arr is None:continue
        rk=sd.get(date)
        if rk is None:continue
        for j,s in enumerate(rk):
            if s.get('recent_ca'):arr[j]-=RC*float(s['recent_ca'])
            if thr is not None:
                dv=disp_of(s['ticker'],date)
                if dv is not None and dv>thr: arr[j]-=100.0  # 매수차단(점수 바닥)
def make(sub,thr=None,exclude=None):
    sd={d:[r for r in ar_all[d] if not exclude or r['ticker'] not in exclude] for d in sub}
    t=TurboSimulator(sd,sub,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True;patch(t,sd,thr);return t
def run(sub,thr=None,exclude=None):
    reg=calc_reg(sub);t=make(sub,thr,exclude)
    t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:])
    f=list(t._cached_flat)
    r=_run_regime_inner(f,f,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    return r.get('calmar',0),r.get('mdd',0),r.get('total',0)
print("이격도20 매수차단 BT (production-faithful, recent_ca ON)\n")
base=run(dall)
print(f"base(필터無): Calmar {base[0]:.3f}  MDD {base[1]:.1f}%  누적 {base[2]:.0f}%")
print("\n[임계 스윕]")
for thr in [1.5,1.6,1.7,1.8,2.0]:
    # 차단되는 매수권 건수
    blocked=sum(1 for d in dall for r in ar_all[d] if r.get('rank',99)<=6 and (disp_of(r['ticker'],d) or 0)>thr)
    c=run(dall,thr)
    print(f"  이격도>{thr}: Calmar {c[0]:.3f} (Δ{c[0]-base[0]:+.3f})  MDD {c[1]:.1f}%  차단(rank≤6) {blocked}건")
print("\n[LOWO @ 이격도>1.8] 승자 제외해도 무해한가")
for tk,nm in [('080220','제주반도체'),('000660','SK하이닉스'),('033100','제룡전기'),('131290','티에스이')]:
    b=run(dall,None,{tk})[0]; f=run(dall,1.8,{tk})[0]
    print(f"  −{nm}: base {b:.3f} → 필터 {f:.3f}  Δ{f-b:+.3f}")
print("\n[완료]")
