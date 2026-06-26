import sqlite3, sys, io, os, glob
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np, pandas as pd
ROOT='C:/dev'
px=pd.read_parquet(sorted(glob.glob(ROOT+'/data_cache/all_ohlcv_adj_*.parquet'))[-1]).replace(0,np.nan)
pcol={c:i for i,c in enumerate(px.columns)};parr=px.values
tdays=[d.strftime('%Y%m%d') for d in px.index];tdi={d:i for i,d in enumerate(tdays)};last=tdays[-1]
nm=None
try: nm=__import__('json').load(open(ROOT+'/kr_eps_momentum/ticker_info_cache.json',encoding='utf-8'))
except: nm={}
def nameof(t):
    for k in (t,t+'.KS',t+'.KQ'):
        if k in nm: return nm[k].get('shortName',t)
    return t
c=sqlite3.connect(ROOT+'/kr_eps_momentum/eps_momentum_data_kr.db')
df=pd.read_sql('SELECT date,ticker,rank,composite_rank,score,price FROM ntm_screening',c)
df['tk']=df['ticker'].str[:6];df['d8']=df['date'].str.replace('-','')
def fwd(t,d):
    if t not in pcol or d not in tdi: return None
    p0=parr[tdi[d],pcol[t]];p1=parr[tdi[last],pcol[t]]
    return (p1/p0-1)*100 if p0>0 and p1>0 else None
df['fwd']=[fwd(t,d) for t,d in zip(df['tk'],df['d8'])]
o=df.dropna(subset=['fwd','composite_rank'])
o=o[o['d8']<last]
days=sorted(o['d8'].unique())
print(f"=== KR EPS 성과 — {len(days)}일 누적 (forward→{last}, 평균 보유 {(len(days))}거래일) ===")
print("※ 16일·overlap·단일에피소드 = 예비. 매매기록 없어 screening 픽 forward로 추정\n")
# 시장 벤치 (전체 픽 평균 = 시스템 유니버스 평균)
bench=o['fwd'].mean()
print(f"  유니버스 평균(벤치): {bench:+.2f}%\n")
print(f"  {'전략':18s}{'평균fwd':>9s}{'승률':>7s}{'벤치대비':>9s}")
for N,lab in [(3,'top3'),(5,'top5'),(10,'top10'),(20,'top20')]:
    s=o[o['composite_rank']<=N]
    if len(s)>0:
        print(f"  {lab:18s}{s['fwd'].mean():>+8.2f}%{(s['fwd']>0).mean()*100:>6.0f}%{s['fwd'].mean()-bench:>+8.2f}%p")
# rank 버킷
print(f"\n  [composite_rank 버킷별 forward]")
for lo,hi in [(1,5),(6,10),(11,20),(21,50),(51,999)]:
    s=o[(o['composite_rank']>=lo)&(o['composite_rank']<=hi)]
    if len(s)>0: print(f"    rank {lo}-{hi if hi<999 else 'max'}: n={len(s):4d} fwd {s['fwd'].mean():+.2f}% 승률{(s['fwd']>0).mean()*100:.0f}%")
ic=o['composite_rank'].corr(o['fwd'],method='spearman')
print(f"\n  composite_rank IC(낮을수록 좋아야 음수): {ic:+.3f}  (음수=랭킹 작동)")
# 첫날 top5 실명
d0=days[0]
print(f"\n  [{d0} top5 picks → {last} 수익]")
for _,r in o[(o['d8']==d0)&(o['composite_rank']<=5)].sort_values('composite_rank').iterrows():
    print(f"    {r['composite_rank']:.0f}위 {nameof(r['tk'])[:12]:12s} {r['fwd']:+.0f}%")
