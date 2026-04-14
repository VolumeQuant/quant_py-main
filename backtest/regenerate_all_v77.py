"""전체 1290일 FG 재생성 — boost + defense 병렬 subprocess"""
import os
import sys
import time
import subprocess
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

PROJECT = Path(__file__).parent.parent
FG_SCRIPT = PROJECT / 'backtest' / 'fast_generate_rankings_v2.py'
PYTHON = sys.executable

# v77 params (regime_indicator.py에서 확인)
BOOST_ENV = {
    'FACTOR_V_W': '0.05',
    'FACTOR_Q_W': '0.00',
    'FACTOR_G_W': '0.65',
    'FACTOR_M_W': '0.30',
    'G_REVENUE_WEIGHT': '0.0',
    'MOM_PERIOD': '12m-1m',
    'G_SUB1': 'rev_z',
    'G_SUB2': 'oca_z',
    'G_SUB3': 'gp_growth_z',
    'G_W1': '0.5',
    'G_W2': '0.3',
    'G_W3': '0.2',
}
DEFENSE_ENV = {
    'FACTOR_V_W': '0.30',
    'FACTOR_Q_W': '0.05',
    'FACTOR_G_W': '0.10',
    'FACTOR_M_W': '0.55',
    'G_REVENUE_WEIGHT': '0.5',
    'MOM_PERIOD': '6m-1m',
    'G_SUB1': 'rev_accel_z',
    'G_SUB2': 'op_margin_z',
}

START_DATE = '20210104'
END_DATE = '20260409'

base_env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
boost_env = {**base_env, **BOOST_ENV}
defense_env = {**base_env, **DEFENSE_ENV}

boost_cmd = [PYTHON, '-u', str(FG_SCRIPT), START_DATE, END_DATE, '--state-dir=state']
def_cmd = [PYTHON, '-u', str(FG_SCRIPT), START_DATE, END_DATE, '--state-dir=state/defense']

# 로그 파일
log_boost = PROJECT / 'logs' / 'fg_regen_boost.log'
log_def = PROJECT / 'logs' / 'fg_regen_defense.log'
log_boost.parent.mkdir(exist_ok=True)

print(f'=== FG 재생성 병렬 시작 ({START_DATE} ~ {END_DATE}) ===')
print(f'예상 시간: 25-30분')
t0 = time.time()

with open(log_boost, 'w', encoding='utf-8') as fb, open(log_def, 'w', encoding='utf-8') as fd:
    proc_boost = subprocess.Popen(
        boost_cmd, cwd=str(PROJECT), stdout=fb, stderr=subprocess.STDOUT,
        env=boost_env, text=True, encoding='utf-8', errors='replace'
    )
    proc_def = subprocess.Popen(
        def_cmd, cwd=str(PROJECT), stdout=fd, stderr=subprocess.STDOUT,
        env=defense_env, text=True, encoding='utf-8', errors='replace'
    )

    print(f'boost PID: {proc_boost.pid}, defense PID: {proc_def.pid}')
    print('진행 상황은 logs/fg_regen_boost.log, logs/fg_regen_defense.log 참조')

    # 병렬 대기
    ret_boost = proc_boost.wait()
    ret_def = proc_def.wait()

elapsed = time.time() - t0
print(f'\n=== 완료 ===')
print(f'boost 종료코드: {ret_boost}')
print(f'defense 종료코드: {ret_def}')
print(f'총 소요: {elapsed/60:.1f}분')
