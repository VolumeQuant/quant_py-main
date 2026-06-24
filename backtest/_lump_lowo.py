# -*- coding: utf-8 -*-
import sys, io, os, glob, json, pickle
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
EXCL={'187870','171090'}  # 디바이스, 선익 제외
ar={};dates=[]
for f in sorted(glob.glob(os.path.join(PROJ,'state','ranking_*.json'))):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102':
        ar[dt]=[r for r in json.load(open(f,encoding='utf-8'))['rankings'] if r['ticker'] not in EXCL];dates.append(dt)
dates=sorted(dates)
orig_g={dt:[(r.get('growth_s')or 0.0) for r in ar[dt]] for dt in dates}
tks=pickle.load(open(os.path.join(PROJ,'_lump_tickers.pkl'),'rb'));qser={}
for tk in tks:
    p=os.path.join(PROJ,'data_cache',f'fs_dart_{tk}.parquet')
    if not os.path.exists(p): continue
    d=pd.read_parquet(p);q=d[(d['공시구분']=='q')&(d['계정']=='매출액')].copy()
    q['rcept_dt']=pd.to_datetime(q['rcept_dt'],errors='coerce');q=q.dropna(subset=['rcept_dt']).sort_values('rcept_dt')
    if len(q)>=8: qser[tk]=(q['rcept_dt'].values,q['값'].astype(float).values)
def flag(tk,ts,T):
    s=qser.get(tk)
    if s is None: return False
    v=s[1][s[0]<=np.datetime64(ts)]
    if len(v)<8 or (v[-8:]<=0).any(): return False
    l4=v[-4:];return l4.min()/l4.max()<T
fl={dt:set(r['ticker'] for r in ar[dt] if flag(r['ticker'],pd.Timestamp(dt[:4]+'-'+dt[4:6]+'-'+dt[6:]),0.25)) for dt in dates}
def ap(use):
    for dt in dates:
        og=orig_g[dt]
        for j,r in enumerate(ar[dt]):
            r['growth_s']=og[j]*0.3 if (use and r['ticker'] in fl[dt]) else og[j]
def runbt(sub):
    reg=calc_reg(sub)
    t=TurboSimulator({d:ar[d] for d in sub},sub,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True
    t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:]);flat=list(t._cached_flat)
    r=_run_regime_inner(flat,flat,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    a=np.asarray(r['_daily_rets'],float);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100;n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return (cagr/abs(mdd) if mdd<0 else 0),mdd
ap(False);b=runbt(dates);ap(True);f=runbt(dates)
print(f"[디바이스·선익 유니버스서 제외 후] baseline Cal {b[0]:.2f} → 필터 {f[0]:.2f}  Δ{f[0]-b[0]:+.2f}")
print("→ Δ가 여전히 +면 효과가 디바이스 회피가 아닌 광범위(robust)")
