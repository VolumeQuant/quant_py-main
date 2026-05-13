"""백업 fs_dart_042500 매출액 시계열 + 다른 표본 (024840/046940/072950) 동일 패턴 확인"""
import sys, os
sys.path.insert(0, 'C:/dev')
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd
from dart_collector import DartCollector
from config import DART_API_KEYS

dc = DartCollector(api_key=DART_API_KEYS[0])

samples_bad = ['042500','024840','046940','072950']
samples_good = ['000660','088130','196170','207940']

print('=== 백업 fs_dart 매출액 시계열 (각 표본 모두) ===')
for tk in samples_bad + samples_good:
    bp = f'C:/dev/data_cache_backup_20260512/fs_dart_{tk}.parquet'
    if not os.path.exists(bp): continue
    b = pd.read_parquet(bp)
    rev = b[(b['공시구분']=='q') & (b['계정']=='매출액') & b['값'].notna()].sort_values('기준일')
    print(f'\n--- {tk} ---')
    for _, r in rev.iterrows():
        print(f'  {r["기준일"].strftime("%Y-%m")}: {r["값"]:>12.2f} (억원)')

print('\n=== 4종목 잘못 가설 검증: DART API SG&A == 캐시 매출액 ? ===')
for tk in samples_bad:
    bp = f'C:/dev/data_cache_backup_20260512/fs_dart_{tk}.parquet'
    b = pd.read_parquet(bp)
    rev24 = b[(b['공시구분']=='q') & (b['계정']=='매출액') & (b['기준일']==pd.Timestamp('2024-03-31'))]
    if rev24.empty:
        print(f'  {tk}: 24Q1 매출 row 없음')
        continue
    cache_rev = float(rev24['값'].iloc[0])  # 억원

    # DART API에서 24Q1 SG&A 가져오기
    rep = dc.dart.finstate_all(tk, 2024, reprt_code='11013', fs_div='CFS')
    if rep is None or rep.empty:
        rep = dc.dart.finstate_all(tk, 2024, reprt_code='11013', fs_div='OFS')
    if rep is None or rep.empty:
        print(f'  {tk}: DART 데이터 없음')
        continue

    sga = rep[rep['account_id']=='dart_TotalSellingGeneralAdministrativeExpenses']
    if sga.empty:
        print(f'  {tk}: SG&A row 없음. 캐시={cache_rev}억')
    else:
        sga_amt = pd.to_numeric(sga['thstrm_amount'].astype(str).str.replace(',',''), errors='coerce').iloc[0]
        sga_eok = sga_amt / 1e8
        match = abs(cache_rev - sga_eok) < 0.5
        print(f'  {tk}: 캐시매출={cache_rev:.1f}억  vs  DART SG&A={sga_eok:.1f}억  {"✓ 일치" if match else "✗ 불일치"}')
