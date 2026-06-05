"""pen_cs 구현 검증: 소규모 재생성(W=0.1) + overheat_pen 정확성 확인."""
import os, sys, time, subprocess
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

PYTHON = sys.executable
FG = str(Path(__file__).parent / 'fast_generate_rankings_v2.py')
PROJECT = Path(__file__).parent.parent

V80_22 = {
    'FACTOR_V_W': '0.15', 'FACTOR_Q_W': '0.00', 'FACTOR_G_W': '0.55', 'FACTOR_M_W': '0.30',
    'G_SUB1': 'rev_z', 'G_SUB2': 'oca_z', 'G_SUB3': 'gp_growth_z',
    'G_W1': '0.4', 'G_W2': '0.4', 'G_W3': '0.2', 'G_REVENUE_WEIGHT': '0.5',
    'MOM_PERIOD': '12m', 'SEASONALITY_FORMULA': 'curr', 'SEASONALITY_RATIO_THRESH': '1.4',
    'SEASONALITY_PENALTY': '0.3', 'SEASONALITY_EXEMPT_MM_THRESH': '0.2',
    'G_QOQ_PENALTY': 'D6', 'G_QOQ_PENALTY_THRESHOLD': '20', 'G_QOQ_PENALTY_MULTIPLIER': '0.7',
    'G_QOQ_SG6_THRESH': '0.06', 'FACTOR_MOM_10_W': '0.05', 'FACTOR_VOL_LOW_W': '0.06',
    'PYTHONIOENCODING': 'utf-8',
}

START, END = '20240502', '20240531'
runs = {'base': {'FACTOR_OVERHEAT_W': '0.0'}, 'w01': {'FACTOR_OVERHEAT_W': '0.1'}}
for label, extra in runs.items():
    sdir = str(PROJECT / 'backtest' / f'_peg_val_{label}')
    Path(sdir).mkdir(parents=True, exist_ok=True)
    env = {**os.environ, **V80_22, **extra}
    cmd = [PYTHON, '-u', FG, START, END, f'--state-dir={sdir}']
    print(f'\n=== regen {label} (OVERHEAT_W={extra["FACTOR_OVERHEAT_W"]}) → {sdir} ===', flush=True)
    t0 = time.time()
    p = subprocess.run(cmd, cwd=str(PROJECT), env=env, capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    print(f'  종료 {time.time()-t0:.0f}s, rc={p.returncode}')
    tail = '\n'.join(p.stdout.splitlines()[-6:])
    print('  stdout tail:', tail)
    if p.returncode != 0:
        print('  STDERR tail:', '\n'.join(p.stderr.splitlines()[-10:]))
print('\n완료')
