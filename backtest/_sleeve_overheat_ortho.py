# -*- coding: utf-8 -*-
"""fwd_per(forward PER) vs 과열캡(trailing PER) 직교성. 중복이면 sleeve 추가 무의미, 직교면 진짜 새 정보."""
import sys, io, os, glob, pickle
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
from scipy.stats import spearmanr
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(prices.columns)};parr=prices.values
tdays=[d.strftime('%Y%m%d') for d in prices.index];tdi={d:i for i,d in enumerate(tdays)}
cache=pickle.load(open(P+'/backtest/_earn_cache.pkl','rb'))
mc=pd.read_parquet(sorted(glob.glob(P+'/data_cache/market_cap_ALL_*.parquet'))[-1])
sh={t:mc.loc[t,'상장주식수'] for t in mc.index}
g=pd.read_pickle(P+'/backtest/_sleeve_eda_df.pkl').dropna(subset=['r60']).copy()
def ttm_now(t,d):  # 현재 시점 TTM (trailing)
    dd=cache.get(t);s=dd.get('ni') if dd else None
    if s is None: return None
    v=s[1][s[0]<=np.datetime64(pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]))];return v[-4:].sum() if len(v)>=4 else None
def px(t,d):
    if t not in pcol or d not in tdi: return None
    v=parr[tdi[d],pcol[t]]; return float(v) if v>0 else None
# trailing PER = 시총/현재TTM순이익 (과열캡 기준 ey의 역수)
tp=[]
for _,r in g.iterrows():
    t,d=r['t'],r['d']; e0=ttm_now(t,d); p0=px(t,d)
    tp.append((p0*sh[t])/(e0*1e8) if (e0 and e0>0 and p0 and t in sh) else np.nan)
g['trailing_per']=tp
gg=g.dropna(subset=['trailing_per'])
gg=gg[(gg['trailing_per']>0)&(gg['trailing_per']<300)]
print(f"[fwd_per vs trailing_per 직교성, n={len(gg)}]\n")
print(f"  상관(Spearman) fwd_per vs trailing_per: {spearmanr(gg['fwdper'],gg['trailing_per'])[0]:+.3f}")
print(f"  (1에 가까우면 같은정보=과열캡과 중복 / 낮으면 직교=새 정보)\n")
print(f"  IC fwd_per(낮을수록)   : {spearmanr(-gg['fwdper'],gg['r60'])[0]:+.4f}")
print(f"  IC trailing_per(낮을수록): {spearmanr(-gg['trailing_per'],gg['r60'])[0]:+.4f}  ← 과열캡이 쓰는 신호")
# trailing_per 통제 후 fwd_per 잔차 IC (과열캡 빼고도 fwd_per가 예측하나)
import numpy as np
lt=np.log(gg['trailing_per']); lf=np.log(gg['fwdper'])
beta=np.polyfit(lt,lf,1); resid=lf-(beta[0]*lt+beta[1])
print(f"\n  ★trailing_per 통제후 fwd_per 잔차 IC: {spearmanr(-resid,gg['r60'])[0]:+.4f}")
print(f"   (과열캡이 못잡는 fwd_per 고유 예측력 — 양수면 진짜 새 알파)")
# 2D: trailing 비싼데 forward 싼 종목(=기대성장으로 싸짐) 수익
print(f"\n[trailing 비쌈 but forward 쌈 = 이익폭증 종목 (SK하이닉스류)]")
hi_t=gg['trailing_per']>=20
for lbl,s in [('trailing>=20 & fwd<15 (이익폭증)',gg[hi_t&(gg['fwdper']<15)]),
              ('trailing>=20 & fwd>=20 (그냥비쌈)',gg[hi_t&(gg['fwdper']>=20)]),
              ('trailing<20 & fwd<15 (둘다쌈)',gg[(~hi_t)&(gg['fwdper']<15)])]:
    if len(s)>0: print(f"  {lbl:<36} n={len(s):5d}  fwd60 {s['r60'].mean():+.1f}%")
