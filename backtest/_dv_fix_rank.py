# -*- coding: utf-8 -*-
"""디바이스(187870) 무상증자 보정 후 진짜 순위 추정.
1) 4/28 권리락 비율로 이전 주가 back-adjust
2) 12m 모멘텀 재계산 (전 종목) → z-score
3) 내 재계산이 시스템 momentum_s와 맞는지 검증(상관)
4) 맞으면 디바이스 보정 모멘텀 → 점수 보정(M가중 0.30) → 재정렬
"""
import pandas as pd, numpy as np, glob, json
oh=pd.read_parquet(sorted(glob.glob('data_cache/all_ohlcv_2019*_*.parquet'))[-1]).replace(0,np.nan)
oh.index=pd.to_datetime(oh.index)
rk=json.load(open(sorted(glob.glob('state/ranking_2026*.json'))[-1],encoding='utf-8'))
elig={str(x['ticker']).zfill(6):x for x in rk['rankings']}
out=open('_dv_fix.txt','w',encoding='utf-8')

# 12m(252거래일) 수익률 — 전 eligible 종목
N=252
def ret12(s):
    s=s.dropna()
    if len(s)<N+1: return np.nan
    return s.iloc[-1]/s.iloc[-N-1]-1

raw_r={}
for tk in elig:
    if tk in oh.columns: raw_r[tk]=ret12(oh[tk])
raw_r={k:v for k,v in raw_r.items() if pd.notna(v)}
vals=np.array(list(raw_r.values())); mu,sd=vals.mean(),vals.std()
myz={k:(v-mu)/sd for k,v in raw_r.items()}

# 검증: 내 z vs 시스템 momentum_s
import numpy as _np
common=[k for k in myz if k in elig]
xs=[myz[k] for k in common]; ys=[elig[k].get('momentum_s',0) for k in common]
corr=_np.corrcoef(xs,ys)[0,1]
out.write(f'=== 검증: 내 12m z-score vs 시스템 momentum_s (n={len(common)}) ===\n')
out.write(f'  상관계수 = {corr:.3f}  (1에 가까울수록 내 재계산이 시스템과 일치)\n')
out.write('  샘플 (종목: 내z / 시스템M):\n')
for k in sorted(common,key=lambda x:elig[x]["rank"])[:6]:
    out.write(f'    {elig[k]["name"]}: {myz[k]:+.2f} / {elig[k].get("momentum_s",0):+.2f}\n')

# 디바이스 보정
tk='187870'; s=oh[tk].copy()
r=s.pct_change(fill_method=None)
exdate=r[(r<-0.33)&(r.index>='2026-01-01')].index[0]
ratio=s.loc[exdate]/s.loc[:exdate].iloc[-2]   # 권리락 당일/전일
out.write(f'\n=== 디바이스 권리락 {exdate.date()} 비율={ratio:.3f} ===\n')
s_adj=s.copy(); s_adj.loc[s_adj.index<exdate]=s_adj.loc[s_adj.index<exdate]*ratio
wrong=ret12(s); right=ret12(s_adj)
out.write(f'  12m 수익률: 잘못={wrong*100:+.0f}%  →  보정={right*100:+.0f}%\n')
wz=(wrong-mu)/sd; rz=(right-mu)/sd
out.write(f'  모멘텀 z:   잘못={wz:+.2f}  →  보정={rz:+.2f}  (Δ={rz-wz:+.2f})\n')
out.write(f'  (시스템 보고 momentum_s={elig[tk].get("momentum_s",0):+.2f})\n')

# 점수 보정 (M 가중 0.30) → 재정렬
dz=rz-wz
cur=elig[tk].get('score',0)
new=cur+0.30*dz
allsc=sorted([(elig[t].get('score',0),elig[t]['name'],t) for t in elig],key=lambda x:-x[0])
cur_rank=[i for i,(_,_,t) in enumerate(allsc) if t==tk][0]+1
new_list=sorted(allsc+[(new,'디바이스(보정)','X')],key=lambda x:-x[0])
new_rank=[i for i,(_,_,t) in enumerate(new_list) if t=='X'][0]+1
out.write(f'\n=== 디바이스 순위(당일 cr 기준) ===\n')
out.write(f'  현재(잘못): #{cur_rank}  (score {cur:+.3f})\n')
out.write(f'  보정 후:    #{new_rank}  (score {new:+.3f})\n')
out.write(f'\n보정 후 상위 6 (참고):\n')
for i,(sc,nm,t) in enumerate(new_list[:6]): out.write(f'  #{i+1} {nm} ({sc:+.3f})\n')
out.close(); print('done')
