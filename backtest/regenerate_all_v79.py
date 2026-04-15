"""v79 전체 state 재생성 — boost + defense 병렬 subprocess
state/ 1294일 + state/defense/ 1294일 (2021-01-04 ~ 2026-04-14)
bt_extended/는 건드리지 않음 (시스템 수익률은 state/만 사용)

v79 파라미터:
  공격: V15Q5G50M30, 3f rev+oca+gp(0.5/0.3/0.2), 12m, E3X6S3
  방어: V30Q15G15M40, 2f rev+oca(0.7), 6m-1m, E3X6S7
"""
import os, sys, time, subprocess
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

PYTHON = 'C:/Users/user/miniconda3/envs/volumequant/python.exe'
FG = 'C:/dev/backtest/fast_generate_rankings_v2.py'

# v79 파라미터 (regime_indicator.py에서 확인)
BOOST_ENV = {
    'FACTOR_V_W': '0.15',
    'FACTOR_Q_W': '0.05',
    'FACTOR_G_W': '0.50',
    'FACTOR_M_W': '0.30',
    'G_SUB1': 'rev_z',
    'G_SUB2': 'oca_z',
    'G_SUB3': 'gp_growth_z',
    'G_W1': '0.5', 'G_W2': '0.3', 'G_W3': '0.2',
    'MOM_PERIOD': '12m',
    'PYTHONIOENCODING': 'utf-8',
}
DEFENSE_ENV = {
    'FACTOR_V_W': '0.30',
    'FACTOR_Q_W': '0.15',
    'FACTOR_G_W': '0.15',
    'FACTOR_M_W': '0.40',
    'G_SUB1': 'rev_z',          # v77.1의 rev_accel_z → rev_z
    'G_SUB2': 'oca_z',          # v77.1의 op_margin_z → oca_z
    'G_REVENUE_WEIGHT': '0.7',  # v77.1의 0.5 → 0.7
    'MOM_PERIOD': '6m-1m',
    'PYTHONIOENCODING': 'utf-8',
}

# 병렬 작업 (2워커 — prod만, bt_extended 불필요)
jobs = [
    ('boost_prod', '20210104', '20260414', 'state',          BOOST_ENV),
    ('def_prod',   '20210104', '20260414', 'state/defense',  DEFENSE_ENV),
]

print(f'v79 state 재생성 시작 — 2워커 병렬')
print(f'  boost_prod: state/ 1294일')
print(f'  def_prod:   state/defense/ 1294일')
print()

processes = []
t0 = time.time()
for label, s, e, sdir, env in jobs:
    merged_env = {**os.environ, **env}
    log_path = f'C:/dev/logs/v79_regen_{label}.log'
    logf = open(log_path, 'w', encoding='utf-8')
    cmd = [PYTHON, FG, s, e, '--state-dir', sdir]
    p = subprocess.Popen(cmd, cwd='C:/dev', env=merged_env,
                         stdout=logf, stderr=subprocess.STDOUT,
                         text=True, encoding='utf-8', errors='replace')
    processes.append((label, p, logf, time.time()))
    print(f'  [{label}] 시작 PID={p.pid}, log={log_path}', flush=True)

print(f'\n대기 중... (tail -f {log_path})', flush=True)
results = []
for label, p, logf, ts in processes:
    rc = p.wait()
    logf.close()
    elapsed = time.time() - ts
    results.append((label, rc, elapsed))
    print(f'  [{label}] 완료 rc={rc}, 소요 {elapsed:.1f}초', flush=True)

total = time.time() - t0
print(f'\n=== v79 재생성 완료: {total/60:.1f}분 ({total:.0f}초) ===', flush=True)
for label, rc, elapsed in results:
    status = 'OK' if rc == 0 else 'FAIL'
    print(f'  {label}: {status} ({elapsed/60:.1f}분)')
