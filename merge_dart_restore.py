"""3 손실 종목 fs_dart 복원 — 옛 commit row만 추가 (현재 row 보존)"""
import sys, subprocess, io, shutil
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd

OLD_COMMIT = 'd4247a01b'
LOST_TICKERS = ['000660', '196170', '088130']

print('=== 3 종목 fs_dart 옛 데이터 복원 ===')
for tk in LOST_TICKERS:
    cur_fp = f'C:/dev/data_cache/fs_dart_{tk}.parquet'
    rel = f'data_cache/fs_dart_{tk}.parquet'
    r = subprocess.run(['git','show',f'{OLD_COMMIT}:{rel}'], capture_output=True, cwd='C:/dev')
    if r.returncode != 0:
        print(f'  {tk}: 옛 commit 데이터 없음 — skip')
        continue
    old = pd.read_parquet(io.BytesIO(r.stdout))
    cur = pd.read_parquet(cur_fp)

    # 키: (계정, 기준일, 공시구분)
    cur_keys = set(zip(cur['계정'], cur['기준일'], cur['공시구분']))
    old_extra = old[~old.apply(lambda r: (r['계정'], r['기준일'], r['공시구분']) in cur_keys, axis=1)]

    # 백업
    shutil.copy2(cur_fp, cur_fp + '.bak_pre_restore')

    # merge — old 추가 row만
    if 'fs_div' in cur.columns and 'fs_div' not in old.columns:
        old['fs_div'] = None
    common_cols = list(cur.columns)
    old_extra = old_extra.reindex(columns=common_cols)
    merged = pd.concat([cur, old_extra], ignore_index=True)
    merged = merged.drop_duplicates(subset=['계정','기준일','공시구분'], keep='first')

    merged.to_parquet(cur_fp, index=False)
    print(f'  {tk}: {len(cur)} → {len(merged)} (+{len(old_extra)} 복원)')

# 검증
print('\n=== 검증 ===')
for tk in LOST_TICKERS:
    fp = f'C:/dev/data_cache/fs_dart_{tk}.parquet'
    d = pd.read_parquet(fp)
    n_2016 = d[(d['공시구분']=='q') & (d['기준일'].dt.year==2016)]['기준일'].nunique()
    n_2017 = d[(d['공시구분']=='q') & (d['기준일'].dt.year==2017)]['기준일'].nunique()
    print(f'  {tk}: total {len(d)}, 2016 q={n_2016}, 2017 q={n_2017}')
