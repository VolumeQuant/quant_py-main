# -*- coding: utf-8 -*-
"""극단 tail + composite — 작은 cohort에 큰손실 몰린 함정 시그니처 탐색 (lumpiness식)."""
import sys, io, os, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# fwd120 추가
px=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(px.columns)};parr=px.values;pdi={d.strftime('%Y%m%d'):i for i,d in enumerate(px.index)}
df=pd.read_parquet(P+'/backtest/_creative_feats.parquet')
def fwd(tk,d,h):
    if tk not in pcol or d not in pdi: return None
    i=pdi[d];ci=pcol[tk]
    if i+h>=len(parr): return None
    p0,p1=parr[i,ci],parr[i+h,ci]
    return (p1/p0-1)*100 if(p0>0 and p1>0)else None
df['f120']=[fwd(tk,d,120) for tk,d in zip(df['tk'],df['d'])]
v=df.dropna(subset=['f60']).copy()
base_w=(v['f60']>0).mean()*100; base_m=v['f60'].mean()
print(f"전체 {len(v)}건: fwd60 {base_m:+.1f}% 승률{base_w:.0f}% / 큰손실(f60<-15) {(v['f60']<-15).mean()*100:.0f}%\n")
def tail(name,mask):
    g=v[mask].dropna(subset=['f60'])
    if len(g)<10: print(f"  {name}: n={len(g)} (too few)"); return
    bl=(g['f60']<-15).mean()*100; m=g['f60'].mean(); w=(g['f60']>0).mean()*100
    g2=g.dropna(subset=['f120']); m120=g2['f120'].mean() if len(g2) else np.nan
    print(f"  {name:34s} n={len(g):>3} fwd60 {m:>+6.1f}% 승률{w:>3.0f}% 큰손실{bl:>3.0f}% fwd120{m120:>+6.1f}%")
print("=== 단일 극단 tail ===")
tail('upratio20 >0.70 (쉼없이상승)', v['upratio20']>0.70)
tail('upratio20 >0.75', v['upratio20']>0.75)
tail('dpar120 상위15% (장기초과열)', v['dpar120']>v['dpar120'].quantile(0.85))
tail('dpar20 상위15%', v['dpar20']>v['dpar20'].quantile(0.85))
tail('rvol20 상위15% (고변동)', v['rvol20']>v['rvol20'].quantile(0.85))
tail('volsurge 상위15% (거래폭발)', v['volsurge']>v['volsurge'].quantile(0.85))
tail('voltrend 하위15% (거래량감소)', v['voltrend']<v['voltrend'].quantile(0.15))
tail('max1d20 상위15% (상한가스파이크)', v['max1d20']>v['max1d20'].quantile(0.85))
tail('asset_g 상위15% (자산급증=희석)', v['asset_g']>v['asset_g'].quantile(0.85))
print("\n=== composite (끝물 exhaustion 조합) ===")
# 끝물 = 많이올랐고(dpar20 상위절반) + 쉼없이(upratio 상위절반) + 거래량 식음(voltrend 하위절반)
m1=(v['upratio20']>0.6)&(v['dpar20']>v['dpar20'].median())
tail('상승끝물: upratio>0.6 & dpar20>중앙', m1)
m2=m1&(v['voltrend']<0)
tail(' +거래량감소(voltrend<0)', m2)
m3=(v['dpar120']>v['dpar120'].quantile(0.7))&(v['upratio20']>0.65)
tail('장기초과열 dpar120>70% & upratio>0.65', m3)
m4=(v['rvol20']>v['rvol20'].quantile(0.7))&(v['dpar20']>v['dpar20'].quantile(0.7))
tail('고변동+단기초과열 (rvol70 & dpar20_70)', m4)
# 작전주: 거래폭발+고변동+저유동성레벨
m5=(v['volsurge']>v['volsurge'].quantile(0.7))&(v['rvol20']>v['rvol20'].quantile(0.6))
tail('작전풍: 거래폭발+고변동', m5)
