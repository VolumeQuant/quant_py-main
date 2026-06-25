# -*- coding: utf-8 -*-
"""sleeve 다방면 심층 EDA — 기대성장×fwd_per 2D, production rank 상호작용, 시총, IC.
look-ahead proxy(미래 실적으로 기대성장·fwd_per 계산). 패턴 방향 탐색용."""
import sys, io, os, glob, json, pickle
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
P=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
prices=pd.read_parquet(sorted(glob.glob(P+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(prices.columns)};parr=prices.values
tdays=[d.strftime('%Y%m%d') for d in prices.index];tdi={d:i for i,d in enumerate(tdays)}
cache=pickle.load(open(P+'/backtest/_earn_cache.pkl','rb'))
mc=pd.read_parquet(sorted(glob.glob(P+'/data_cache/market_cap_ALL_*.parquet'))[-1])
sh={t:mc.loc[t,'상장주식수'] for t in mc.index}
ar={};dts=[]
for f in sorted(glob.glob(P+'/state/ranking_*.json')):
    dt=os.path.basename(f)[8:16]
    if dt.isdigit() and len(dt)==8 and dt>='20190102' and dt in tdi:
        ar[dt]=json.load(open(f,encoding='utf-8'))['rankings'];dts.append(dt)
dts=sorted(dts)
prank={}  # production rank map
for d in dts: prank[d]={x['ticker']:x.get('rank',99) for x in ar[d]}
def ttm(t,d):
    dd=cache.get(t);s=dd.get('ni') if dd else None
    if s is None: return None
    v=s[1][s[0]<=np.datetime64(pd.Timestamp(d[:4]+'-'+d[4:6]+'-'+d[6:]))];return v[-4:].sum() if len(v)>=4 else None
def px(t,d):
    if t not in pcol or d not in tdi: return None
    v=parr[tdi[d],pcol[t]]; return float(v) if v>0 else None
def fwd(t,d,h):
    i=tdi[d]; d2=tdays[min(i+h,len(tdays)-1)]; p0=px(t,d); p1=px(t,d2)
    return (p1/p0-1)*100 if p0 and p1 else None
# 데이터셋: 매월 기대성장 계산되는 모든 종목 (풀 넓게)
rows=[]; seen=set()
for d in dts:
    if d[:6] in seen: continue
    seen.add(d[:6]); i=tdi[d]; d1=tdays[min(i+250,len(tdays)-1)]
    for t in cache:
        p0=px(t,d)
        if p0 is None or t not in sh or not(sh[t]>0): continue
        e0=ttm(t,d); e1=ttm(t,d1)
        if e0 and e0>0 and e1 is not None and e1>0:
            grow=e1/e0; fper=(p0*sh[t])/(e1*1e8)
            r20=fwd(t,d,20); r60=fwd(t,d,60)
            if r20 is not None and 0<fper<300:
                rows.append({'d':d,'t':t,'grow':grow,'fwdper':fper,'r20':r20,'r60':r60,
                             'prank':prank.get(d,{}).get(t,99),'mcap':p0*sh[t]/1e8})
df=pd.DataFrame(rows)
# 정상성장만(흑자전환 이상치 제외)
g=df[(df['grow']>=1.2)&(df['grow']<=5.0)].copy()
print(f"=== sleeve 다방면 EDA (정상성장 1.2~5x, n={len(g)}) ===\n")

print("【1】 기대성장 × fwd_per 2D — fwd60 수익률 교차표")
gq=pd.qcut(g['grow'],3,labels=['성장下','성장中','성장上'])
fq=pd.cut(g['fwdper'],[0,15,25,300],labels=['fwd_per<15','15~25','>25'])
piv=g.groupby([gq,fq],observed=True)['r60'].mean().unstack()
print(piv.round(1).to_string())
print("  → 행=기대성장, 열=fwd_per. 어느 조합이 최고인지\n")

print("【2】 기대성장 단독 효과 (fwd_per 통제 위해 5분위)")
for lbl,s in [('성장 1.2~1.5',g[g['grow']<1.5]),('1.5~2',g[(g['grow']>=1.5)&(g['grow']<2)]),
              ('2~3',g[(g['grow']>=2)&(g['grow']<3)]),('3~5',g[g['grow']>=3])]:
    print(f"  {lbl:<12} n={len(s):5d}  fwd60 {s['r60'].mean():+.1f}%  승률 {(s['r20']>0).mean()*100:.0f}%")

print("\n【3】 production rank 상호작용 (보유 top3 = rank<=3이 실제 sleeve 대상)")
for lbl,s in [('rank 1-3(보유)',g[g['prank']<=3]),('4-10',g[(g['prank']>3)&(g['prank']<=10)]),
              ('11-20',g[(g['prank']>10)&(g['prank']<=20)]),('20+',g[g['prank']>20])]:
    if len(s)>0:
        lo=s[s['fwdper']<20]; hi=s[s['fwdper']>=20]
        print(f"  {lbl:<14} n={len(s):5d}  fwd_per<20 {lo['r60'].mean():+.1f}%(n{len(lo)}) vs >=20 {hi['r60'].mean():+.1f}%(n{len(hi)})")

print("\n【4】 시총 상호작용 (fwd_per 신호가 대형/소형 어디서 강한가)")
for lbl,s in [('대형 1조+',g[g['mcap']>=10000]),('중형 3천~1조',g[(g['mcap']>=3000)&(g['mcap']<10000)]),
              ('소형 <3천억',g[g['mcap']<3000])]:
    lo=s[s['fwdper']<20]; hi=s[s['fwdper']>=20]
    print(f"  {lbl:<14} n={len(s):5d}  fwd_per<20 {lo['r60'].mean():+.1f}% vs >=20 {hi['r60'].mean():+.1f}%  (Δ{lo['r60'].mean()-hi['r60'].mean():+.1f})")

print("\n【5】 IC (Spearman) — 각 신호의 fwd60 예측력")
from scipy.stats import spearmanr
for nm,col,sign in [('기대성장(높을수록)','grow',1),('fwd_per(낮을수록)','fwdper',-1),
                    ('-log(fwdper)','fwdper',-1)]:
    x=sign*(np.log(g['fwdper']) if 'log' in nm else g[col]); ic=spearmanr(x,g['r60'])[0]
    print(f"  {nm:<20} IC={ic:+.4f}")
# 결합신호: 기대성장 z - fwd_per z
gz=(g['grow']-g['grow'].mean())/g['grow'].std(); fz=(np.log(g['fwdper'])-np.log(g['fwdper']).mean())/np.log(g['fwdper']).std()
for w in [0,0.5,1.0,1.5,2.0]:
    comb=gz - w*fz; ic=spearmanr(comb,g['r60'])[0]
    print(f"  결합: 성장z - {w}×fwd_per_z   IC={ic:+.4f}")
print("  → 결합 IC가 단독보다 높으면 두 축 합칠 가치")
g.to_pickle(P+'/backtest/_sleeve_eda_df.pkl')
print(f"\n[데이터셋 저장 → _sleeve_eda_df.pkl, n={len(g)}]")
