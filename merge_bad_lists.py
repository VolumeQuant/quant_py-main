"""bad_tickers_v2 (32) + FN-mismatch (171) 합쳐 bad_tickers_v3 생성 (DART 호출 0)

분류:
  - tier1_confirmed: SG&A 일치로 확정 BAD (32)
  - tier2_fn_mismatch: FN과 5배+ 차이 (139 추가) — 다른 매핑 버그 가능성
  - tier3_cross_match: 다른 회계항목과 동일값 (cross match) → 매핑 의심

재수집 우선순위:
  1. tier1 (확정) — 무조건 재수집
  2. tier2 (FN 차이) — 재수집 권장
  3. tier3 (cross match) — 표본 확인 후 결정
"""
import sys, json, os
sys.path.insert(0, 'C:/dev')
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd

# tier1: SG&A 일치
with open('C:/dev/bad_tickers_v2.txt') as f:
    tier1 = set(l.strip() for l in f if l.strip())

# Step 3 결과 다시 계산 (offline_diag_summary.json에 fn_mismatch_tickers 있음)
summary = json.load(open('C:/dev/offline_diag_summary.json', encoding='utf-8'))
tier2_all = set(item['ticker'] for item in summary['fn_mismatch_tickers'])
tier2_only = tier2_all - tier1  # FN 차이만 (SG&A 일치 아님)

print(f'tier1 (SG&A 일치 확정 BAD): {len(tier1)}')
print(f'tier2 전체 (FN 5배+ 차이): {len(tier2_all)}')
print(f'tier2 only (tier1 제외): {len(tier2_only)}')

# tier2_only 종목 표본 검사 — 캐시 vs FN 매출 시계열
import glob
print(f'\n=== tier2 only 표본 5종목 캐시 vs FN 매출 시계열 ===')
samples = sorted(tier2_only)[:5]
for tk in samples:
    print(f'\n--- {tk} ---')
    d_df = pd.read_parquet(f'C:/dev/data_cache/fs_dart_{tk}.parquet')
    fn_fp = f'C:/dev/data_cache/fs_fnguide_{tk}.parquet'
    if not os.path.exists(fn_fp):
        print(f'  FN 없음')
        continue
    f_df = pd.read_parquet(fn_fp)
    d_q = d_df[(d_df['공시구분']=='q') & (d_df['계정']=='매출액') & d_df['값'].notna()].sort_values('기준일').tail(8)
    f_q = f_df[(f_df['공시구분']=='q') & (f_df['계정']=='매출액') & f_df['값'].notna()].sort_values('기준일').tail(8)
    print(f'  DART q 매출 (최근 8):')
    for _, r in d_q.iterrows():
        print(f'    {r["기준일"].strftime("%Y-%m")}: {r["값"]:>10.1f}억')
    print(f'  FN q 매출 (최근 8):')
    for _, r in f_q.iterrows():
        print(f'    {r["기준일"].strftime("%Y-%m")}: {r["값"]:>10.1f}억')

# bad_tickers_v3.txt 저장 (tier1 + tier2_only 통합)
all_bad = sorted(tier1 | tier2_only)
with open('C:/dev/bad_tickers_v3.txt', 'w') as f:
    for tk in all_bad:
        f.write(tk + '\n')

# tier 별 저장
with open('C:/dev/bad_tickers_tier1.txt', 'w') as f:
    for tk in sorted(tier1):
        f.write(tk + '\n')
with open('C:/dev/bad_tickers_tier2_only.txt', 'w') as f:
    for tk in sorted(tier2_only):
        f.write(tk + '\n')

print(f'\n저장:')
print(f'  bad_tickers_v3.txt: {len(all_bad)}종목 (tier1+tier2 통합)')
print(f'  bad_tickers_tier1.txt: {len(tier1)}종목 (SG&A 확정)')
print(f'  bad_tickers_tier2_only.txt: {len(tier2_only)}종목 (FN 차이만)')
