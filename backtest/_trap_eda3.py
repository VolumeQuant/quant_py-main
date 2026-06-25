# -*- coding: utf-8 -*-
"""왜 잃었나 — 베타(시장) vs 알파(종목), 진입 이격(추격), 일시 vs 영구."""
import sys, io, os, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pidx={d.strftime('%Y%m%d'):i for i,d in enumerate(prices.index)};parr=prices.values;pcol={c:i for i,c in enumerate(prices.columns)}
kc=pd.read_parquet(P+'/data_cache/kospi_yf.parquet').iloc[:,0]
kidx={d.strftime('%Y%m%d'):i for i,d in enumerate(kc.index)};karr=kc.values
df=pd.read_parquet(P+'/backtest/_trap_entries.parquet')
def sret(tk,d,h):
    if tk not in pcol or d not in pidx: return None
    i=pidx[d];ci=pcol[tk]
    if i+h>=len(parr) or i+h<0: return None
    p0,p1=parr[i,ci],parr[i+h,ci]
    return (p1/p0-1)*100 if(p0>0 and p1>0)else None
def kret(d,h):
    if d not in kidx: return None
    i=kidx[d]
    if i+h>=len(karr) or i+h<0: return None
    return (karr[i+h]/karr[i]-1)*100
df['k60']=[kret(d,60) for d in df['d']]
df['alpha60']=df['f60']-df['k60']
df['prior60']=[sret(tk,d,-60) for tk,d in zip(df['tk'],df['d'])]  # 진입 전 60일 (이격/추격)
df['prior20']=[sret(tk,d,-20) for tk,d in zip(df['tk'],df['d'])]
df['f120']=[sret(tk,d,120) for tk,d in zip(df['tk'],df['d'])]
v=df.dropna(subset=['f60','k60','alpha60']).copy()
los=v[v['f60']<0]; big=v[v['f60']<-15]
print(f"전체 {len(v)} / 패자 {len(los)} / 큰손실 {len(big)}\n")
# 1) 베타 vs 알파
print("=== 1. 시장(베타) vs 종목고유(알파) 분해 — 큰손실 65건 ===")
mkt=big[big['k60']<-8]  # 시장도 같이 빠진 (베타)
spec=big[big['alpha60']<-15]  # 시장 대비 크게 더 빠진 (종목고유)
print(f"  시장동반(k60<-8%): {len(mkt)}건 (평균 시장 {mkt['k60'].mean():.0f}%, 종목 {mkt['f60'].mean():.0f}%)")
print(f"  종목고유붕괴(alpha60<-15%p): {len(spec)}건 (평균 시장 {spec['k60'].mean():+.0f}%, 종목 {spec['f60'].mean():.0f}%, 알파 {spec['alpha60'].mean():.0f}%p)")
# 2) 진입 이격 (추격매수?)
print("\n=== 2. 진입 전 60일 수익률(이격/추격) — 승자 vs 패자 ===")
for nm,g in [('승자(f60>0)',v[v['f60']>0]),('패자(f60<0)',los),('큰손실(<-15)',big)]:
    gp=g.dropna(subset=['prior60'])
    print(f"  {nm}: 진입前60일 평균 {gp['prior60'].mean():+.0f}% (중앙 {gp['prior60'].median():+.0f}%), 진입前 +50%↑ 비율 {(gp['prior60']>50).mean()*100:.0f}%")
# 3) 일시 vs 영구 (f20 vs f60 vs f120)
print("\n=== 3. 일시낙폭 vs 영구손실 (큰손실 65건의 회복) ===")
b=big.dropna(subset=['f120'])
print(f"  진입後 f20 평균 {big['f20'].mean():+.0f}% → f60 {big['f60'].mean():+.0f}% → f120 {b['f120'].mean():+.0f}%")
print(f"  f120까지 회복(>0): {(b['f120']>0).mean()*100:.0f}%  / f120도 손실: {(b['f120']<0).mean()*100:.0f}%")
# 4) 큰손실 진입前 급등 종목 예시
print("\n=== 4. 진입前 급등(+50%↑) 후 큰손실 = 추격매수 끝물 ===")
chase=big[big['prior60']>50].sort_values('f60')
for _,x in chase.head(12).iterrows():
    print(f"  {x['d']} {x['nm'][:10]:10s} 진입前60일 {x['prior60']:+.0f}% → 진입後60일 {x['f60']:+.0f}% (mom={x['mom']:.1f} pbr={x['pbr']})")
