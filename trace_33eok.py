"""백업 fs_dart_042500의 24Q1 매출 33억 정체 추적
   - 어떤 row? account_id, sj_div, fs_div 무엇인가?
   - DART API 직접 호출 24년 전체 보고서에서 33억과 가까운 row 찾기
"""
import sys, os
sys.path.insert(0, 'C:/dev')
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd
from dart_collector import DartCollector
from config import DART_API_KEYS

print('=== Step 1: 백업 fs_dart_042500 24Q1 매출 row 전수 검토 ===')
b = pd.read_parquet('C:/dev/data_cache_backup_20260512/fs_dart_042500.parquet')
print('컬럼:', list(b.columns))

# 24-03-31 기준일 + 매출 관련
m24 = b[b['기준일']==pd.Timestamp('2024-03-31')]
print(f'\n24Q1 row 총 {len(m24)}개 (전체 계정)')
rev = m24[m24['계정'].str.contains('매출|수익|영업수', na=False)]
print(f'매출/수익/영업수 row {len(rev)}개:')
for _, r in rev.iterrows():
    print(f'  계정={r["계정"]:<20} 값={r["값"]:.3e}  공시구분={r["공시구분"]}  fs_div={r.get("fs_div","-")}')

# 시점별 33억 패턴 추적 (다른 분기에서도 33억 패턴 있나)
print(f'\n=== Step 2: 백업 042500 매출액 시계열 ===')
all_rev = b[(b['공시구분']=='q') & (b['계정']=='매출액') & b['값'].notna()].sort_values('기준일')
for _, r in all_rev.iterrows():
    val_eok = r['값'] / 1e8
    print(f'  {r["기준일"].strftime("%Y-%m")} {val_eok:>10.1f}억  (fs_div={r.get("fs_div","-")})')

# DART API 직접 호출 — 24년 1Q 전체 보고서 dump
print(f'\n=== Step 3: DART API 24년 1Q 보고서 — 33억과 가까운 row 찾기 ===')
dc = DartCollector(api_key=DART_API_KEYS[0])
for fs_div in ['CFS', 'OFS']:
    print(f'\n--- {fs_div} ---')
    rep = dc.dart.finstate_all('042500', 2024, reprt_code='11013', fs_div=fs_div)
    if rep is None or rep.empty:
        print('  데이터 없음')
        continue
    # 33억 = 3.3e9 와 가까운 값 (1억 ~ 100억) 모두
    rep_num = rep.copy()
    rep_num['amt'] = pd.to_numeric(rep['thstrm_amount'].astype(str).str.replace(',',''), errors='coerce')
    near = rep_num[(rep_num['amt'].abs() >= 1e9) & (rep_num['amt'].abs() <= 1e10)]
    for _, r in near.head(20).iterrows():
        sj = r.get('sj_div', '-')
        nm = r.get('account_nm', '-')
        aid = r.get('account_id', '-')
        amt = r['amt']
        print(f'  [{sj}] {nm:<25} amt={amt:.3e}  id={aid}')
