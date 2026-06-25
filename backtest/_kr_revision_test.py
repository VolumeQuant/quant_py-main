# -*- coding: utf-8 -*-
import sqlite3, glob, os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
ROOT='C:/dev'
px=pd.read_parquet(sorted(glob.glob(ROOT+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(px.columns)};parr=px.values;pdi={d.strftime('%Y%m%d'):i for i,d in enumerate(px.index)};ptd=list(pdi.keys())
c=sqlite3.connect(ROOT+'/kr_eps_momentum/eps_momentum_data_kr.db')
df=pd.read_sql('SELECT date,ticker,ntm_current,ntm_30d,ntm_7d FROM ntm_screening',c)
df['tk']=df['ticker'].str[:6];df['d8']=df['date'].str.replace('-','')
last=ptd[-1]
def pr(t,d):
    return float(parr[pdi[d],pcol[t]]) if (t in pcol and d in pdi and parr[pdi[d],pcol[t]]>0) else None
rows=[]
for _,r in df.iterrows():
    if not r['ntm_current'] or r['ntm_current']<=0: continue
    p0=pr(r['tk'],r['d8']); p1=pr(r['tk'],last)
    if not p0 or not p1 or r['d8']>=last: continue
    rev30=(r['ntm_current']/r['ntm_30d']-1) if (r['ntm_30d'] and r['ntm_30d']>0) else np.nan
    rev7=(r['ntm_current']/r['ntm_7d']-1) if (r['ntm_7d'] and r['ntm_7d']>0) else np.nan
    rows.append({'rev30':rev30,'rev7':rev7,'fwdper':p0/r['ntm_current'],'fwd':(p1/p0-1)*100})
o=pd.DataFrame(rows)
print("=== KR 리비전 vs 레벨 — 가용 컨센 측정 (n=%d, 스냅샷 forward->%s) ===" % (len(o),last))
print("※ ntm_screening 15일치, 소표본 예비(US 측정-NOW 이행)\n")
def ic(x,nm):
    m=o[[x,'fwd']].dropna()
    if len(m)<20: print("  %-26s n=%d 부족" % (nm,len(m))); return
    print("  %-26s IC(Spearman)=%+.3f  n=%d" % (nm, m[x].corr(m['fwd'],method='spearman'), len(m)))
ic('rev30','리비전30일(상향폭)')
ic('rev7','리비전7일(상향폭)')
o['cheap']=-o['fwdper']
ic('cheap','레벨(선행PER 낮을수록)')
m=o.dropna(subset=['rev30'])
if len(m)>=30:
    md=m['rev30'].median();hi=m[m['rev30']>md];lo=m[m['rev30']<=md]
    print("\n  리비전30 상위half fwd %+.1f%% vs 하위half %+.1f%%  (delta %+.1f%%p)" % (hi['fwd'].mean(),lo['fwd'].mean(),hi['fwd'].mean()-lo['fwd'].mean()))
n0=(m['rev30']==0).sum()
print("  리비전30=0(미변동) %d/%d (%.0f%%) — 변동 적으면 신호 약함" % (n0,len(m),n0/len(m)*100))
