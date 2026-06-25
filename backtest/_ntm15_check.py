# -*- coding: utf-8 -*-
"""실제 NTM 컨센서스 15일 — production 보유 ∩ NTM기대성장 상위 = confirm. 확인 vs 미확인 차이. ★n 극소, 일화."""
import sys, io, os, glob, json, sqlite3
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
mc=pd.read_parquet(sorted(glob.glob(P+'/data_cache/market_cap_ALL_*.parquet'))[-1])
nm={}
try: nm=json.load(open(P+'/kr_eps_momentum/ticker_info_cache.json',encoding='utf-8'))
except: pass
def name(t):
    for k in (t,t+'.KS',t+'.KQ'):
        if k in nm: return nm[k].get('shortName',t)
    return t
def ttm_eps(t6):
    p=P+f'/data_cache/fs_dart_{t6}.parquet'
    if not os.path.exists(p) or t6 not in mc.index: return None
    fs=pd.read_parquet(p);fs['rcept_dt']=pd.to_datetime(fs['rcept_dt'],errors='coerce')
    q=fs[(fs['공시구분']=='q')&(fs['계정']=='지배주주당기순이익')&(fs['rcept_dt'].notna())].sort_values('rcept_dt')
    v=q['값'].astype(float).values
    if len(v)<4: return None
    sh=mc.loc[t6,'상장주식수'];return (v[-4:].sum()*1e8)/sh if sh>0 else None
c=sqlite3.connect(P+'/kr_eps_momentum/eps_momentum_data_kr.db')
ntmdates=[r[0] for r in c.execute("SELECT DISTINCT date FROM ntm_screening ORDER BY date")]
# 각 NTM일별 기대성장 상위셋
fwtop={}
for dt in ntmdates:
    df=pd.read_sql(f"SELECT ticker,ntm_current FROM ntm_screening WHERE date='{dt}'",c)
    rows=[]
    for _,r in df.iterrows():
        t6=r['ticker'][:6]
        if not r['ntm_current'] or r['ntm_current']<=0: continue
        te=ttm_eps(t6)
        if te and te>0: rows.append((t6,r['ntm_current']/te))
    g=pd.DataFrame(rows,columns=['t','gap']).sort_values('gap',ascending=False)
    g=g[g['gap']<15]
    fwtop[dt]={'top100':set(g.head(100)['t']),'gap':dict(zip(g['t'],g['gap'])),'n':len(g)}
print(f"NTM 일수 {len(ntmdates)} ({ntmdates[0]}~{ntmdates[-1]}), 일평균 기대성장 계산종목 {np.mean([fwtop[d]['n'] for d in ntmdates]):.0f}\n")
# production 보유(rank<=3) per day
pdays=[]
for f in sorted(glob.glob(P+'/state/ranking_2026*.json')):
    dt=os.path.basename(f)[8:16]
    if dt>='20260601': pdays.append((dt,f))
tdays=[d.strftime('%Y%m%d') for d in prices.index];tdi={d:i for i,d in enumerate(tdays)};pcol={c2:i for i,c2 in enumerate(prices.columns)};parr=prices.values
print(f"{'날짜':9s} {'production 보유 top3':38s} 확인?")
cf_r=[];un_r=[];rows_show=[]
for dt,f in pdays:
    held=[x['ticker'] for x in sorted(json.load(open(f,encoding='utf-8'))['rankings'],key=lambda z:z.get('rank',99))][:3]
    ft=fwtop.get(dt) or fwtop.get(max([x for x in ntmdates if x<=dt],default=ntmdates[0]))
    tags=[]
    for t in held:
        isc = t in ft['top100']
        tags.append(f"{name(t)[:8]}{'✅' if isc else '  '}")
        # 익일수익
        if dt in tdi and tdi[dt]+1<len(tdays):
            d2=tdays[tdi[dt]+1]
            if t in pcol and parr[tdi[dt],pcol[t]]>0 and parr[tdi[tdi[dt] and dt] if False else tdi[d2],pcol[t]]>0:
                r=parr[tdi[d2],pcol[t]]/parr[tdi[dt],pcol[t]]-1
                (cf_r if isc else un_r).append(r)
    print(f"{dt}  {' | '.join(tags):38s}")
print(f"\n★확인종목 익일평균 {np.mean(cf_r)*100:+.3f}% (n={len(cf_r)}) vs 미확인 {np.mean(un_r)*100:+.3f}% (n={len(un_r)})")
print(f"  격차 {(np.mean(cf_r)-np.mean(un_r))*100:+.3f}%p  ⚠️ n 극소(15일)=통계무의미, 메커니즘 확인용")
