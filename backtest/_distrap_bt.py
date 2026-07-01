# -*- coding: utf-8 -*-
"""유통 일회성 트랩 교집합 BT — 마진<10 & accruals>25 & 이익집중>0.6 (+성장>1.5) 매수차단."""
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
prices=pd.read_parquet(sorted(glob.glob(os.path.join(PROJ,'data_cache','all_ohlcv_2017*_20260*.parquet')))[-1]).replace(0,np.nan).apply(ba)
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
tk_all=set()
for d in dall: tk_all|=set(r['ticker'] for r in ar_all[d])
sig={}
for t in tk_all:
    fp=PROJ+f'/data_cache/fs_dart_{t}.parquet'
    if not os.path.exists(fp):continue
    df=pd.read_parquet(fp);A={}
    for nm in ['매출액','당기순이익','지배주주당기순이익','영업활동으로인한현금흐름','자산']:
        s=df[df['계정']==nm]
        if s.empty:continue
        g=s.groupby('기준일').agg(v=('값','last'),rc=('rcept_dt','last')).reset_index().sort_values('기준일')
        g['rc']=pd.to_datetime(g['rc']).dt.strftime('%Y%m%d');A[nm]=g
    if '매출액' not in A or '자산' not in A:continue
    M=A['매출액'][['기준일','rc']].copy()
    for nm,g in A.items(): M=M.merge(g[['기준일','v']].rename(columns={'v':nm}),on='기준일',how='left')
    M=M.sort_values('기준일').reset_index(drop=True)
    if len(M)<5:continue
    ni=M['지배주주당기순이익'].fillna(M.get('당기순이익')) if '지배주주당기순이익' in M else M.get('당기순이익')
    if ni is None:continue
    rev_t=M['매출액'].rolling(4).sum();ni_t=ni.rolling(4).sum()
    cfo_t=M['영업활동으로인한현금흐름'].rolling(4).sum() if '영업활동으로인한현금흐름' in M else pd.Series([np.nan]*len(M))
    mg=(ni_t/rev_t*100).values; B=((ni_t-cfo_t)/M['자산']*100).values; cc=(ni.rolling(4).max()/ni_t).values
    sig[t]=(M['rc'].values, mg, B, cc)
_c={}
def trap(t,d8,need_grow,growv):
    k=(t,d8)
    x=sig.get(t)
    if x is None:return False
    rcs,mg,B,cc=x;i=np.searchsorted(rcs,d8,'right')-1
    if i<0:return False
    m,b,c=mg[i],B[i],cc[i]
    if not(m==m and b==b and c==c):return False
    base=(m<10 and b>25 and c>0.6)
    if need_grow: return base and growv>1.5
    return base
def patch(t,sd,mode=None):
    for date,arr in t._overlay_pre.items():
        if arr is None:continue
        rk=sd.get(date)
        if rk is None:continue
        for j,s in enumerate(rk):
            if s.get('recent_ca'):arr[j]-=RC*float(s['recent_ca'])
            if mode and trap(s['ticker'],date, mode=='④', (s.get('growth_s') or 0)):
                arr[j]-=100.0
def run(sub,mode=None,exclude=None):
    sd={d:[r for r in ar_all[d] if not exclude or r['ticker'] not in exclude] for d in sub}
    t=TurboSimulator(sd,sub,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True
    patch(t,sd,mode)
    t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:])
    f=list(t._cached_flat);reg=calc_reg(sub)
    r=_run_regime_inner(f,f,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    return r.get('calmar',0),r.get('mdd',0),r.get('total',0)
base=run(dall)
print(f"base: Calmar {base[0]:.3f} MDD {base[1]:.1f}% 누적 {base[2]:.0f}%")
for mode in ['③','④']:
    c=run(dall,mode)
    print(f"  {mode} 차단: Calmar {c[0]:.3f} (Δ{c[0]-base[0]:+.3f}) MDD {c[1]:.1f}% 누적 {c[2]:.0f}%")
print("[LOWO @ ④]")
for tk,nm in [('000660','SK'),('080220','제주'),('033100','제룡'),('042700','한미'),('131290','티에스이'),('039030','이오')]:
    b=run(dall,None,{tk})[0];f=run(dall,'④',{tk})[0]
    print(f"  −{nm}: {b:.3f}→{f:.3f} Δ{f-b:+.3f}")
print("[완료]")
