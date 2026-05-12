"""test_account_map.py 음의 검증 — 의도적 잘못 매핑 추가 시 fail 확인"""
import sys
sys.path.insert(0, 'C:/dev')
sys.stdout.reconfigure(encoding='utf-8')

# 임시로 ACCOUNT_ID_MAP 변조 (메모리 내에서만)
from dart_collector import ACCOUNT_ID_MAP

# 백업
ORIGINAL = dict(ACCOUNT_ID_MAP)

print('=' * 50)
print('test_account_map.py 음의 검증')
print('=' * 50)

# 시나리오 1: 비용 → 수익 매핑 (2026-05-04 SG&A 사고 재현)
print('\n[시나리오 1] dart_TotalSellingGeneralAdministrativeExpenses → 매출액 추가')
ACCOUNT_ID_MAP['dart_TotalSellingGeneralAdministrativeExpenses'] = '매출액'

from test_account_map import test_no_expense_to_revenue, test_blacklist
fail1, fail2 = False, False
try:
    test_no_expense_to_revenue()
    print('  ✗ test_no_expense_to_revenue: 검출 못 함 (BUG)')
except AssertionError:
    print('  ✓ test_no_expense_to_revenue: 정상 검출')
    fail1 = True
try:
    test_blacklist()
    print('  ✗ test_blacklist: 검출 못 함 (BUG)')
except AssertionError:
    print('  ✓ test_blacklist: 정상 검출')
    fail2 = True

# 원복
ACCOUNT_ID_MAP.clear()
ACCOUNT_ID_MAP.update(ORIGINAL)

# 시나리오 2: 부채 → 자산 매핑 (블랙리스트)
print('\n[시나리오 2] ifrs-full_CurrentTaxLiabilities → 자산 추가')
ACCOUNT_ID_MAP['ifrs-full_CurrentTaxLiabilities'] = '자산'
fail3 = False
try:
    test_blacklist()
    print('  ✗ test_blacklist: 검출 못 함 (BUG)')
except AssertionError:
    print('  ✓ test_blacklist: 정상 검출')
    fail3 = True

# 원복
ACCOUNT_ID_MAP.clear()
ACCOUNT_ID_MAP.update(ORIGINAL)

# 시나리오 3: 필수 매핑 제거
print('\n[시나리오 3] ifrs-full_Revenue 제거')
if 'ifrs-full_Revenue' in ACCOUNT_ID_MAP:
    del ACCOUNT_ID_MAP['ifrs-full_Revenue']
from test_account_map import test_required_mappings
fail4 = False
try:
    test_required_mappings()
    print('  ✗ test_required_mappings: 검출 못 함 (BUG)')
except AssertionError:
    print('  ✓ test_required_mappings: 정상 검출')
    fail4 = True

# 원복
ACCOUNT_ID_MAP.clear()
ACCOUNT_ID_MAP.update(ORIGINAL)

# 시나리오 4: legacy prefix 불일치
print('\n[시나리오 4] ifrs_Revenue → 영업이익 (legacy 불일치)')
ACCOUNT_ID_MAP['ifrs_Revenue'] = '영업이익'
from test_account_map import test_legacy_prefix_consistency
fail5 = False
try:
    test_legacy_prefix_consistency()
    print('  ✗ test_legacy_prefix_consistency: 검출 못 함 (BUG)')
except AssertionError:
    print('  ✓ test_legacy_prefix_consistency: 정상 검출')
    fail5 = True

# 원복
ACCOUNT_ID_MAP.clear()
ACCOUNT_ID_MAP.update(ORIGINAL)

print('\n' + '=' * 50)
total = sum([fail1, fail2, fail3, fail4, fail5])
print(f'음의 검증 통과: {total}/5')
if total == 5:
    print('✅ unit test가 모든 시나리오 정확 검출')
else:
    print(f'❌ {5-total}건의 시나리오 검출 실패 — unit test 보강 필요')
sys.exit(0 if total == 5 else 1)
