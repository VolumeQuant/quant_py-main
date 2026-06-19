# -*- coding: utf-8 -*-
"""mom/vol 가중치 그리드 BT — 효율경로용 baseline 재생성.
baseline 가중치(0.05/0.06)로 1회 재생성하되 mom_10_z/vol_low_z를 JSON에 저장.
START END STATEDIR 인자로 받음 (표본/전체 공용).
"""
import os, sys, time, subprocess
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

PYTHON = sys.executable
FG = str(Path(__file__).parent / 'fast_generate_rankings_v2.py')
PROJECT = Path(__file__).parent.parent

START = sys.argv[1]
END = sys.argv[2]
SDIR = sys.argv[3]

V80_22_BOOST = {
    'FACTOR_V_W': '0.15', 'FACTOR_Q_W': '0.00',
    'FACTOR_G_W': '0.55', 'FACTOR_M_W': '0.30',
    'G_SUB1': 'rev_z', 'G_SUB2': 'oca_z', 'G_SUB3': 'gp_growth_z',
    'G_W1': '0.4', 'G_W2': '0.4', 'G_W3': '0.2',
    'G_REVENUE_WEIGHT': '0.5',
    'MOM_PERIOD': '12m',
    'SEASONALITY_FORMULA': 'curr',
    'SEASONALITY_RATIO_THRESH': '1.4',
    'SEASONALITY_PENALTY': '0.3',
    'SEASONALITY_EXEMPT_MM_THRESH': '0.2',
    'G_QOQ_PENALTY': 'D6',
    'G_QOQ_PENALTY_THRESHOLD': '20',
    'G_QOQ_PENALTY_MULTIPLIER': '0.7',
    'G_QOQ_SG6_THRESH': '0.06',
    'FACTOR_MOM_10_W': '0.05',
    'FACTOR_VOL_LOW_W': '0.06',
    'PYTHONIOENCODING': 'utf-8',
}

Path(SDIR).mkdir(parents=True, exist_ok=True)
merged = {**os.environ, **V80_22_BOOST}
cmd = [PYTHON, '-u', FG, START, END, f'--state-dir={SDIR}', '--resume']
print(f'재생성 {START}~{END} → {SDIR}', flush=True)
t0 = time.time()
p = subprocess.run(cmd, cwd=str(PROJECT), env=merged)
print(f'\n완료 ({(time.time()-t0)/60:.1f}분, return {p.returncode})', flush=True)
