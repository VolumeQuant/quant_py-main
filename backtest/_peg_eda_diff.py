# -*- coding: utf-8 -*-
"""v80.22(패널티前) vs v80.23(과열캡) 순위 변화 EDA.
깨끗한 분리: state_peg_bt의 base score(W=0) vs score+0.2*pen(W=0.2) — 같은 base, 패널티만 토글.
+ 실제 매매(wr top-3 진입) 변화 + 패널티 분포 + 최다 강등 종목."""
import json, glob, sys, bisect
from pathlib import Path
from collections import defaultdict
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
W=0.2; PEG=Path('backtest/state_peg_bt'); PENALTY=50; TOP_N=20
kospi=pd.read_parquet('data_cache/kospi_yf.parquet')['close'].sort_index()

# 로드: date -> rows(tk, base_score, pen, name, sector, per)
DATA={}
for f in sorted(PEG.glob('ranking_*.json')):
    ds=f.stem.replace('ranking_','')
    if not(ds.isdigit() and len(ds)==8): continue
    d=json.load(open(f,encoding='utf-8')); rows=d.get('rankings',[])
    if not rows: continue
    DATA[ds]=[(str(r['ticker']).zfill(6), r.get('score',0.0) or 0.0, r.get('overheat_pen',0.0) or 0.0,
              r.get('name',''), r.get('sector',''), r.get('per')) for r in rows]
dates=sorted(DATA); print(f'분석 {len(dates)}일 ({dates[0]}~{dates[-1]})',flush=True)

def ranks(rows, w):
    items=sorted(range(len(rows)), key=lambda i:(-(rows[i][1]+w*rows[i][2]), i))
    return {rows[i][0]:r+1 for r,i in enumerate(items)}

# ── 1) 패널티 분포 ──
allpen=[p for ds in dates for (_,_,p,_,_,_) in DATA[ds]]
allpen=np.array(allpen)
print('\n【1】 패널티(pen) 분포 (전 종목-일)')
print(f'  총 {len(allpen):,} 관측 | 감점(pen<0) {np.mean(allpen<0)*100:.1f}% | pen=0 {np.mean(allpen==0)*100:.1f}%')
print(f'  감점 종목 평균 pen {allpen[allpen<0].mean():.3f} | 최저(최과열) {allpen.min():.3f}')
print(f'  일평균 감점 종목수 {np.mean([sum(1 for x in DATA[d] if x[2]<0) for d in dates]):.0f} / 일평균 종목수 {np.mean([len(DATA[d]) for d in dates]):.0f}')

# ── 2) composite_rank 변화 (순수 패널티 효과) ──
dcr=[]; demote=defaultdict(list)
for ds in dates:
    rb=ranks(DATA[ds],0.0); rp=ranks(DATA[ds],W)
    for (tk,sc,pen,nm,sec,per) in DATA[ds]:
        d=rp[tk]-rb[tk]   # +강등
        dcr.append(d)
        if d!=0: demote[(tk,nm)].append(d)
dcr=np.array(dcr)
print('\n【2】 composite_rank 변화량 Δ (양수=강등, 패널티 순수효과)')
print(f'  변동 종목 비율 {np.mean(dcr!=0)*100:.1f}% | 평균 Δ {dcr.mean():+.2f} | 중앙값 {np.median(dcr):+.0f}')
print(f'  강등(Δ>0) {np.mean(dcr>0)*100:.1f}% | 승격(Δ<0) {np.mean(dcr<0)*100:.1f}%')
print(f'  |Δ| 분포: 평균 {np.abs(dcr).mean():.1f} | p50 {np.percentile(np.abs(dcr),50):.0f} | p90 {np.percentile(np.abs(dcr),90):.0f} | p99 {np.percentile(np.abs(dcr),99):.0f} | 최대 {np.abs(dcr).max()}')

# ── 3) 실제 매매: wr top-3 진입 변화 (boost일만) ──
def regime_cross(ds_list):
    sma=kospi.rolling(20).mean();lma=kospi.rolling(80).mean();reg={};md=False;stk=0;ss=None
    for d in ds_list:
        ts=pd.Timestamp(d);sv=sma.get(ts);lv=lma.get(ts)
        if sv is None or pd.isna(sv) or pd.isna(lv): reg[d]=md;continue
        s=sv>lv
        if s==ss: stk+=1
        else: stk=1;ss=s
        if stk>=5 and md!=s: md=s
        reg[d]=md
    return reg
reg=regime_cross(dates)
def wr_top(w, k=3):
    """각 boost일의 wr 상위 k 집합."""
    crc={d:ranks(DATA[d],w) for d in dates}
    top={}
    for i,d in enumerate(dates):
        if not reg.get(d,True): continue
        cr0=crc[d]; cr1=crc[dates[i-1]] if i>=1 else {}; cr2=crc[dates[i-2]] if i>=2 else {}
        t1={tk:c for tk,c in cr1.items() if c<=TOP_N}; t2={tk:c for tk,c in cr2.items() if c<=TOP_N}
        wr={tk:c*0.4+t1.get(tk,PENALTY)*0.35+t2.get(tk,PENALTY)*0.25 for tk,c in cr0.items()}
        top[d]=[tk for tk,_ in sorted(wr.items(),key=lambda x:x[1])[:k]]
    return top
base_top=wr_top(0.0); pen_top=wr_top(W)
nm_map={tk:nm for ds in dates for (tk,_,_,nm,_,_) in DATA[ds]}
changed_days=0; added=defaultdict(int); removed=defaultdict(int)
for d in pen_top:
    if d not in base_top: continue
    bs=set(base_top[d]); ps=set(pen_top[d])
    if bs!=ps:
        changed_days+=1
        for tk in ps-bs: added[tk]+=1
        for tk in bs-ps: removed[tk]+=1
nboost=len(pen_top)
print(f'\n【3】 실제 매매 영향 — 진입 top-3(wr) 변화 (boost {nboost}일)')
print(f'  top-3 매수리스트 바뀐 날: {changed_days}/{nboost} ({changed_days/nboost*100:.1f}%)')
print('  과열로 매수후보서 빠진 종목 Top (제외 일수):')
for (tk),c in sorted(removed.items(),key=lambda x:-x[1])[:8]:
    print(f'    {nm_map.get(tk,tk):<12} {c}일 제외')
print('  대신 진입한 종목 Top (진입 일수):')
for (tk),c in sorted(added.items(),key=lambda x:-x[1])[:8]:
    print(f'    {nm_map.get(tk,tk):<12} {c}일 진입')

# ── 4) 최다 강등 종목 (누적) ──
print('\n【4】 과열로 가장 많이 강등된 종목 (누적 Δrank 합, 전 기간)')
agg=[(nm, sum(v), len(v), np.mean(v)) for (tk,nm),v in demote.items() if sum(v)>0]
agg.sort(key=lambda x:-x[1])
print(f'  {"종목":<12}{"누적강등":>8}{"강등일수":>8}{"평균Δ":>8}')
for nm,tot,n,avg in agg[:12]:
    print(f'  {nm:<12}{tot:>8}{n:>8}{avg:>+8.1f}')

# ── 5) 패널티 vs PER 관계 (과열캡이 비싼 종목 겨냥하나) ──
print('\n【5】 패널티 vs 표시PER (과열캡이 고PER 겨냥 검증, 06-05 표본)')
last=DATA[dates[-1]]
hi=[per for (_,_,p,_,_,per) in last if p<-0.5 and per]
lo=[per for (_,_,p,_,_,per) in last if p==0 and per]
if hi and lo:
    print(f'  강한감점(pen<-0.5) 종목 평균 PER {np.mean(hi):.1f} (n={len(hi)})')
    print(f'  무감점(pen=0) 종목 평균 PER {np.mean(lo):.1f} (n={len(lo)})')
