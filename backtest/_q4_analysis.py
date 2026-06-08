# -*- coding: utf-8 -*-
"""2025 Q4 최신 기간(2026-03-23~05-14) 분석:
① 그 기간 매매/보유 종목 (선익시스템·동아엘텍 박제 검증)
② 가격 변동에 따라 순위 바뀐 것 검증 (G 서브팩터 동결 vs rank 변동)
v80.22(backup) vs v80.23(current) 둘 다."""
import json, glob, sys
from pathlib import Path
from collections import defaultdict, Counter
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
W0=('20260323','20260514')
def dates_in(state):
    out=[]
    for f in sorted(Path(state).glob('ranking_*.json')):
        ds=f.stem.replace('ranking_','')
        if ds.isdigit() and len(ds)==8 and W0[0]<=ds<=W0[1]: out.append((ds,f))
    return out

def load(f):
    d=json.load(open(f,encoding='utf-8'))
    return d.get('rankings',[])

print(f'=== 기간 {W0[0]}~{W0[1]} (2025 Q4 최신) ===')
for label, state in [('v80.22 (전 버전, 실제 매매)','state_backup_v8023'),('v80.23 (과열캡 현재)','state')]:
    dts=dates_in(state)
    print(f'\n##### {label} — {len(dts)} 거래일 #####')
    # 일별 wr top3 (진입 후보) 집계
    top3_counter=Counter(); top1_counter=Counter(); held_days=Counter()
    name_of={}
    daily_top3=[]
    for ds,f in dts:
        rows=load(f)
        for r in rows: name_of[r['ticker']]=r.get('name','')
        srt=sorted(rows,key=lambda x:x.get('weighted_rank',999))
        t3=[r['ticker'] for r in srt[:3]]
        daily_top3.append((ds,[(r['ticker'],r.get('name'),r.get('weighted_rank')) for r in srt[:3]]))
        for tk in t3: top3_counter[tk]+=1
        if t3: top1_counter[t3[0]]+=1
    n=len(dts)
    print(f'  진입권(wr top3) 최다 종목 (등장일수/{n}):')
    for tk,c in top3_counter.most_common(6):
        print(f'    {name_of.get(tk,tk):<14} {c}일 ({c*100//n}%)')
    print(f'  서로 다른 top3 종목 수: {len(top3_counter)}개 (다양성)')
    # 선익시스템/동아엘텍
    for nm_q in ['선익시스템','동아엘텍']:
        tks=[tk for tk,nm in name_of.items() if nm_q in str(nm)]
        for tk in tks:
            print(f'  ▶ {nm_q}({tk}): top3 {top3_counter.get(tk,0)}일 등장')
