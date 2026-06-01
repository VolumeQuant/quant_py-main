# -*- coding: utf-8 -*-
"""v80.22 진짜 BT 재생성 — 옵션 F 미적용 + v80.7 계절성 + v80.12 QoQ + v80.20 신팩터
2026-06-01 자율주행 검증용

룰:
- V0.15 / Q0.00 / G0.55 / M0.30 (boost)
- G 3팩터 (rev_z 0.4 + oca_z 0.4 + gp_growth_z 0.2)
- 12m momentum
- 계절성 curr 식, threshold 1.4, penalty 0.3 (v80.7)
- QoQ D6 (boost + KOSPI > MA220 × 1.06 → qoq < +20% / × 0.7)
- v80.20 신팩터: mom_10_z × 0.05 + vol_low_z × 0.06 (boost)
- 옵션 F 미적용

기간: 2019-01-02 ~ 2026-05-29 (7.4년)
저장: backtest/state_v80_22_truebt/
"""
import os, sys, time, subprocess
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

PYTHON = sys.executable
FG = str(Path(__file__).parent / 'fast_generate_rankings_v2.py')
PROJECT = Path(__file__).parent.parent

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
    # v80.20 신팩터
    'FACTOR_MOM_10_W': '0.05',
    'FACTOR_VOL_LOW_W': '0.06',
    'PYTHONIOENCODING': 'utf-8',
}

sdir = str(PROJECT / 'backtest' / 'state_v80_22_truebt')
Path(sdir).mkdir(parents=True, exist_ok=True)
log_path = str(PROJECT / 'logs' / 'v80_22_truebt.log')
Path(PROJECT / 'logs').mkdir(exist_ok=True)

merged = {**os.environ, **V80_22_BOOST}
logf = open(log_path, 'w', encoding='utf-8')
cmd = [PYTHON, '-u', FG, '20190102', '20260529', f'--state-dir={sdir}', '--resume']
print(f'v80.22 진짜 BT 재생성 시작 → {sdir}', flush=True)
print(f'룰: 옵션F 미적용 + v80.7 계절성 + v80.12 D6 + v80.20 mom_10/vol_low', flush=True)
p = subprocess.Popen(cmd, cwd=str(PROJECT), env=merged,
                     stdout=logf, stderr=subprocess.STDOUT,
                     text=True, encoding='utf-8', errors='replace')
print(f'PID: {p.pid}', flush=True)

t0 = time.time()
while p.poll() is None:
    time.sleep(60)
    elapsed = time.time() - t0
    # 진행률
    n_files = len(list(Path(sdir).glob('ranking_2*.json')))
    print(f'  진행 중 ({elapsed/60:.1f}분 경과, {n_files}/1853 ranking 파일)', flush=True)

logf.close()
print(f'\n✓ 완료 (총 {(time.time()-t0)/60:.1f}분, return {p.returncode})')
