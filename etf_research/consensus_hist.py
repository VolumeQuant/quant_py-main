"""consensus 신규편입 — 연도별(다국면) 재검증. _cache/holdings_hist.parquet(분기 2023~) 사용.
벤치=액티브 유니버스 EW. 실행: python etf_research/consensus_hist.py
"""
import sys
from pathlib import Path
import pandas as pd, numpy as np
sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(__file__).resolve().parent.parent; C=Path(__file__).parent/'_cache'
FWD=20
h=pd.read_parquet(C/'holdings_hist.parquet'); h['stock']=h['stock'].astype(str).str.zfill(6)
snaps=sorted(h['snap'].unique())
ohlcv=pd.read_parquet(ROOT/'data_cache'/'all_ohlcv_20170601_20260522.parquet').replace(0,np.nan)
od=ohlcv.index; lastd=od[-1]
def fwd(stock,snap,k=FWD):
    ts=pd.Timestamp(snap)
    if ts>lastd or stock not in ohlcv.columns: return None
    pos=od.searchsorted(ts)
    if pos+k>=len(od): return None
    p0,p1=ohlcv.iloc[pos][stock],ohlcv.iloc[pos+k][stock]
    if pd.isna(p0) or pd.isna(p1) or p0<=0: return None
    return p1/p0-1
rows=[]
for i in range(1,len(snaps)):
    sp,sc=snaps[i-1],snaps[i]
    prev=h[h.snap==sp].groupby('etf')['stock'].apply(set).to_dict()
    cur=h[h.snap==sc]
    uni=[s for s in cur['stock'].unique()]; uf=[fwd(s,sc) for s in uni]; uf=[x for x in uf if x is not None]
    if not uf: continue
    ew=np.mean(uf)
    newc={}
    for etf,g in cur.groupby('etf'):
        pv=prev.get(etf)
        if not pv: continue
        for s in set(g['stock'])-pv: newc[s]=newc.get(s,0)+1
    for s,n in newc.items():
        f=fwd(s,sc)
        if f is not None: rows.append({'snap':sc,'year':sc[:4],'stock':s,'n':n,'fwd':f,'ew':ew})
bt=pd.DataFrame(rows)
if len(bt):
    bt['exc']=bt['fwd']-bt['ew']
    print(f"검증 {len(bt)}건 (벤치=액티브 유니버스 EW, fwd {FWD}d, 분기전이)", flush=True)
    print(f"\n=== 전체 N별 ===", flush=True)
    for lbl,c in [('N=1',bt.n==1),('N=2',bt.n==2),('N>=3',bt.n>=3)]:
        s=bt[c]
        if len(s): print(f"  {lbl}: {len(s)}건 초과(vsEW) {s.exc.mean()*100:+.2f}% 승률 {(s.exc>0).mean()*100:.0f}%", flush=True)
    print(f"\n=== 연도별 (N>=2 합의) 초과(vs EW) ===", flush=True)
    for y in sorted(bt.year.unique()):
        s=bt[(bt.year==y)&(bt.n>=2)]
        if len(s): print(f"  {y}: {len(s)}건 초과 {s.exc.mean()*100:+.2f}% 승률 {(s.exc>0).mean()*100:.0f}%", flush=True)
    print("\n판정: 매 연도 N>=2 초과 양수 = robust. 강세장만이면 국면의존.", flush=True)
else:
    print("데이터 부족", flush=True)
