# -*- coding: utf-8 -*-
"""강도별(G×0.3/0.2/0.1) 2026-06-08 Top20 비교 — 좋은 종목 빠지나 확인."""
import os, sys, subprocess, json
from pathlib import Path
PY=sys.executable; FG='backtest/fast_generate_rankings_v2.py'
BASE={'FACTOR_V_W':'0.15','FACTOR_Q_W':'0.00','FACTOR_G_W':'0.55','FACTOR_M_W':'0.30',
 'G_SUB1':'rev_z','G_SUB2':'oca_z','G_SUB3':'gp_growth_z','G_W1':'0.4','G_W2':'0.4','G_W3':'0.2',
 'G_REVENUE_WEIGHT':'0.5','MOM_PERIOD':'12m','SEASONALITY_FORMULA':'curr','SEASONALITY_RATIO_THRESH':'1.4',
 'SEASONALITY_PENALTY':'0.3','SEASONALITY_EXEMPT_MM_THRESH':'0.2','G_QOQ_PENALTY':'D6',
 'G_QOQ_PENALTY_THRESHOLD':'20','G_QOQ_PENALTY_MULTIPLIER':'0.7','G_QOQ_SG6_THRESH':'0.06',
 'FACTOR_MOM_10_W':'0.05','FACTOR_VOL_LOW_W':'0.06','FACTOR_OVERHEAT_W':'0.2','PYTHONIOENCODING':'utf-8'}
D='20260608'
strengths={'0.3':'backtest/_st03','0.2':'backtest/_st02','0.1':'backtest/_st01'}
flagged_tk={}
for s,dr in strengths.items():
    Path(dr).mkdir(parents=True,exist_ok=True)
    env={**os.environ,**BASE,'ONEOFF_DISABLE':'0','ONEOFF_PENALTY':s}
    r=subprocess.run([PY,'-u',FG,D,D,f'--state-dir={dr}'],env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
    print(f'G×{s} rc={r.returncode}', [l.strip() for l in r.stdout.splitlines() if '일회성' in l])

nm=json.load(open('data_cache/ticker_names_cache.json',encoding='utf-8'))
def load(dr):
    f=Path(dr)/f'ranking_{D}.json'
    if not f.exists(): return {}
    d=json.load(open(f,encoding='utf-8'))['rankings']
    return {str(x['ticker']).zfill(6):(x['rank'],x.get('growth_s') or 0,x['score']) for x in d}
off=load('backtest/_oneoff_off'); on7=load('backtest/_oneoff_on')
r03=load('backtest/_st03'); r02=load('backtest/_st02'); r01=load('backtest/_st01')
offg={tk:v[1] for tk,v in off.items()}
# 페널티 걸린 종목 식별: off 대비 growth_s 깎인 종목
def flagged(rr):
    out=set()
    for tk,v in rr.items():
        og=offg.get(tk,0)
        if og>0 and v[1]>0 and v[1]<og*0.99: out.add(tk)
    return out
fl=flagged(r03)  # 걸린 집합(강도 무관 동일)
out=open('backtest/_strength_top20.txt','w',encoding='utf-8')
out.write(f'2026-06-08 강도별 순위 비교 (OFF=페널티없음)\n')
out.write(f'걸린 종목(B>25&C>0.7): {[nm.get(t,t) for t in fl]}\n\n')
# OFF Top20 기준으로, 각 강도에서 순위
off_sorted=sorted(off.items(),key=lambda x:x[1][0])[:22]
out.write(f'{"종목":<16}{"OFF":>5}{"×0.3":>6}{"×0.2":>6}{"×0.1":>6}  플래그\n')
for tk,v in off_sorted:
    name=nm.get(tk,tk)
    def rk(rr): return rr.get(tk,(None,))[0]
    fmt=lambda x: str(x) if x else '권외'
    flag='⚠️일회성' if tk in fl else ''
    out.write(f'{name:<16}{v[0]:>5}{fmt(rk(r03)):>6}{fmt(rk(r02)):>6}{fmt(rk(r01)):>6}  {flag}\n')
# 걸린 종목 강도별 순위 추적
out.write('\n[걸린 종목 강도별 순위]\n')
for tk in fl:
    name=nm.get(tk,tk)
    out.write(f'  {name}: OFF {off.get(tk,(0,))[0]}위 → ×0.3 {r03.get(tk,(0,))[0]} → ×0.2 {r02.get(tk,(0,))[0]} → ×0.1 {r01.get(tk,(0,))[0]}\n')
out.close();print('done')
