"""v80.12 QoQ 패널티 옵션 ranking 재생성 — A/B 병렬
2026-05-18

옵션:
  A: qoq_op < -10% → G × 0.5
  B: qoq_op < -5% → G × 0.5
  baseline (D): v80.11 그대로 (이미 state/ 있음)

별도 디렉토리:
  state_v80_12_qoq_A
  state_v80_12_qoq_B

기간: 2019-01-02 ~ 2026-05-15 (v80.11 7.4y 기준)
"""
import os, sys, time, subprocess
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

PYTHON = sys.executable
FG = str(Path(__file__).parent / 'fast_generate_rankings_v2.py')
PROJECT = Path(__file__).parent.parent

# v80.11 boost 환경변수 (regenerate_all_v80.py 기준)
BOOST_BASE = {
    'FACTOR_V_W': '0.15',
    'FACTOR_Q_W': '0.00',
    'FACTOR_G_W': '0.55',
    'FACTOR_M_W': '0.30',
    'G_SUB1': 'rev_z',
    'G_SUB2': 'oca_z',
    'G_SUB3': 'gp_growth_z',
    'G_W1': '0.4',
    'G_W2': '0.4',
    'G_W3': '0.2',
    'G_REVENUE_WEIGHT': '0.5',
    'MOM_PERIOD': '12m',
    'SEASONALITY_FORMULA': 'curr',
    'SEASONALITY_RATIO_THRESH': '1.4',
    'SEASONALITY_PENALTY': '0.3',
    'SEASONALITY_EXEMPT_MM_THRESH': '0.2',  # v80.10
    'PYTHONIOENCODING': 'utf-8',
}

# QoQ 옵션 A + B
jobs = [
    ('qoq_A', '20190102', '20260515', str(PROJECT / 'state_v80_12_qoq_A'),
     {**BOOST_BASE, 'G_QOQ_PENALTY': 'A', 'G_QOQ_PENALTY_MULTIPLIER': '0.5'}),
    ('qoq_B', '20190102', '20260515', str(PROJECT / 'state_v80_12_qoq_B'),
     {**BOOST_BASE, 'G_QOQ_PENALTY': 'B', 'G_QOQ_PENALTY_MULTIPLIER': '0.5'}),
]

print('v80.12 QoQ 옵션 7년 ranking 재생성 — A+B 병렬')
print('  A: qoq_op < -10% → G × 0.5')
print('  B: qoq_op < -5% → G × 0.5')
print()

t0 = time.time()
processes = []
for label, s, e, sdir, env in jobs:
    merged = {**os.environ, **env}
    log_path = str(PROJECT / 'logs' / f'v80_12_{label}.log')
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    os.makedirs(sdir, exist_ok=True)
    logf = open(log_path, 'w', encoding='utf-8')
    cmd = [PYTHON, '-u', FG, s, e, f'--state-dir={sdir}', '--resume']
    p = subprocess.Popen(cmd, cwd=str(PROJECT), env=merged,
                         stdout=logf, stderr=subprocess.STDOUT,
                         text=True, encoding='utf-8', errors='replace')
    processes.append((label, p, logf, time.time()))
    print(f'  {label}: PID {p.pid} → {sdir}', flush=True)

# 모니터링
finished = set()
while len(finished) < len(processes):
    for i, (label, p, logf, t_start) in enumerate(processes):
        if i in finished: continue
        if p.poll() is not None:
            finished.add(i)
            logf.close()
            elapsed = time.time() - t_start
            print(f'  ✓ {label} 완료 ({elapsed/60:.1f}분, return {p.returncode})', flush=True)
    time.sleep(60)
    elapsed = time.time() - t0
    print(f'  대기 중 ({elapsed/60:.1f}분 경과, {len(finished)}/{len(processes)} 완료)...', flush=True)

print(f'\n총 소요: {(time.time()-t0)/60:.1f}분')
