# -*- coding: utf-8 -*-
"""production boost state authoritative rebuild (v80.23, W=0.2).
- state_peg_bt (FG가 계산·저장한 authoritative overheat_pen) 를 W=0.2 fold → composite_rank/score
  (FG W=0.2 출력과 수학적으로 정확히 동일)
- per/pbr/roe 는 backup(production)에서 ticker별 이식 (표시용)
- state_peg_bt에 없는 날짜(2018 + 만성실패일)는 backup 그대로 (un-penned, 데이터 sparse라 무방)
- weighted_rank 전역 재계산 (production _postprocess 동일: T-1/T-2 Top20 cr, penalty50, 0.4/0.35/0.25)
- defense/ 는 건드리지 않음
"""
import sys, json, glob, time
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
t0=time.time()
W=0.2; PENALTY=50
BACKUP=Path('state_backup_v8023'); PEG=Path('backtest/state_peg_bt'); OUT=Path('state')

# backup per/pbr/roe 맵 (date -> {tk: (per,pbr,roe)})
def load_ppr(d):
    fp=BACKUP/f'ranking_{d}.json'
    if not fp.exists(): return {}
    rows=json.load(open(fp,encoding='utf-8')).get('rankings',[])
    return {str(r['ticker']).zfill(6):(r.get('per'),r.get('pbr'),r.get('roe')) for r in rows}

backup_files={f.stem.replace('ranking_',''):f for f in BACKUP.glob('ranking_*.json')
              if f.stem.replace('ranking_','').isdigit() and len(f.stem.replace('ranking_',''))==8}
peg_files={f.stem.replace('ranking_',''):f for f in PEG.glob('ranking_*.json')
           if f.stem.replace('ranking_','').isdigit() and len(f.stem.replace('ranking_',''))==8}
all_dates=sorted(backup_files.keys())
print(f'backup {len(backup_files)} | peg {len(peg_files)} | 처리 {len(all_dates)}',flush=True)

# Pass1: 각 날짜 파일 구성 (authoritative fold or backup) → 메모리
out_data={}; cr_top20={}
n_auth=0; n_keep=0
for d in all_dates:
    base=json.load(open(backup_files[d],encoding='utf-8'))
    if d in peg_files:
        pegd=json.load(open(peg_files[d],encoding='utf-8'))
        rows=pegd.get('rankings',[])
        ppr=load_ppr(d)
        for r in rows:
            tk=str(r['ticker']).zfill(6)
            pen=r.get('overheat_pen',0.0) or 0.0
            r['score']=round((r.get('score',0.0) or 0.0)+W*pen,4)   # fold W=0.2
            pp=ppr.get(tk,(None,None,None))
            if pp[0] is not None: r['per']=pp[0]
            if pp[1] is not None: r['pbr']=pp[1]
            if pp[2] is not None: r['roe']=pp[2]
        order=sorted(range(len(rows)),key=lambda i:(-rows[i]['score'],i))
        for cr,i in enumerate(order,1): rows[i]['composite_rank']=cr
        base['rankings']=rows
        n_auth+=1
    else:
        rows=base.get('rankings',[])
        n_keep+=1
    cr_top20[d]={str(r['ticker']).zfill(6):r.get('composite_rank',r.get('rank',PENALTY))
                 for r in base.get('rankings',[]) if r.get('composite_rank',r.get('rank',999))<=20}
    out_data[d]=base
print(f'Pass1: authoritative {n_auth}, backup유지 {n_keep}, {time.time()-t0:.0f}s',flush=True)

# Pass2: wr 재계산 + 저장
for idx,d in enumerate(all_dates):
    base=out_data[d]; rows=base.get('rankings',[])
    if not rows:
        json.dump(base,open(OUT/f'ranking_{d}.json','w',encoding='utf-8'),ensure_ascii=False); continue
    prev=[x for x in all_dates if x<d]
    t1=cr_top20.get(prev[-1],{}) if len(prev)>=1 else {}
    t2=cr_top20.get(prev[-2],{}) if len(prev)>=2 else {}
    for r in rows:
        tk=str(r['ticker']).zfill(6)
        r0=r.get('composite_rank',r.get('rank',PENALTY))
        r['weighted_rank']=round(r0*0.4+t1.get(tk,PENALTY)*0.35+t2.get(tk,PENALTY)*0.25,1)
    rows.sort(key=lambda x:(x['weighted_rank'],-x.get('score',0)))
    for i,r in enumerate(rows,1): r['rank']=i
    json.dump(base,open(OUT/f'ranking_{d}.json','w',encoding='utf-8'),ensure_ascii=False)
print(f'Pass2 wr+저장 완료: {len(all_dates)} 파일, {time.time()-t0:.0f}s',flush=True)
