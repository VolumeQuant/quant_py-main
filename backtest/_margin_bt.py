# -*- coding: utf-8 -*-
"""순마진 플로어 트랩필터 BT — net margin < thr 매수차단. 에스에이엠티/삼지 잡으면서 승자 안죽이나."""
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
# 순마진 PIT 계산: TTM 지배순이익 / TTM 매출
tickers=set()
for d in dall: tickers|=set(r['ticker'] for r in ar_all[d])
margin_series={}
for t in tickers:
    fp=PROJ+f'/data_cache/fs_dart_{t}.parquet'
    if not os.path.exists(fp): continue
    df=pd.read_parquet(fp)
    def ser(nm):
        s=df[df['계정']==nm]
        if s.empty: return None
        g=s.groupby('기준일').agg(v=('값','last'),rc=('rcept_dt','last')).reset_index().sort_values('기준일')
        g['rc']=pd.to_datetime(g['rc']).dt.strftime('%Y%m%d'); return g
    rev=ser('매출액'); ni=ser('지배주주당기순이익')
    if ni is None: ni=ser('당기순이익')
    if rev is None or ni is None: continue
    # ★종목별 분기시점 TTM마진 사전계산 (rc배열 + 마진배열) → margin_at은 이진탐색
    m=rev.merge(ni,on='기준일',suffixes=('_r','_n')).sort_values('기준일')
    m['rc']=m[['rc_r','rc_n']].max(axis=1)  # 둘 중 늦은 공시일
    rcs=[]; mgs=[]
    rv=m['v_r'].values; nv=m['v_n'].values; rcv=m['rc'].values
    for i in range(3,len(m)):
        rs=rv[i-3:i+1].sum(); ns=nv[i-3:i+1].sum()
        rcs.append(rcv[i]); mgs.append(ns/rs*100 if rs>0 else np.nan)
    if rcs: margin_series[t]=(np.array(rcs),np.array(mgs))
_mcache={}
def margin_at(t,d8):
    key=(t,d8)
    if key in _mcache: return _mcache[key]
    x=margin_series.get(t); res=None
    if x is not None:
        rcs,mgs=x
        idx=np.searchsorted(rcs,d8,side='right')-1
        if idx>=0:
            v=mgs[idx]; res=float(v) if v==v else None
    _mcache[key]=res; return res
def patch(t,sd,thr=None):
    blk=0
    for date,arr in t._overlay_pre.items():
        if arr is None:continue
        rk=sd.get(date)
        if rk is None:continue
        for j,s in enumerate(rk):
            if s.get('recent_ca'):arr[j]-=RC*float(s['recent_ca'])
            if thr is not None:
                mg=margin_at(s['ticker'],date)
                if mg is not None and mg<thr: arr[j]-=100.0; blk+=1
    return blk
def run(sub,thr=None,exclude=None):
    sd={d:[r for r in ar_all[d] if not exclude or r['ticker'] not in exclude] for d in sub}
    t=TurboSimulator(sd,sub,prices,overheat_w=0.2);t._use_overlay=True;t._use_stored_growth=True
    patch(t,sd,thr)
    t._ensure_cache(0.15,0.0,0.55,0.30,0.4,20,'12m',*G3[:3],*G3[3:])
    f=list(t._cached_flat);reg=calc_reg(sub)
    r=_run_regime_inner(f,f,0,6,3,3,6,3,reg,sub,t._price_arr,t._bench_arr,t._has_bench,t._date_row_indices,len(sub),None,None,None,None,stop_loss_o=None,trailing_stop_o=None,stop_loss_d=None,trailing_stop_d=None)
    return r.get('calmar',0),r.get('mdd',0),r.get('total',0)
base=run(dall)
print(f"base: Calmar {base[0]:.3f} MDD {base[1]:.1f}% 누적 {base[2]:.0f}%\n[순마진 플로어 매수차단]")
for thr in [8,10,12,15]:
    # 차단되는 매수권 건수 + 에스에이엠티/삼지 차단 확인
    blk=sum(1 for d in dall for r in ar_all[d] if r.get('rank',99)<=6 and (margin_at(r['ticker'],d) or 99)<thr)
    c=run(dall,thr)
    print(f"  마진<{thr}%: Calmar {c[0]:.3f} (Δ{c[0]-base[0]:+.3f}) MDD {c[1]:.1f}% 차단(rank≤6) {blk}건")
print("\n[LOWO @ 마진<12%]")
for tk,nm in [('000660','SK'),('080220','제주'),('033100','제룡'),('042700','한미'),('131290','티에스이'),('039030','이오')]:
    b=run(dall,None,{tk})[0];f=run(dall,12,{tk})[0]
    print(f"  −{nm}: base {b:.3f} → 필터 {f:.3f} Δ{f-b:+.3f}")
print("\n[완료]")
