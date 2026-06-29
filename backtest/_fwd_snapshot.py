# -*- coding: utf-8 -*-
import pandas as pd, numpy as np, glob, os, sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fp=pd.read_parquet(P+'/data_cache/consensus_forward_per.parquet').set_index('ticker')
mc=pd.read_parquet(sorted(glob.glob(P+'/data_cache/market_cap_ALL_*.parquet'))[-1])
nm={}
for f in sorted(glob.glob(P+'/state/ranking_*.json'))[-5:]:
    for x in json.load(open(f,encoding='utf-8'))['rankings']: nm[x['ticker']]=x['name']
def ttm_ni(t):
    p=P+f'/data_cache/fs_dart_{t}.parquet'
    if not os.path.exists(p): return None
    fs=pd.read_parquet(p);fs['rcept_dt']=pd.to_datetime(fs['rcept_dt'],errors='coerce')
    q=fs[(fs['공시구분']=='q')&(fs['계정']=='지배주주당기순이익')&(fs['rcept_dt'].notna())].sort_values('rcept_dt')
    v=q['값'].astype(float).values
    return v[-4:].sum() if len(v)>=4 else None
rows=[]
for t in fp.index:
    fper=fp.loc[t,'forward_per']
    if t not in mc.index or pd.isna(fper) or fper<=0: continue
    cap=mc.loc[t,'시가총액']; ni=ttm_ni(t)
    if ni is None or ni<=0 or pd.isna(cap): continue
    tper=cap/(ni*1e8)   # 시총(원) / TTM지배순이익(억→원)
    rows.append((t,nm.get(t,t),tper,fper,(tper/fper-1)*100))
df=pd.DataFrame(rows,columns=['t','nm','후행PER','선행PER','갭']).dropna()
df=df[(df['후행PER']>0)&(df['후행PER']<300)]
print('=== 네가 본 종목 ===')
for t in ['000660','005930','402340','000270']:
    r=df[df['t']==t]
    if len(r):
        x=r.iloc[0]
        print('  %s: 후행PER %.1f / 선행PER %.1f -> 선행성장갭 %+.0f%%'%(x['nm'],x['후행PER'],x['선행PER'],x['갭']))
print('\n=== 선행성장 갭 상위 12 (인플렉션, 시스템 놓칠수있음) ===')
for _,x in df.sort_values('갭',ascending=False).head(12).iterrows():
    print('  %-12s 후행PER %6.1f 선행PER %5.1f 갭 %+5.0f%%'%(x['nm'][:12],x['후행PER'],x['선행PER'],x['갭']))
print('\n=== 갭 하위 8 (후행만 좋고 선행 꺼짐=함정의심) ===')
for _,x in df.sort_values('갭').head(8).iterrows():
    print('  %-12s 후행PER %6.1f 선행PER %5.1f 갭 %+5.0f%%'%(x['nm'][:12],x['후행PER'],x['선행PER'],x['갭']))
