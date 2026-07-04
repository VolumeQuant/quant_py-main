# -*- coding: utf-8 -*-
"""mom_5_z를 기존 production state에 주입 (재생성 없이). FG와 동일: raw OHLCV, mcap종목, corpaction OFF,
영업일필터(nonempty≥50%), mom_5=iloc[-1]/iloc[-6]-1, 전체 μ,σ z. 먼저 재생성 표본과 대조."""
import sys,io,os,glob,json
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
import numpy as np,pandas as pd
R='C:/dev/claude-code/quant_py-main'
ohlcv=pd.read_parquet(R+'/data_cache/all_ohlcv_20170601_20260629.parquet').replace(0,np.nan)
# 시총 종목 (PIT) — market_cap 캐시
mcap=pd.read_parquet(R+'/data_cache/market_cap_20170601_20260629.parquet') if os.path.exists(R+'/data_cache/market_cap_20170601_20260629.parquet') else None
print('mcap 파일',mcap is not None, 'ohlcv',ohlcv.shape)
def mom5_z_for(base_ts, use_mcap_cols=None):
    pdf=ohlcv.loc[ohlcv.index<=base_ts]
    if use_mcap_cols is not None:
        cols=[c for c in pdf.columns if c in use_mcap_cols]; pdf=pdf[cols]
    mask=pdf.notna().sum(axis=1) >= (pdf.shape[1]*0.5)
    biz=pdf.loc[mask]
    if len(biz)<6: return {}
    raw=biz.iloc[-1]/biz.iloc[-6]-1
    raw=raw.replace([np.inf,-np.inf],np.nan).dropna()
    m,s=raw.mean(),raw.std()
    if not s>0: return {}
    z=(raw-m)/s
    return z.to_dict()
# 재생성 표본 대조
D='C:/Users/jkw88/AppData/Local/Temp/state_mom5_sample'
fs=sorted(glob.glob(D+'/ranking_*.json'))
errs=[];errs_mc=[]
for f in fs[::10]:
    dt=os.path.basename(f)[8:16]; base_ts=pd.Timestamp(dt[:4]+'-'+dt[4:6]+'-'+dt[6:])
    r=json.load(open(f,encoding='utf-8'))['rankings']
    z_all=mom5_z_for(base_ts)
    for x in r:
        if 'mom_5_z' in x and x['ticker'] in z_all:
            errs.append(abs(x['mom_5_z']-z_all[x['ticker']]))
print(f'\n[대조: 전체컬럼 μ,σ] 표본 {len(errs)}종목, 평균오차 {np.mean(errs):.4f}, 최대 {np.max(errs):.4f}')
# 상위종목 몇개 직접 비교
f=fs[-1]; dt=os.path.basename(f)[8:16]; base_ts=pd.Timestamp(dt[:4]+'-'+dt[4:6]+'-'+dt[6:])
z_all=mom5_z_for(base_ts); r=json.load(open(f,encoding='utf-8'))['rankings']
print(f'{dt} 상위6 (재생성 vs 주입):')
for x in r[:6]:
    print(f"  {x['name'][:8]:10s} 재생성 {x.get('mom_5_z',-9):+.4f}  주입 {z_all.get(x['ticker'],-9):+.4f}")
