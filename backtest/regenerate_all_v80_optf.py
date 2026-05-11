"""v80 BT 옵션F 검증용 재생성 — production state는 건드리지 않음
backtest/bt_optf_boost/ + backtest/bt_optf_defense/ (각 2018-07~2026-04 7.8년 풀)

용도: 옵션 F (항목별 mismatch 자동 정정) 도입 후 BT 결과 비교
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
    ('boost_optf',   '20180702', '20260430', str(PROJECT / 'backtest' / 'bt_optf_boost'),   BOOST_ENV),
    ('def_optf',     '20180702', '20260430', str(PROJECT / 'backtest' / 'bt_optf_defense'), DEFENSE_ENV),
]

print(f'옵션F BT 재생성 — boost + defense 2병렬 (7.8년 풀)')
t0 = time.time()
processes = []
for label, s, e, sdir, env in jobs:
    Path(sdir).mkdir(parents=True, exist_ok=True)
    merged = {**os.environ, **env}
    log_path = str(PROJECT / 'logs' / f'v80_optf_{label}.log')
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
print(f'\n=== 옵션F BT 재생성 완료: {total/60:.1f}분 ({total:.0f}초) ===', flush=True)
