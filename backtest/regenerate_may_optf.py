"""5/1 ~ 5/11 옵션F 적용 ranking 생성 — state_new/에 추가
bt_optf는 4/30까지. 5/1~5/11 (5거래일) 추가 필요.
"""
import os, sys, time, subprocess
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

PYTHON = sys.executable
FG = str(Path(__file__).parent / 'fast_generate_rankings_v2.py')
PROJECT = Path(__file__).parent.parent

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
    ('may_boost', '20260501', '20260511', str(PROJECT / 'state_new'),         BOOST_ENV),
    ('may_def',   '20260501', '20260511', str(PROJECT / 'state_new' / 'defense'), DEFENSE_ENV),
]

print(f'5/1~5/11 옵션F ranking 생성 — boost + defense 2병렬')
t0 = time.time()
processes = []
for label, s, e, sdir, env in jobs:
    Path(sdir).mkdir(parents=True, exist_ok=True)
    merged = {**os.environ, **env}
    log_path = str(PROJECT / 'logs' / f'may_optf_{label}.log')
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    logf = open(log_path, 'w', encoding='utf-8')
    cmd = [PYTHON, '-u', FG, s, e, f'--state-dir={sdir}']
    p = subprocess.Popen(cmd, cwd=str(PROJECT), env=merged,
                         stdout=logf, stderr=subprocess.STDOUT,
                         text=True, encoding='utf-8', errors='replace')
    processes.append((label, p, logf, time.time()))
    print(f'  [{label}] PID={p.pid} → {sdir}', flush=True)

for label, p, logf, ts in processes:
    rc = p.wait()
    logf.close()
    elapsed = time.time() - ts
    print(f'  [{label}] rc={rc} ({elapsed/60:.1f}분)', flush=True)

total = time.time() - t0
print(f'\n=== 5월 옵션F ranking 완료: {total/60:.1f}분 ===', flush=True)
