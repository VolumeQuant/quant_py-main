"""v80 전체 state 재생성 — boost + defense 병렬 subprocess
state/ + state/defense/ + bt_extended/ + bt_extended_defense/

v80 파라미터:
  공격: V15Q0G55M30, 2f rev+oca(0.6/0.4), 12m, E3X6S3
  방어: V30Q15G15M40, 2f rev+oca(0.7/0.3), 6m-1m, E3X6S5
"""
import os, sys, time, subprocess
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

PYTHON = sys.executable
FG = str(Path(__file__).parent / 'fast_generate_rankings_v2.py')
PROJECT = Path(__file__).parent.parent

# v80.6.1 (2026-05-15): boost G 2팩터 → 3팩터 (rev+oca+gp_growth_z 0.4/0.4/0.2)
# 7.4y BT: Cal +0.073, WF CV 0.508→0.440 (-13% 안정성 개선)
# v80.6 (2026-05-13): MA170→MA250 + boost gr 0.6→0.5 + defense V/Q/G/M V30→V35 M40→M35 gr 0.7→0.8
BOOST_ENV = {
    'FACTOR_V_W': '0.15',
    'FACTOR_Q_W': '0.00',
    'FACTOR_G_W': '0.55',
    'FACTOR_M_W': '0.30',
    'G_SUB1': 'rev_z',
    'G_SUB2': 'oca_z',
    'G_SUB3': 'gp_growth_z',  # v80.6.1: 3팩터 도입
    'G_W1': '0.4',
    'G_W2': '0.4',
    'G_W3': '0.2',
    'G_REVENUE_WEIGHT': '0.5',  # 2팩터 폴백용 (3팩터 모드에선 G_W1~3 사용)
    'MOM_PERIOD': '12m',
    'PYTHONIOENCODING': 'utf-8',
}
DEFENSE_ENV = {
    'FACTOR_V_W': '0.35',   # v80.6: 0.30→0.35
    'FACTOR_Q_W': '0.15',
    'FACTOR_G_W': '0.15',
    'FACTOR_M_W': '0.35',   # v80.6: 0.40→0.35
    'G_SUB1': 'rev_z',
    'G_SUB2': 'oca_z',
    'G_REVENUE_WEIGHT': '0.8',  # v80.6: 0.7→0.8 (rev 비중↑)
    'MOM_PERIOD': '6m-1m',
    'PYTHONIOENCODING': 'utf-8',
}

# 사용자 지시 (2026-05-13): state/ 단일 통합 (bt_extended 분리 폐기)
# v80.6.1 (2026-05-15): boost 3팩터 도입 — boost만 재생성, defense는 무변경 (baseline 유지)
jobs = [
    ('boost_state',   '20180702', '20260514', str(PROJECT / 'state'),                             BOOST_ENV),
    # ('def_state',     '20180702', '20260512', str(PROJECT / 'state' / 'defense'),                 DEFENSE_ENV),  # defense 무변경
]

print(f'v80.6.1 전체 재생성 시작 — 2작업 병렬 (state/ 단일 통합)')
print(f'  공격: V15Q0G55M30 3f(rev40+oca40+gp20) 12m')
print(f'  방어: V35Q15G15M35 2f(rev80+oca20) 6m-1m')
print()

# 2병렬: boost + defense (단일 batch)
t0 = time.time()

for batch_name, batch_jobs in [
    ('Batch 1 (boost+defense state 통합)', jobs),
]:
    print(f'\n{batch_name}:', flush=True)
    processes = []
    for label, s, e, sdir, env in batch_jobs:
        merged = {**os.environ, **env}
        log_path = str(PROJECT / 'logs' / f'v80_regen_{label}.log')
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        logf = open(log_path, 'w', encoding='utf-8')
        cmd = [PYTHON, '-u', FG, s, e, f'--state-dir={sdir}', '--resume']
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
print(f'\n=== v80 재생성 완료: {total/60:.1f}분 ({total:.0f}초) ===', flush=True)
