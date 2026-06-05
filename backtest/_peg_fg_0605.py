import os, sys, subprocess
from pathlib import Path
PY=sys.executable; FG='backtest/fast_generate_rankings_v2.py'
ENV={'FACTOR_V_W':'0.15','FACTOR_Q_W':'0.00','FACTOR_G_W':'0.55','FACTOR_M_W':'0.30',
 'G_SUB1':'rev_z','G_SUB2':'oca_z','G_SUB3':'gp_growth_z','G_W1':'0.4','G_W2':'0.4','G_W3':'0.2',
 'G_REVENUE_WEIGHT':'0.5','MOM_PERIOD':'12m','SEASONALITY_FORMULA':'curr','SEASONALITY_RATIO_THRESH':'1.4',
 'SEASONALITY_PENALTY':'0.3','SEASONALITY_EXEMPT_MM_THRESH':'0.2','G_QOQ_PENALTY':'D6',
 'G_QOQ_PENALTY_THRESHOLD':'20','G_QOQ_PENALTY_MULTIPLIER':'0.7','G_QOQ_SG6_THRESH':'0.06',
 'FACTOR_MOM_10_W':'0.05','FACTOR_VOL_LOW_W':'0.06','FACTOR_OVERHEAT_W':'0.2','PYTHONIOENCODING':'utf-8'}
Path('backtest/_peg_fg0605').mkdir(parents=True,exist_ok=True)
r=subprocess.run([PY,'-u',FG,'20260605','20260605','--state-dir=backtest/_peg_fg0605'],
  env={**os.environ,**ENV},capture_output=True,text=True,encoding='utf-8',errors='replace')
print('rc',r.returncode); print('\n'.join(r.stdout.splitlines()[-4:]))
