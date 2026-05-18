"""v80.12 D6 옵션 ranking 재생성 — qoq_op < +20% → ×0.7
2026-05-18

표본 BT 결과: D6 Cal 0.904 ★★ (Opt2b 0.888 능가)

룰: qoq_op < +20% 면 G_score × 0.7 (약한 패널티)
  → 음수 + 양수 미미 종목까지 잡음
  → 보성파워텍 (QoQ +11%) 같은 base 효과 종목 차단
"""
import os, sys, time, subprocess
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

PYTHON = sys.executable
FG = str(Path(__file__).parent / 'fast_generate_rankings_v2.py')
PROJECT = Path(__file__).parent.parent

BOOST_D6 = {
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
    # D6: 양수 미미까지 잡음
    'G_QOQ_PENALTY': 'D6',  # 새 옵션, 코드 추가 필요
    'G_QOQ_PENALTY_THRESHOLD': '20',  # +20% 미만
    'G_QOQ_PENALTY_MULTIPLIER': '0.7',
    'PYTHONIOENCODING': 'utf-8',
}

sdir = str(PROJECT / 'state_v80_12_qoq_D6')
os.makedirs(sdir, exist_ok=True)
log_path = str(PROJECT / 'logs' / 'v80_12_qoq_D6.log')

merged = {**os.environ, **BOOST_D6}
logf = open(log_path, 'w', encoding='utf-8')
cmd = [PYTHON, '-u', FG, '20190102', '20260515', f'--state-dir={sdir}', '--resume']
print(f'D6 ranking 재생성 시작 → {sdir}', flush=True)
p = subprocess.Popen(cmd, cwd=str(PROJECT), env=merged,
                     stdout=logf, stderr=subprocess.STDOUT,
                     text=True, encoding='utf-8', errors='replace')
print(f'PID: {p.pid}', flush=True)

t0 = time.time()
while p.poll() is None:
    time.sleep(60)
    n_files = len(list(Path(sdir).glob('ranking_*.json')))
    elapsed = time.time() - t0
    print(f'  진행: {n_files} / 1873 ({elapsed/60:.1f}분 경과)', flush=True)

logf.close()
print(f'\n✓ 완료 (총 {(time.time()-t0)/60:.1f}분, return {p.returncode})')
