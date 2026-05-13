"""4/18 baseline commit에서 손실된 fs_dart 데이터 복원

전략:
1. 4/18 commit (d4247a01b) vs 현재 비교 — 종목별 row 수 차이
2. 손실 종목 식별
3. 옛 commit에서 손실된 row만 추출 → 현재 fs_dart에 merge
4. SG&A 매핑 사고 영향 받는 row는 제외 (2024년 q 데이터 등은 215 정정 결과 유지)
"""
import sys, os, glob, subprocess, io
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd

OLD_COMMIT = 'd4247a01b'  # 4/18 v80 baseline 시점

# 1. 손실 종목 식별
print('=== 종목별 row 수 비교 (4/18 vs 현재) ===')
all_files = sorted(glob.glob('C:/dev/data_cache/fs_dart_*.parquet'))
lost = []  # (ticker, old_total, new_total, lost_count)
for fp in all_files:
    tk = os.path.basename(fp).replace('fs_dart_','').replace('.parquet','')
    try:
        cur = pd.read_parquet(fp)
        n_new = len(cur)
    except: continue
    rel = f'data_cache/fs_dart_{tk}.parquet'
    r = subprocess.run(['git','show',f'{OLD_COMMIT}:{rel}'], capture_output=True, cwd='C:/dev')
    if r.returncode != 0: continue
    try:
        old = pd.read_parquet(io.BytesIO(r.stdout))
        n_old = len(old)
    except: continue
    if n_old > n_new + 5:  # 10 row 이상 손실
        lost.append((tk, n_old, n_new, n_old - n_new))

lost.sort(key=lambda x: -x[3])
print(f'손실 종목 (10 row 이상): {len(lost)}')
for tk, no, nn, l in lost[:20]:
    print(f'  {tk}: 옛 {no} → 새 {nn} (손실 {l})')

# 저장
with open('C:/dev/_lost_dart_tickers.txt', 'w') as f:
    for tk, _, _, _ in lost:
        f.write(tk + '\n')
print(f'\n저장: _lost_dart_tickers.txt ({len(lost)}종목)')
