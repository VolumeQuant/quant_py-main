"""v79 전체 재생성 (FnGuide rcept_dt 역추적 반영 PIT)
- state/: 2021-01-04 ~ 2026-04-15 (boost) — 프로덕션
- state/defense/: 동일
- backtest/bt_extended/: 2018-07-02 ~ 2020-12-30 (boost) — BT
- backtest/bt_extended_defense/: 동일

4워커 병렬. Phase 3 스크립트 재활용 구조.
"""
import os, sys, time, subprocess
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

PYTHON = 'C:/Users/user/miniconda3/envs/volumequant/python.exe'
FG = 'C:/dev/backtest/fast_generate_rankings_v2.py'

# v79 파라미터 (regime_indicator.py와 100% 일치)
BOOST_ENV = {
    'FACTOR_V_W':'0.15','FACTOR_Q_W':'0.05','FACTOR_G_W':'0.50','FACTOR_M_W':'0.30',
    'G_SUB1':'rev_z','G_SUB2':'oca_z','G_SUB3':'gp_growth_z',
    'G_W1':'0.5','G_W2':'0.3','G_W3':'0.2',
    'MOM_PERIOD':'12m',
    'PYTHONIOENCODING':'utf-8',
}
DEFENSE_ENV = {
    'FACTOR_V_W':'0.30','FACTOR_Q_W':'0.15','FACTOR_G_W':'0.15','FACTOR_M_W':'0.40',
    'G_SUB1':'rev_z','G_SUB2':'oca_z',
    'G_REVENUE_WEIGHT':'0.7',
    'MOM_PERIOD':'6m-1m',
    'PYTHONIOENCODING':'utf-8',
}

# 4워커 병렬 작업
jobs = [
    ('boost_prod', '20210104', '20260415', 'state',                            BOOST_ENV),
    ('def_prod',   '20210104', '20260415', 'state/defense',                    DEFENSE_ENV),
    ('boost_ext',  '20180702', '20201230', 'backtest/bt_extended',             BOOST_ENV),
    ('def_ext',    '20180702', '20201230', 'backtest/bt_extended_defense',     DEFENSE_ENV),
]

print(f'v79 전체 재생성 시작 — 4워커 병렬 (FnGuide rcept_dt 반영 PIT)')
print(f'  prod: 1295일 × 2 (boost+defense, 2021-01-04~2026-04-15)')
print(f'  ext:  617일 × 2 (boost+defense, 2018-07-02~2020-12-30)')
print()

processes = []
t0 = time.time()
for label, s, e, sdir, env in jobs:
    merged_env = {**os.environ, **env}
    log_path = f'C:/dev/logs/v79_full_{label}.log'
    logf = open(log_path, 'w', encoding='utf-8')
    cmd = [PYTHON, '-u', FG, s, e, '--state-dir', sdir]  # -u: unbuffered stdout
    p = subprocess.Popen(cmd, cwd='C:/dev', env=merged_env,
                         stdout=logf, stderr=subprocess.STDOUT,
                         text=True, encoding='utf-8', errors='replace')
    processes.append((label, p, logf, time.time()))
    print(f'  [{label}] 시작 PID={p.pid}, log={log_path}', flush=True)

print(f'\n대기 중... (tail -f logs/v79_full_*.log)', flush=True)
results = []
for label, p, logf, ts in processes:
    rc = p.wait()
    logf.close()
    elapsed = time.time() - ts
    results.append((label, rc, elapsed))
    print(f'  [{label}] 완료 rc={rc}, 소요 {elapsed:.1f}초', flush=True)

total = time.time() - t0
print(f'\n=== v79 전체 재생성 완료: {total/60:.1f}분 ({total:.0f}초) ===', flush=True)
for label, rc, elapsed in results:
    status = 'OK' if rc == 0 else 'FAIL'
    print(f'  {label}: {status} ({elapsed/60:.1f}분)')
