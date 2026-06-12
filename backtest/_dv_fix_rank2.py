# -*- coding: utf-8 -*-
"""디바이스 보정 후 진짜 순위 — 정확 복제판.
모멘텀 = 12m수익률/연변동성(floor15), 섹터별 Blom 순위 z-score (FG와 동일).
검증: 내 momentum_z vs 시스템 momentum_s 상관 → 통과 시 보정 적용."""
import pandas as pd, numpy as np, glob, json
from scipy.stats import norm
oh=pd.read_parquet(sorted(glob.glob('data_cache/all_ohlcv_2019*_*.parquet'))[-1]).replace(0,np.nan)
oh.index=pd.to_datetime(oh.index)
rk=json.load(open(sorted(glob.glob('state/ranking_2026*.json'))[-1],encoding='utf-8'))
elig={str(x['ticker']).zfill(6):x for x in rk['rankings']}
out=open('_dv_fix2.txt','w',encoding='utf-8')

L12=252; VFLOOR=15.0
def voladj_mom(s):
    s=s.dropna()
    if len(s)<L12+1: return np.nan
    cur=s.iloc[-1]; start=s.iloc[-(L12+1)]
    if not(start>0 and cur>0): return np.nan
    ret=(cur/start-1)*100
    dr=s.iloc[-(L12+1):].pct_change(fill_method=None).iloc[1:]
    vol=dr.std()*np.sqrt(252)*100
    vol=max(vol,VFLOOR)
    return ret/vol

# 전 eligible 모멘텀 raw
mom={}
for tk in elig:
    if tk in oh.columns:
        m=voladj_mom(oh[tk])
        if pd.notna(m): mom[tk]=m

def blom_sector_z(rawmap, sectormap, min_sector=10):
    s=pd.Series(rawmap)
    sec=pd.Series({k:sectormap.get(k,'?') for k in rawmap})
    # full z
    def blom(x):
        n=len(x); r=x.rank(method='average'); u=((r-0.375)/(n+0.25)).clip(0.001,0.999); return pd.Series(norm.ppf(u),index=x.index)
    fullz=blom(s)
    z=fullz.copy()
    for sn in sec.unique():
        m=sec==sn
        if m.sum()>=min_sector: z[m]=blom(s[m])
    return z

sectormap={tk:elig[tk].get('sector','?') for tk in elig}
myz=blom_sector_z(mom, sectormap)

# 검증
common=[k for k in myz.index if k in elig]
xs=np.array([myz[k] for k in common]); ys=np.array([elig[k].get('momentum_s',0) for k in common])
corr=np.corrcoef(xs,ys)[0,1]
out.write(f'=== 검증: 내 momentum_z vs 시스템 momentum_s (n={len(common)}) 상관={corr:.3f} ===\n')
for k in sorted(common,key=lambda x:elig[x]["rank"])[:7]:
    out.write(f'  {elig[k]["name"]}(sec={elig[k].get("sector","?")}): 내{myz[k]:+.2f} / 시스템{elig[k].get("momentum_s",0):+.2f}\n')

# 디바이스 보정
tk='187870'; s=oh[tk]
r=s.pct_change(fill_method=None)
exd=r[(r<-0.33)&(r.index>='2026-01-01')].index[0]
ratio=s.loc[exd]/s.loc[:exd].iloc[-2]
s_adj=s.copy(); s_adj.loc[s_adj.index<exd]*=ratio
mom_wrong=voladj_mom(s); mom_right=voladj_mom(s_adj)
out.write(f'\n=== 디바이스 보정 (권리락 {exd.date()} ×{ratio:.3f}) ===\n')
out.write(f'  위험조정 모멘텀 raw: 잘못={mom_wrong:.2f} → 보정={mom_right:.2f}\n')
# 보정 모멘텀으로 섹터 z 다시
mom2=dict(mom); mom2[tk]=mom_right
myz2=blom_sector_z(mom2, sectormap)
z_wrong=myz[tk]; z_right=myz2[tk]
out.write(f'  섹터 모멘텀 z:  잘못={z_wrong:+.2f} → 보정={z_right:+.2f}  (Δ={z_right-z_wrong:+.2f})\n')
out.write(f'  (시스템 보고 momentum_s={elig[tk].get("momentum_s",0):+.2f})\n')

# 점수 보정 → 재정렬 (cr 당일)
dz=z_right-z_wrong
cur=elig[tk].get('score',0); new=cur+0.30*dz
allsc=sorted([(elig[t].get('score',0),elig[t]['name'],t) for t in elig],key=lambda x:-x[0])
cr_cur=[i for i,(_,_,t) in enumerate(allsc) if t==tk][0]+1
merged=sorted([(s2 if t!=tk else new, nm, t) for s2,nm,t in allsc],key=lambda x:-x[0])
cr_new=[i for i,(_,_,t) in enumerate(merged) if t==tk][0]+1
out.write(f'\n=== 디바이스 당일순위(cr) ===\n  현재(잘못): #{cr_cur}\n  보정 후:    #{cr_new}\n')
out.write('\n보정 후 상위 6:\n')
for i,(sc,nm,t) in enumerate(merged[:6]): out.write(f'  #{i+1} {nm} ({sc:+.3f})\n')
out.close(); print('done')
