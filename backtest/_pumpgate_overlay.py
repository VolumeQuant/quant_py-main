# -*- coding: utf-8 -*-
"""펌프게이트 오버레이 — 기존 state에 (이격도>1.4 & growth_s<0.5 → score-999, 재랭킹) 적용.
FG 마지막단계와 동일 연산. VERIFY=날짜 → 그 날만 검증출력. APPLY=1 → 전체 적용+wr 재계산+swap백업."""
import sys, os, glob, json, shutil
sys.path.insert(0,'C:/dev')
import numpy as np, pandas as pd
import run_daily as RD
PUMP_DISP=1.4; PUMP_GROWTH=1.5
# 이격도: OHLCV(raw) biz행 close/MA20 (FG와 동일)
ohlcv=sorted(glob.glob('C:/dev/data_cache/all_ohlcv_2017*_20260*.parquet'))[-1]
px=pd.read_parquet(ohlcv).replace(0,np.nan)
ne=px.notna().sum(axis=1) >= (px.shape[1]*0.5)
biz=px.loc[ne]
biz_disp=biz/biz.rolling(20).mean()
bidx={d:i for i,d in enumerate(biz.index.strftime('%Y%m%d'))}
bcol={c:j for j,c in enumerate(biz.columns)}; darr=biz_disp.values
def disp_of(tk,d):
    i=bidx.get(d); j=bcol.get(tk)
    if i is None or j is None: return None
    v=darr[i,j]; return float(v) if v==v else None
def apply_file(path):
    """한 state 파일에 펌프게이트 점수-999 + composite_rank 재계산. 변경수 반환."""
    d=os.path.basename(path)[8:16]
    data=json.load(open(path,encoding='utf-8')); rk=data['rankings']; ch=0
    for r in rk:
        dv=disp_of(r['ticker'],d); gv=r.get('growth_s',0) or 0
        if dv is not None and dv>PUMP_DISP and gv<PUMP_GROWTH:
            if r.get('score',0)!=-999.0:
                r['score']=-999.0; ch+=1
    if ch:
        # composite_rank 재계산 (score desc, 동점 안정)
        order=sorted(range(len(rk)), key=lambda i:(-rk[i]['score'], rk[i]['ticker']))
        for newcr,i in enumerate(order,1): rk[i]['composite_rank']=newcr
        json.dump(data, open(path,'w',encoding='utf-8'), ensure_ascii=False, indent=2)
    return ch
V=os.environ.get('VERIFY')
if V:
    p=f'C:/dev/state/ranking_{V}.json'
    rk=json.load(open(p,encoding='utf-8'))['rankings']
    g=[x for x in rk if x['ticker']=='002990']
    if g: print(f"적용 전 금호: cr{g[0]['composite_rank']} score{g[0].get('score'):.2f} 이격도{disp_of('002990',V)} growth{g[0]['growth_s']}")
    ch=apply_file(p)
    rk=json.load(open(p,encoding='utf-8'))['rankings']
    g=[x for x in rk if x['ticker']=='002990']
    print(f"적용 후 금호: cr{g[0]['composite_rank']} score{g[0].get('score'):.2f} (변경 {ch}종목)")
    print("top5 cr:", [(x['composite_rank'],x['ticker']) for x in sorted(rk,key=lambda z:z['composite_rank'])[:5]])
    sys.exit()
if os.environ.get('APPLY')=='1':
    if not os.path.exists('C:/dev/state_bak_pregate'):
        shutil.copytree('C:/dev/state','C:/dev/state_bak_pregate',ignore=shutil.ignore_patterns('*.tmp'))
        print('[백업] state/ → state_bak_pregate')
    tot=0; days_ch=0
    for sub,mode in [('','boost'),('/defense','defense')]:
        sdir='C:/dev/state'+sub
        files=sorted(glob.glob(f'{sdir}/ranking_*.json'))
        files=[f for f in files if os.path.basename(f)[8:16].isdigit() and len(os.path.basename(f)[8:16])==8]
        ds=sorted(os.path.basename(f)[8:16] for f in files)
        affected=[]; sc=0
        for f in files:
            c=apply_file(f)
            if c: affected.append(os.path.basename(f)[8:16]); sc+=c
        # wr 재계산: 영향일 + 다음 2거래일(wr_D는 cr of D,D-1,D-2)만 → per/pbr 전체덮어쓰기 회피
        pos={d:i for i,d in enumerate(ds)}; pp=set()
        for a in affected:
            i=pos[a]
            for k in (0,1,2):
                if i+k < len(ds): pp.add(ds[i+k])
        for dt in sorted(pp): RD._postprocess_ranking(dt, sdir, mode, None)
        print(f'[{mode}] 점수차단 {sc}종목 / {len(affected)}일, wr 재계산 {len(pp)}일(영향+2거래일)')
        tot+=sc; days_ch+=len(affected)
    print(f'[완료] 총 차단 {tot}종목, 영향일 {days_ch}일')
