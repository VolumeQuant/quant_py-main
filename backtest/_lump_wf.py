# -*- coding: utf-8 -*-
"""min/max<T 일회성 필터 워크포워드 검증 — 구간별 Calmar baseline vs 필터 + 디바이스 실제 진입일 효과."""
import sys, io, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from turbo_simulator import TurboSimulator, _run_regime_inner
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def ba(s):
    r = s.pct_change(fill_method=None); ev = r[(r < -0.33) | (r > 0.45)]; s2 = s.copy()
    for d, rt in ev.items():
        f = 1 + rt
        if 0.02 < abs(f) < 50: s2.loc[s2.index < d] *= f
    return s2
prices = pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_2017*_202606*.parquet')))[-1]).replace(0,np.nan).apply(ba)
kc = pd.read_parquet(os.path.join(PROJ,'data_cache','kospi_yf.parquet')).iloc[:,0]
ma20=kc.rolling(20).mean(); ma80=kc.rolling(80).mean()
def calc_reg(ds):
    reg={}; md=True; stk=0; ss=None
    for d in ds:
        ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:])
        if ts not in kc.index or pd.isna(ma80.get(ts,np.nan)): reg[d]=md; continue
        s=bool(ma20[ts]>ma80[ts])
        if s==ss: stk+=1
        else: stk=1; ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
G3=('rev_z','oca_z','gp_growth_z',0.4,0.4,0.2)
import pickle
print("로드...",flush=True)
ar={}; dates=[]
for f in sorted(glob.glob(os.path.join(PROJ,'state','ranking_*.json'))):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102':
        ar[dt]=json.load(open(f,encoding='utf-8'))['rankings']; dates.append(dt)
dates=sorted(dates)
orig_g={dt:[(r.get('growth_s') or 0.0) for r in ar[dt]] for dt in dates}
tks=pickle.load(open(os.path.join(PROJ,'_lump_tickers.pkl'),'rb'))
qser={}
for tk in tks:
    p=os.path.join(PROJ,'data_cache',f'fs_dart_{tk}.parquet')
    if not os.path.exists(p): continue
    d=pd.read_parquet(p)
    q=d[(d['공시구분']=='q')&(d['계정']=='매출액')].copy()
    q['rcept_dt']=pd.to_datetime(q['rcept_dt'],errors='coerce')
    q=q.dropna(subset=['rcept_dt']).sort_values('rcept_dt')
    if len(q)>=8: qser[tk]=(q['rcept_dt'].values,q['값'].astype(float).values)
def flag_mm(tk,base_ts,T):
    s=qser.get(tk)
    if s is None: return False
    v=s[1][s[0]<=np.datetime64(base_ts)]
    if len(v)<8 or (v[-8:]<=0).any(): return False
    l4=v[-4:]; return l4.min()/l4.max()<T
def build(T):
    fl={}
    for dt in dates:
        ts=pd.Timestamp(dt[:4]+'-'+dt[4:6]+'-'+dt[6:])
        fl[dt]=set(r['ticker'] for r in ar[dt] if flag_mm(r['ticker'],ts,T))
    return fl
def apply_pen(fl,pen):
    for dt in dates:
        og=orig_g[dt]; fs=fl.get(dt,set()) if fl else set()
        for j,r in enumerate(ar[dt]):
            r['growth_s']=og[j]*pen if r['ticker'] in fs else og[j]
def runbt(sub):
    reg=calc_reg(sub)
    t=TurboSimulator({d:ar[d] for d in sub},sub,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True
    t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:])
    flat=list(t._cached_flat)
    r=_run_regime_inner(flat,flat,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    a=np.asarray(r['_daily_rets'],float);eq=np.cumprod(1+a);peak=np.maximum.accumulate(eq);mdd=((eq-peak)/peak).min()*100
    n=len(a);cagr=(eq[-1]**(252/max(n,1))-1)*100
    return (cagr/abs(mdd) if mdd<0 else 0),cagr,mdd
segs=[('전체','20190102','20261231'),('19-21강세','20190102','20211231'),('22-23약세','20220101','20231231'),('24-26','20240101','20261231')]
fl=build(0.25)
print(f"\nmin/max<0.25 ×0.3 워크포워드 (flag {sum(len(v) for v in fl.values())}건)\n")
print(f"  {'구간':12s}{'base Cal':>9s}{'필터 Cal':>9s}{'ΔCal':>7s}  {'base MDD':>9s}{'필터 MDD':>9s}")
for nm,lo,hi in segs:
    sub=[d for d in dates if lo<=d<=hi]
    apply_pen(None,1.0); b=runbt(sub)
    apply_pen(fl,0.3); f=runbt(sub)
    print(f"  {nm:12s}{b[0]:>9.2f}{f[0]:>9.2f}{f[0]-b[0]:>+7.2f}  {b[2]:>8.1f}%{f[2]:>8.1f}%")
apply_pen(None,1.0)
# 디바이스 2026 진입일 효과 — 실제 rank 재계산
print("\n[디바이스 2026-05~06 일별: 페널티 전/후 점수순위]")
fl=build(0.25)
for dt in [d for d in dates if '20260512'<=d<='20260605']:
    rows=ar[dt]
    def rk(useflag):
        sc=[]
        for r in rows:
            g=(orig_g[dt][rows.index(r)])
            if useflag and r['ticker'] in fl.get(dt,set()): g=g*0.3
            s=0.15*(r.get('value_s')or 0)+0.55*g+0.30*(r.get('mom_12m_s')or r.get('momentum_s')or 0)+0.2*(r.get('overheat_pen')or 0)+0.05*(r.get('mom_10_z')or 0)+0.06*(r.get('vol_low_z')or 0)
            sc.append((s,r['ticker']))
        sc.sort(reverse=True)
        return next((i+1 for i,(s,t) in enumerate(sc) if t=='187870'),99)
    flagged='FLAG' if '187870' in fl.get(dt,set()) else '-'
    print(f"  {dt}: 페널티전 {rk(False):>2}위 → 후 {rk(True):>2}위  ({flagged})")
