import sys, io, glob, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
ROOT='C:/dev';TK='080220'
fs=pd.read_parquet(ROOT+f'/data_cache/fs_dart_{TK}.parquet')
fs['rcept_dt']=pd.to_datetime(fs['rcept_dt'],errors='coerce')
q=fs[(fs['공시구분']=='q')&(fs['계정']=='지배주주당기순이익')&(fs['rcept_dt'].notna())].sort_values('rcept_dt')
v=q['값'].astype(float).values  # 억원
dts=q['rcept_dt'].dt.strftime('%Y-%m').values
mc=pd.read_parquet(sorted(glob.glob(ROOT+'/data_cache/market_cap_ALL_*.parquet'))[-1])
sh=mc.loc[TK,'상장주식수']; price=mc.loc[TK,'종가']; cap=mc.loc[TK,'시가총액']
print(f"제주반도체({TK}) — 주가 {price:,.0f}원, 시총 {cap/1e8:,.0f}억, 주식수 {sh:,.0f}\n")
print("최근 8분기 지배순이익(억):")
for d,x in zip(dts[-8:],v[-8:]): print(f"  {d}: {x:+.0f}억")
ttm=v[-4:].sum(); ttm_prev=v[-8:-4].sum() if len(v)>=8 else None
eps_ttm=ttm*1e8/sh
per_trail=price/eps_ttm
print(f"\nTTM 지배순이익: {ttm:.0f}억 (전년 {ttm_prev:.0f}억)" if ttm_prev else f"\nTTM: {ttm:.0f}억")
print(f"TTM EPS: {eps_ttm:,.0f}원 / trailing PER: {per_trail:.1f}")
# === forward EPS 예측 (여러 방법) ===
print(f"\n=== forward EPS 예측 → fwd_per ===")
ests={}
# 1) 최근분기 run-rate ×4
ests['run-rate(최근Q×4)']=v[-1]*4
# 2) 최근2분기 평균 ×4
ests['최근2Q평균×4']=v[-2:].mean()*4
# 3) YoY 성장률 적용
if ttm_prev and ttm_prev>0:
    yoy=ttm/ttm_prev; ests[f'TTM×YoY({(yoy-1)*100:+.0f}%)']=ttm*yoy
# 4) QoQ 추세 (최근4Q 선형회귀 연율화)
if len(v)>=4:
    x=np.arange(4);y=v[-4:];sl,ic=np.polyfit(x,y,1);proj=[ic+sl*(4+i) for i in range(4)];ests['QoQ선형추세 다음4Q']=sum(proj)
for nm,fe_eok in ests.items():
    if fe_eok<=0: print(f"  {nm:22s}: 적자예상(불가)"); continue
    fe=fe_eok*1e8/sh; fper=price/fe
    print(f"  {nm:22s}: fwdEPS {fe:,.0f}원  fwd_per {fper:.1f}  (기대성장 {(fe/eps_ttm-1)*100:+.0f}%)")
