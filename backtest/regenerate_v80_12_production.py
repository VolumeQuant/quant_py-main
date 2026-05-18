"""v80.12 Production state/ 재생성 — D6_SG6 룰
2026-05-18

룰:
- boost mode + KOSPI > MA220 × 1.06 → ranking_D6 (qoq<+20/0.7x)
- 그 외 → baseline 자동 (코드 내부 SG6 체크)

기간: 2019-01-02 ~ 2026-05-15 (7.4년)
"""
import os, sys, time, subprocess
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

PYTHON = sys.executable
FG = str(Path(__file__).parent / 'fast_generate_rankings_v2.py')
PROJECT = Path(__file__).parent.parent

BOOST_V80_12 = {
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
    # v80.12 (★ NEW)
    'G_QOQ_PENALTY': 'D6',
    'G_QOQ_PENALTY_THRESHOLD': '20',
    'G_QOQ_PENALTY_MULTIPLIER': '0.7',
    'G_QOQ_SG6_THRESH': '0.06',
    'PYTHONIOENCODING': 'utf-8',
}

sdir = str(PROJECT / 'state')
log_path = str(PROJECT / 'logs' / 'v80_12_production.log')

merged = {**os.environ, **BOOST_V80_12}
logf = open(log_path, 'w', encoding='utf-8')
cmd = [PYTHON, '-u', FG, '20190102', '20260515', f'--state-dir={sdir}']  # --resume 없음 (덮어쓰기)
print(f'v80.12 production state/ 재생성 시작 → {sdir}', flush=True)
print(f'룰: D6 (qoq<+20/0.7x) + SG6 (MA220 × 1.06)', flush=True)
p = subprocess.Popen(cmd, cwd=str(PROJECT), env=merged,
                     stdout=logf, stderr=subprocess.STDOUT,
                     text=True, encoding='utf-8', errors='replace')
print(f'PID: {p.pid}', flush=True)

t0 = time.time()
while p.poll() is None:
    time.sleep(60)
    elapsed = time.time() - t0
    print(f'  진행 중 ({elapsed/60:.1f}분 경과)', flush=True)

logf.close()
print(f'\n✓ 완료 (총 {(time.time()-t0)/60:.1f}분, return {p.returncode})')
