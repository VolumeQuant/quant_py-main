"""consensus 공정벤치 검증: 신규편입이 '액티브 유니버스 동일가중 평균'을 이기나?
KOSPI(메가캡 cap-weight 멜트업) 대신, 운용자들이 담는 종목 전체의 EW 평균을 벤치로 → 선택 스킬 순수 측정.
실행: python etf_research/consensus_fair.py
"""
import sys
from pathlib import Path
import pandas as pd, numpy as np
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parent.parent
C = Path(__file__).parent / '_cache'
FWD = 20
h = pd.read_parquet(C/'holdings.parquet'); h['stock']=h['stock'].astype(str).str.zfill(6)
snaps = sorted(h['snap'].unique())
ohlcv = pd.read_parquet(ROOT/'data_cache'/'all_ohlcv_20170601_20260522.parquet').replace(0,np.nan)
od = ohlcv.index; lastd = od[-1]

def fwd(stock, snap, k=FWD):
    ts = pd.Timestamp(snap)
    if ts>lastd or stock not in ohlcv.columns: return None
    pos = od.searchsorted(ts)
    if pos+k>=len(od): return None
    p0,p1 = ohlcv.iloc[pos][stock], ohlcv.iloc[pos+k][stock]
    if pd.isna(p0) or pd.isna(p1) or p0<=0: return None
    return p1/p0-1

rows=[]
for i in range(1,len(snaps)):
    sp,sc = snaps[i-1],snaps[i]
    prev = h[h.snap==sp].groupby('etf')['stock'].apply(set).to_dict()
    cur = h[h.snap==sc]
    # 유니버스 EW 벤치 (sc 보유 전체 종목 고유)
    uni = [s for s in cur['stock'].unique()]
    uni_f = [fwd(s,sc) for s in uni]; uni_f=[x for x in uni_f if x is not None]
    if not uni_f: continue
    ew = np.mean(uni_f)
    # 신규편입 by N
    newc={}
    for etf,g in cur.groupby('etf'):
        pv=prev.get(etf)
        if not pv: continue
        for s in set(g['stock'])-pv: newc[s]=newc.get(s,0)+1
    for s,n in newc.items():
        f=fwd(s,sc)
        if f is not None: rows.append({'snap':sc,'stock':s,'n':n,'fwd':f,'ew':ew})
bt=pd.DataFrame(rows)
if len(bt):
    bt['exc']=bt['fwd']-bt['ew']
    print(f"검증 {len(bt)}건 (벤치=액티브 유니버스 EW 평균, forward {FWD}d)", flush=True)
    print(f"{'코호트':<14}{'건수':>6}{'평균fwd':>9}{'EW벤치':>9}{'초과(vs EW)':>11}{'승률':>7}", flush=True)
    for lbl,c in [('N=1',bt.n==1),('N=2',bt.n==2),('N>=3',bt.n>=3),('전체',bt.n>=1)]:
        s=bt[c]
        if len(s): print(f"{lbl:<14}{len(s):>6}{s.fwd.mean()*100:>+8.2f}%{s.ew.mean()*100:>+8.2f}%{s.exc.mean()*100:>+10.2f}%{(s.exc>0).mean()*100:>6.0f}%", flush=True)
    print(f"\n판정: 초과(vs EW)가 양수+N커질수록↑ 면 운용자 선택스킬 존재(메가캡멜트업과 무관). 음수면 스킬 없음.", flush=True)
