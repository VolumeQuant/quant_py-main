"""v80 전체 state 재생성 — boost + defense 병렬 subprocess
state/ + state/defense/ + bt_extended/ + bt_extended_defense/

v80 파라미터:
  공격: V15Q0G55M30, 2f rev+oca(0.6/0.4), 12m, E3X6S3
  방어: V30Q15G15M40, 2f rev+oca(0.7/0.3), 6m-1m, E3X6S5
"""
import os, sys, time, subprocess
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

PYTHON = sys.executable
FG = str(Path(__file__).parent / 'fast_generate_rankings_v2.py')
PROJECT = Path(__file__).parent.parent

BOOST_ENV = {
    'FACTOR_V_W': '0.15',
    'FACTOR_Q_W': '0.00',
    'FACTOR_G_W': '0.55',
    'FACTOR_M_W': '0.30',
    'G_SUB1': 'rev_z',
    'G_SUB2': 'oca_z',
    'G_REVENUE_WEIGHT': '0.6',
    'MOM_PERIOD': '12m',
    'PYTHONIOENCODING': 'utf-8',
}
DEFENSE_ENV = {
    'FACTOR_V_W': '0.30',
    'FACTOR_Q_W': '0.15',
    'FACTOR_G_W': '0.15',
    'FACTOR_M_W': '0.40',
    'G_SUB1': 'rev_z',
    'G_SUB2': 'oca_z',
    'G_REVENUE_WEIGHT': '0.7',
    'MOM_PERIOD': '6m-1m',
    'PYTHONIOENCODING': 'utf-8',
}

jobs = [
    ('boost_bt_ext',  '20180702', '20201230', str(PROJECT / 'backtest' / 'bt_extended'),          BOOST_ENV),
    ('boost_state',   '20210104', '20260511', str(PROJECT / 'state'),                             BOOST_ENV),
    ('def_bt_ext',    '20180702', '20201230', str(PROJECT / 'backtest' / 'bt_extended_defense'),   DEFENSE_ENV),
    ('def_state',     '20210104', '20260511', str(PROJECT / 'state' / 'defense'),                 DEFENSE_ENV),
]

print(f'v80 전체 재생성 시작 — 4작업 (2병렬 × 2순차)')
print(f'  공격: V15Q0G55M30 2f(rev60+oca40) 12m')
print(f'  방어: V30Q15G15M40 2f(rev70+oca30) 6m-1m')
print()

# 2병렬: boost(bt_ext+state) + defense(bt_ext+state)
# 실제로는 4개를 2그룹으로 나눠서 순차
t0 = time.time()

for batch_name, batch_jobs in [
    ('Batch 1 (boost+defense bt_ext)', [jobs[0], jobs[2]]),
    ('Batch 2 (boost+defense state)', [jobs[1], jobs[3]]),
]:
    print(f'\n{batch_name}:', flush=True)
    processes = []
    for label, s, e, sdir, env in batch_jobs:
        merged = {**os.environ, **env}
        log_path = str(PROJECT / 'logs' / f'v80_regen_{label}.log')
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        logf = open(log_path, 'w', encoding='utf-8')
        cmd = [PYTHON, '-u', FG, s, e, f'--state-dir={sdir}']
        p = subprocess.Popen(cmd, cwd=str(PROJECT), env=merged,
                             stdout=logf, stderr=subprocess.STDOUT,
                             text=True, encoding='utf-8', errors='replace')
        processes.append((label, p, logf, time.time()))
        print(f'  [{label}] PID={p.pid} ({s}~{e}) → {sdir}', flush=True)

    for label, p, logf, ts in processes:
        rc = p.wait()
        logf.close()
        elapsed = time.time() - ts
        print(f'  [{label}] rc={rc} ({elapsed/60:.1f}분)', flush=True)

total = time.time() - t0
print(f'\n=== v80 재생성 완료: {total/60:.1f}분 ({total:.0f}초) ===', flush=True)
