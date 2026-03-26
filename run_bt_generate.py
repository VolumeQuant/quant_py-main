"""bt_2021~2025 랭킹 재생성 — 5개 전부 병렬, 각각 별도 캐시 폴더

API 호출 없음. 캐시 파일만 읽어서 계산.
파일 I/O 경합 방지: 각 프로세스가 자기 전용 캐시 복사본 사용.
"""
import subprocess
import sys
import os
import json
import glob
import time

PYTHON = r'C:\Users\user\miniconda3\envs\volumequant\python.exe'
SCRIPT = r'C:\dev\backtest\fast_generate_rankings.py'
os.chdir(r'C:\dev')
sys.stdout.reconfigure(encoding='utf-8')

JOBS = [
    ('20210104', '20211230', r'C:\dev\state\bt_2021', r'C:\dev\data_cache_1'),
    ('20220103', '20221229', r'C:\dev\state\bt_2022', r'C:\dev\data_cache_2'),
    ('20230102', '20231228', r'C:\dev\state\bt_2023', r'C:\dev\data_cache_3'),
    ('20240102', '20241230', r'C:\dev\state\bt_2024', r'C:\dev\data_cache_4'),
    ('20250102', '20260320', r'C:\dev\state\bt_2025', r'C:\dev\data_cache_5'),
]

print('=== 5개 연도 병렬 시작 (각각 별도 캐시) ===', flush=True)
procs = []
for start, end, state_dir, cache_dir in JOBS:
    os.makedirs(state_dir, exist_ok=True)
    cmd = [PYTHON, '-u', SCRIPT, start, end, '--state-dir', state_dir, '--cache-dir', cache_dir]
    p = subprocess.Popen(cmd, cwd=r'C:\dev')
    name = os.path.basename(state_dir)
    print(f'  {name}: PID={p.pid}, cache={os.path.basename(cache_dir)}', flush=True)
    procs.append((p, state_dir))

# 진행률 모니터링
t0 = time.time()
while any(p.poll() is None for p, _ in procs):
    time.sleep(30)
    elapsed = time.time() - t0
    status = []
    for p, sd in procs:
        name = os.path.basename(sd)
        cnt = len(glob.glob(os.path.join(sd, 'ranking_*.json')))
        done = '완료' if p.poll() is not None else f'{cnt}개'
        status.append(f'{name}:{done}')
    print(f'  [{elapsed/60:.0f}분] {" | ".join(status)}', flush=True)

# 결과 수집
print('\n=== 결과 ===', flush=True)
for p, sd in procs:
    p.wait()
    name = os.path.basename(sd)
    cnt = len(glob.glob(os.path.join(sd, 'ranking_*.json')))
    print(f'  {name}: {cnt}개, exit={p.returncode}', flush=True)

# 검증
print('\n=== 검증 ===', flush=True)
for bt_dir in ['state/bt_2021', 'state/bt_2022', 'state/bt_2023', 'state/bt_2024', 'state/bt_2025']:
    files = sorted(glob.glob(os.path.join(bt_dir, 'ranking_*.json')))
    bad = no_price = no_revz = 0
    for f in files:
        with open(f, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        r = data.get('rankings', [])
        if not r:
            bad += 1
            continue
        s = r[0]
        if 'price' not in s or s['price'] is None:
            no_price += 1
        if 'rev_z' not in s or s['rev_z'] is None:
            no_revz += 1
    print(f'  {bt_dir}: {len(files)}파일, 빈랭킹={bad}, price누락={no_price}, rev_z누락={no_revz}', flush=True)

# 캐시 복사본 정리
print('\n캐시 복사본 정리...', flush=True)
import shutil
for i in range(1, 6):
    d = f'C:\\dev\\data_cache_{i}'
    if os.path.exists(d):
        shutil.rmtree(d)
print('정리 완료', flush=True)

elapsed = time.time() - t0
print(f'\n=== 전체 완료: {elapsed/60:.1f}분 ===', flush=True)
