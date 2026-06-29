# -*- coding: utf-8 -*-
"""실험 공통 캐시 — state 종목별 분기 지배순이익/영업이익/매출 시리즈 + 상장주식수(시총용). PIT용 rcept."""
import sys, io, os, glob, json, pickle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# state 등장 종목 union
tks=set()
for f in sorted(glob.glob(P+'/state/ranking_*.json')):
    if os.path.basename(f)[8:16]>='20190102':
        for x in json.load(open(f,encoding='utf-8'))['rankings']:
            if x.get('rank',99)<=30: tks.add(x['ticker'])
print(f"state rank<=30 union {len(tks)}종목")
cache={}
for t in tks:
    p=P+f'/data_cache/fs_dart_{t}.parquet'
    if not os.path.exists(p): continue
    fs=pd.read_parquet(p);fs['rcept_dt']=pd.to_datetime(fs['rcept_dt'],errors='coerce')
    d={}
    for acct,key in [('지배주주당기순이익','ni'),('당기순이익','ni2'),('영업이익','op'),('매출액','rev'),('매출총이익','gp')]:
        q=fs[(fs['공시구분']=='q')&(fs['계정']==acct)&(fs['rcept_dt'].notna())].sort_values('rcept_dt')
        if len(q): d[key]=(q['rcept_dt'].values, q['값'].astype(float).values)
    if 'ni' in d or 'ni2' in d: cache[t]=d
pickle.dump(cache, open(P+'/backtest/_earn_cache.pkl','wb'))
print(f"이익 캐시 {len(cache)}종목 저장")
# 상장주식수 (시총 = price×shares 용), 최신 market_cap
mc=pd.read_parquet(sorted(glob.glob(P+'/data_cache/market_cap_ALL_*.parquet'))[-1])
shares={t:mc.loc[t,'상장주식수'] for t in tks if t in mc.index}
pickle.dump(shares, open(P+'/backtest/_shares.pkl','wb'))
print(f"상장주식수 {len(shares)}종목 저장")
