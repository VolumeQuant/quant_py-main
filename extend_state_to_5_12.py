"""state 4/28 ~ 5/12 추가 생성 (refresh 완료 후)"""
import os, sys, time, subprocess
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
PYTHON = sys.executable
PROJECT = Path(__file__).parent
FG = str(PROJECT / 'backtest' / 'fast_generate_rankings_v2.py')

BOOST_ENV = {
    'FACTOR_V_W': '0.15', 'FACTOR_Q_W': '0.00', 'FACTOR_G_W': '0.55', 'FACTOR_M_W': '0.30',
    'G_SUB1': 'rev_z', 'G_SUB2': 'oca_z', 'G_REVENUE_WEIGHT': '0.6', 'MOM_PERIOD': '12m',
    'PYTHONIOENCODING': 'utf-8',
}
DEFENSE_ENV = {
    'FACTOR_V_W': '0.30', 'FACTOR_Q_W': '0.15', 'FACTOR_G_W': '0.15', 'FACTOR_M_W': '0.40',
    'G_SUB1': 'rev_z', 'G_SUB2': 'oca_z', 'G_REVENUE_WEIGHT': '0.7', 'MOM_PERIOD': '6m-1m',
    'PYTHONIOENCODING': 'utf-8',
}
jobs = [
    ('boost_may', '20260428', '20260512', str(PROJECT / 'state'), BOOST_ENV),
    ('def_may',   '20260428', '20260512', str(PROJECT / 'state' / 'defense'), DEFENSE_ENV),
]
print('=== state 4/28~5/12 추가 (2병렬) ===')
t0 = time.time()
procs = []
for label, s, e, sdir, env in jobs:
    merged = {**os.environ, **env}
    logp = str(PROJECT / 'logs' / f'state_may_{label}.log')
    logf = open(logp, 'w', encoding='utf-8')
    cmd = [PYTHON, '-u', FG, s, e, f'--state-dir={sdir}']
    p = subprocess.Popen(cmd, env=merged, stdout=logf, stderr=subprocess.STDOUT,
                         text=True, encoding='utf-8', errors='replace')
    procs.append((label, p, logf, time.time()))
    print(f'  {label} PID={p.pid}', flush=True)
for label, p, logf, ts in procs:
    rc = p.wait()
    logf.close()
    print(f'  {label} rc={rc} ({(time.time()-ts)/60:.1f}분)', flush=True)
print(f'완료: {(time.time()-t0)/60:.1f}분')
