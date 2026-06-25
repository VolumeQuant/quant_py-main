# -*- coding: utf-8 -*-
"""승자 vs 패자 시그니처 EDA — 저장팩터 + 재무(lumpiness/accruals/opmargin) 분포 비교."""
import sys, io, os, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
df=pd.read_parquet(P+'/backtest/_trap_entries.parquet')
# 재무 features (PIT, 진입일 기준)
def fsfeat(tk,d):
    p=P+f'/data_cache/fs_dart_{tk}.parquet'
    if not os.path.exists(p): return {}
    fs=pd.read_parquet(p); fs['rcept_dt']=pd.to_datetime(fs['rcept_dt'],errors='coerce')
    ts=pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]); out={}
    def q(acct):
        s=fs[(fs['공시구분']=='q')&(fs['계정']==acct)&(fs['rcept_dt'].notna())&(fs['rcept_dt']<=ts)].sort_values('rcept_dt')
        return s['값'].astype(float).values
    rev=q('매출액'); op=q('영업이익'); ni=q('지배주주당기순이익'); cfo=q('영업활동으로인한현금흐름')
    if len(rev)>=8:
        v8=rev[-8:]; v4=rev[-4:]
        if (v8>0).all():
            out['rev_minmax']=v4.min()/v4.max(); out['rev_cv']=v8.std()/v8.mean()
    if len(op)>=4 and len(ni)>=4 and len(cfo)>=4:
        # accruals B, C (TTM)
        asset=q('자산')
        if len(asset)>=1 and asset[-1]>0:
            out['accr_B']=(ni[-4:].sum()-cfo[-4:].sum())/asset[-1]*100
        if op[-4:].sum()>0:
            out['accr_C']=op[-4:].max()/op[-4:].sum()
        if len(rev)>=4 and rev[-4:].sum()>0:
            out['opmargin']=op[-4:].sum()/rev[-4:].sum()*100
    return out
feats=[fsfeat(r['tk'],r['d']) for _,r in df.iterrows()]
fd=pd.DataFrame(feats); df=pd.concat([df.reset_index(drop=True),fd],axis=1)
v=df.dropna(subset=['f60']).copy()
win=v[v['f60']>0]; los=v[v['f60']<0]; big=v[v['f60']<-15]
cols=['growth','value','qual','mom','overheat','recent_ca','per','pbr','roe','rev_minmax','rev_cv','accr_B','accr_C','opmargin']
print(f"승자 {len(win)} / 패자 {len(los)} / 큰손실 {len(big)}\n")
print(f"  {'feature':10s}{'승자평균':>10s}{'패자평균':>10s}{'큰손실평균':>11s}{'분리(패-승)':>11s}")
for c in cols:
    w=win[c].astype(float).mean(); l=los[c].astype(float).mean(); b=big[c].astype(float).mean()
    print(f"  {c:10s}{w:>10.2f}{l:>10.2f}{b:>11.2f}{l-w:>+11.2f}")
# 모멘텀 분위별 패자율
print("\n=== mom_12m 분위별 승률/평균fwd60 ===")
v['mq']=pd.qcut(v['mom'],4,labels=['Q1저','Q2','Q3','Q4고'])
for q,g in v.groupby('mq',observed=True):
    print(f"  {q}: n={len(g)} 평균f60={g['f60'].mean():+.1f}% 승률{(g['f60']>0).mean()*100:.0f}%")
print("\n=== rev_minmax(lumpiness) 분위별 ===")
vv=v.dropna(subset=['rev_minmax']).copy(); vv['lq']=pd.qcut(vv['rev_minmax'],4,labels=['저(lumpy)','Q2','Q3','고(고름)'])
for q,g in vv.groupby('lq',observed=True):
    print(f"  {q}: n={len(g)} 평균f60={g['f60'].mean():+.1f}% 승률{(g['f60']>0).mean()*100:.0f}%")
