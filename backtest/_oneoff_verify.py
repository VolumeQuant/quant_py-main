# -*- coding: utf-8 -*-
"""일회성 페널티 표본검증: 2026-06-08 FG 재생성 ON/OFF 비교.
에스에이엠티(031330)/삼지(037460) 밀리고 제주반도체(080220)/엑시콘(092870) 보존 확인."""
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
runs={'OFF(penalty없음)':{'ONEOFF_DISABLE':'1','dir':'backtest/_oneoff_off'},
      'ON(penalty)':{'ONEOFF_DISABLE':'0','dir':'backtest/_oneoff_on'}}
res={}
for name,cfg in runs.items():
    Path(cfg['dir']).mkdir(parents=True,exist_ok=True)
    env={**os.environ,**BASE,'ONEOFF_DISABLE':cfg['ONEOFF_DISABLE']}
    r=subprocess.run([PY,'-u',FG,D,D,f'--state-dir={cfg["dir"]}'],env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
    pen=[l.strip() for l in r.stdout.splitlines() if '일회성' in l or '계절성' in l]
    print(f'--- {name} rc={r.returncode} ---')
    for l in pen: print('  ',l)
    f=Path(cfg['dir'])/f'ranking_{D}.json'
    if f.exists():
        d=json.load(open(f,encoding='utf-8'))
        res[name]={str(x['ticker']).zfill(6):x['rank'] for x in d['rankings']}
    else:
        print('   파일없음'); res[name]={}
print(f'\n{"종목":<22}{"OFF순위":>8}{"ON순위":>8}  변화')
for tk,nm in [('031330','에스에이엠티(스캠)'),('037460','삼지전자(스캠)'),('080220','제주반도체(win)'),('092870','엑시콘(win)'),('000660','SK하이닉스(win)')]:
    o=res.get('OFF(penalty없음)',{}).get(tk,'-');n=res.get('ON(penalty)',{}).get(tk,'-')
    print(f'{nm:<22}{str(o):>8}{str(n):>8}')
