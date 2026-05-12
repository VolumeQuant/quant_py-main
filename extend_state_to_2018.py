"""state 2018-07-02 ~ 2020-12-30 추가 생성 + bt_extended에 복사

옵션 B (5/13 사용자 결정): state 통합 + bt_extended는 복사로 정합성 보장.
"""
import os, sys, time, subprocess, shutil
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

PYTHON = sys.executable
PROJECT = Path(__file__).parent
FG = str(PROJECT / 'backtest' / 'fast_generate_rankings_v2.py')

BOOST_ENV = {
    'FACTOR_V_W': '0.15', 'FACTOR_Q_W': '0.00', 'FACTOR_G_W': '0.55', 'FACTOR_M_W': '0.30',
    'G_SUB1': 'rev_z', 'G_SUB2': 'oca_z', 'G_REVENUE_WEIGHT': '0.6', 'MOM_PERIOD': '12m',
    'PYTHONIOENCODING': 'utf-8',
}
DEFENSE_ENV = {
    'FACTOR_V_W': '0.30', 'FACTOR_Q_W': '0.15', 'FACTOR_G_W': '0.15', 'FACTOR_M_W': '0.40',
    'G_SUB1': 'rev_z', 'G_SUB2': 'oca_z', 'G_REVENUE_WEIGHT': '0.7', 'MOM_PERIOD': '6m-1m',
    'PYTHONIOENCODING': 'utf-8',
}

# 1. state 2018-07~2020-12 추가 생성 (2병렬)
jobs = [
    ('boost_2018', '20180702', '20201230', str(PROJECT / 'state'),            BOOST_ENV),
    ('def_2018',   '20180702', '20201230', str(PROJECT / 'state' / 'defense'), DEFENSE_ENV),
]

print('=== 1. state 2018-07~2020-12 추가 생성 (2병렬) ===')
t0 = time.time()
procs = []
for label, s, e, sdir, env in jobs:
    merged = {**os.environ, **env}
    logp = str(PROJECT / 'logs' / f'state_2018_{label}.log')
    logf = open(logp, 'w', encoding='utf-8')
    cmd = [PYTHON, '-u', FG, s, e, f'--state-dir={sdir}']
    p = subprocess.Popen(cmd, env=merged, stdout=logf, stderr=subprocess.STDOUT,
                         text=True, encoding='utf-8', errors='replace')
    procs.append((label, p, logf, time.time()))
    print(f'  {label} PID={p.pid}', flush=True)

for label, p, logf, ts in procs:
    rc = p.wait()
    logf.close()
    print(f'  {label} rc={rc} ({(time.time()-ts)/60:.1f}분)', flush=True)
print(f'state 2018-07~2020-12 완료: {(time.time()-t0)/60:.1f}분')

# 2. bt_extended에 state의 2018-07~2020-12 복사
print('\n=== 2. bt_extended에 복사 ===')
for src_d, dst_d in [
    (PROJECT/'state', PROJECT/'backtest'/'bt_extended'),
    (PROJECT/'state'/'defense', PROJECT/'backtest'/'bt_extended_defense'),
]:
    # bt_extended 기존 ranking 삭제
    deleted = 0
    for fp in dst_d.glob('ranking_*.json'):
        if len(fp.stem.replace('ranking_', '')) == 8:
            fp.unlink()
            deleted += 1
    print(f'  {dst_d.name} 기존 {deleted}개 삭제')
    # state의 2018-07~2020-12 복사
    copied = 0
    for fp in src_d.glob('ranking_2018*.json'):
        shutil.copy2(fp, dst_d / fp.name)
        copied += 1
    for fp in src_d.glob('ranking_2019*.json'):
        shutil.copy2(fp, dst_d / fp.name)
        copied += 1
    for fp in src_d.glob('ranking_2020*.json'):
        shutil.copy2(fp, dst_d / fp.name)
        copied += 1
    print(f'  {dst_d.name}: {copied}개 복사')
print(f'\n총 소요: {(time.time()-t0)/60:.1f}분')
