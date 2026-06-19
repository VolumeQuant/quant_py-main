# -*- coding: utf-8 -*-
"""선익/동아를 무엇이 강등시켰나 — 동아 고점일(20260427) FG 필터 ON/OFF.
옛버전(필터X) 동아#1·선익#2 → 현재 8/37. 어떤 필터가 했나 식별."""
import os, sys, subprocess, json
from pathlib import Path
PY=sys.executable; FG='backtest/fast_generate_rankings_v2.py'
BASE={'FACTOR_V_W':'0.15','FACTOR_Q_W':'0.00','FACTOR_G_W':'0.55','FACTOR_M_W':'0.30',
 'G_SUB1':'rev_z','G_SUB2':'oca_z','G_SUB3':'gp_growth_z','G_W1':'0.4','G_W2':'0.4','G_W3':'0.2',
 'G_REVENUE_WEIGHT':'0.5','MOM_PERIOD':'12m','SEASONALITY_FORMULA':'curr','SEASONALITY_RATIO_THRESH':'1.4',
 'SEASONALITY_PENALTY':'0.3','SEASONALITY_EXEMPT_MM_THRESH':'0.2','G_QOQ_PENALTY':'D6',
 'G_QOQ_PENALTY_THRESHOLD':'20','G_QOQ_PENALTY_MULTIPLIER':'0.7','G_QOQ_SG6_THRESH':'0.06',
 'FACTOR_MOM_10_W':'0.05','FACTOR_VOL_LOW_W':'0.06','FACTOR_OVERHEAT_W':'0.2','PYTHONIOENCODING':'utf-8'}
D='20260427'
# 각 변형: 어떤 필터를 끄나
VARIANTS={
 'current(전부ON)':{},
 'overheat OFF':{'FACTOR_OVERHEAT_W':'0.0'},
 'vol_low OFF':{'FACTOR_VOL_LOW_W':'0.0'},
 'seasonality OFF':{'SEASONALITY_PENALTY':'1.0'},
 'qoq OFF':{'G_QOQ_PENALTY':''},
 'overheat+vol OFF':{'FACTOR_OVERHEAT_W':'0.0','FACTOR_VOL_LOW_W':'0.0'},
}
res={}
for name,ov in VARIANTS.items():
    dr=f'backtest/_dem_{abs(hash(name))%9999}'
    Path(dr).mkdir(parents=True,exist_ok=True)
    env={**os.environ,**BASE,**ov}
    r=subprocess.run([PY,'-u',FG,D,D,f'--state-dir={dr}'],env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
    f=Path(dr)/f'ranking_{D}.json'
    rk={}
    if f.exists():
        d=json.load(open(f,encoding='utf-8'))
        rk={str(x['ticker']).zfill(6):x['rank'] for x in d['rankings']}
    res[name]=rk
    print(f'{name:<18} rc={r.returncode}  동아={rk.get("088130","권외")}  선익={rk.get("171090","권외")}',flush=True)
