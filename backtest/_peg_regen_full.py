"""pen_cs BT용 전체 재생성 (1회) — v80.22 env + STORE_OVERHEAT_PEN=1, OVERHEAT_W=0.
score=v80.22 baseline(mom_10/vol_low 포함), composite_rank=baseline, overheat_pen=저장(미반영).
이후 시뮬레이터가 cr(W)=rank(score+W*pen)로 전 W 그리드 재사용."""
import os, sys, time, subprocess
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

PYTHON = sys.executable
FG = str(Path(__file__).parent / 'fast_generate_rankings_v2.py')
PROJECT = Path(__file__).parent.parent

ENV = {
    'FACTOR_V_W': '0.15', 'FACTOR_Q_W': '0.00', 'FACTOR_G_W': '0.55', 'FACTOR_M_W': '0.30',
    'G_SUB1': 'rev_z', 'G_SUB2': 'oca_z', 'G_SUB3': 'gp_growth_z',
    'G_W1': '0.4', 'G_W2': '0.4', 'G_W3': '0.2', 'G_REVENUE_WEIGHT': '0.5',
    'MOM_PERIOD': '12m', 'SEASONALITY_FORMULA': 'curr', 'SEASONALITY_RATIO_THRESH': '1.4',
    'SEASONALITY_PENALTY': '0.3', 'SEASONALITY_EXEMPT_MM_THRESH': '0.2',
    'G_QOQ_PENALTY': 'D6', 'G_QOQ_PENALTY_THRESHOLD': '20', 'G_QOQ_PENALTY_MULTIPLIER': '0.7',
    'G_QOQ_SG6_THRESH': '0.06', 'FACTOR_MOM_10_W': '0.05', 'FACTOR_VOL_LOW_W': '0.06',
    'STORE_OVERHEAT_PEN': '1', 'FACTOR_OVERHEAT_W': '0.0',
    'PYTHONIOENCODING': 'utf-8',
}
sdir = str(PROJECT / 'backtest' / 'state_peg_bt')
Path(sdir).mkdir(parents=True, exist_ok=True)
log_path = str(PROJECT / 'logs' / 'peg_regen.log')
Path(PROJECT / 'logs').mkdir(exist_ok=True)
merged = {**os.environ, **ENV}
logf = open(log_path, 'w', encoding='utf-8')
cmd = [PYTHON, '-u', FG, '20190102', '20260529', f'--state-dir={sdir}', '--resume']
print(f'pen_cs BT 재생성 시작 → {sdir}', flush=True)
p = subprocess.Popen(cmd, cwd=str(PROJECT), env=merged, stdout=logf, stderr=subprocess.STDOUT,
                     text=True, encoding='utf-8', errors='replace')
print(f'PID: {p.pid}', flush=True)
t0 = time.time()
while p.poll() is None:
    time.sleep(60)
    n = len(list(Path(sdir).glob('ranking_2*.json')))
    print(f'  진행 ({(time.time()-t0)/60:.1f}분, {n}/1853 파일)', flush=True)
logf.close()
print(f'\n완료 ({(time.time()-t0)/60:.1f}분, rc={p.returncode})')
