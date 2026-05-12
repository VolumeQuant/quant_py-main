"""다른 회계항목 (영업이익/자산/자본/CF) DART vs FN 5배+ 차이 검출 (DART 호출 0)"""
import sys, os, json, glob
sys.path.insert(0, 'C:/dev')
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd
from collections import Counter

CHECK_ACCTS = {
    '영업이익': {'tol': 5.0, 'sign_check': True},   # 부호 체크
    '순이익': {'tol': 5.0, 'sign_check': True},
    '자산': {'tol': 5.0, 'sign_check': False},     # 양수만
    '자본': {'tol': 5.0, 'sign_check': False},
}

results = {acct: [] for acct in CHECK_ACCTS}
all_files = sorted(glob.glob('C:/dev/data_cache/fs_dart_*.parquet'))

for fp in all_files:
    tk = os.path.basename(fp).replace('fs_dart_','').replace('.parquet','')
    fn_fp = f'C:/dev/data_cache/fs_fnguide_{tk}.parquet'
    if not os.path.exists(fn_fp): continue
    try:
        d_df = pd.read_parquet(fp)
        f_df = pd.read_parquet(fn_fp)
        for acct, cfg in CHECK_ACCTS.items():
            d_q = d_df[(d_df['공시구분']=='q') & (d_df['계정']==acct) & d_df['값'].notna() & (d_df['값']!=0)]
            f_q = f_df[(f_df['공시구분']=='q') & (f_df['계정']==acct) & f_df['값'].notna() & (f_df['값']!=0)]
            if d_q.empty or f_q.empty: continue
            m = d_q.merge(f_q, on='기준일', suffixes=('_d', '_f'))
            m = m[(m['값_d'] != 0) & (m['값_f'] != 0)]
            if m.empty: continue

            if cfg['sign_check']:
                # 부호 다르거나 절대값 5배+
                m['ratio'] = m['값_d'] / m['값_f']
                bad = (m['값_d'] > 0) != (m['값_f'] > 0)
                bad |= (m['ratio'].abs() > cfg['tol']) | (m['ratio'].abs() < 1.0/cfg['tol'])
            else:
                m['ratio'] = m['값_d'] / m['값_f']
                bad = (m['ratio'] > cfg['tol']) | (m['ratio'] < 1.0/cfg['tol'])

            big = m[bad]
            if not big.empty:
                results[acct].append((tk, len(big)))
    except Exception:
        pass

print('=== 다른 회계항목 DART vs FN 5배+ 차이 검출 ===')
for acct, items in results.items():
    print(f'\n[{acct}] {len(items)}종목 차이 발견')
    items.sort(key=lambda x: -x[1])
    for tk, n in items[:10]:
        print(f'  {tk}: {n}분기 차이')

# 매출 BAD에 포함 안 되는 다른 항목 BAD만 추출
with open('C:/dev/bad_tickers_v3.txt') as f:
    rev_bad = set(l.strip() for l in f if l.strip())

extra_bad = set()
for acct, items in results.items():
    for tk, n in items:
        if n >= 3 and tk not in rev_bad:  # 3분기 이상 차이 + 매출엔 안 잡힌 종목
            extra_bad.add(tk)

print(f'\n매출 BAD 외 추가 의심 (다른 항목 3분기+ 차이): {len(extra_bad)}종목')
print(f'예시: {sorted(extra_bad)[:20]}')

with open('C:/dev/bad_tickers_other_accts.txt', 'w') as f:
    for tk in sorted(extra_bad):
        f.write(tk + '\n')

print(f'\n저장: bad_tickers_other_accts.txt')
