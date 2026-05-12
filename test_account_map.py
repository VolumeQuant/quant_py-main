"""dart_collector ACCOUNT_ID_MAP 무결성 unit test

목적:
- 2026-05-04 SG&A→매출 매핑 사고 재발 방지
- 코드 commit 전 자동 실행 (pre-commit hook 통합)
- 사람이 또 잘못된 매핑 추가 시 즉시 fail

검사:
1. 비용계정(Expenses)이 수익계정(Revenue/Profit/Asset/Equity)으로 매핑되지 않는지
2. 음수가 자연스러운 계정(LiabilitiesIncomeTax)이 양수계정으로 매핑 안 되는지
3. 알려진 위험 매핑 (history 기반) 블랙리스트
"""
import sys, os
sys.path.insert(0, 'C:/dev')


def test_no_expense_to_revenue():
    """비용 계정이 매출/이익 계정으로 매핑되지 않아야 함"""
    from dart_collector import ACCOUNT_ID_MAP

    # account_id에 'Expense' 또는 'Cost' 포함되면 비용 계정
    # 시스템 계정명에 '매출액', '매출총이익', '영업이익', '당기순이익', '자산', '자본' 매핑되면 fail
    REVENUE_LIKE = {'매출액', '매출총이익', '영업이익', '당기순이익', '세전계속사업이익',
                    '자산', '자본', '유동자산', '비유동자산', '지배주주당기순이익', '지배주주자본'}

    violations = []
    for aid, sys_name in ACCOUNT_ID_MAP.items():
        aid_lower = aid.lower()
        is_expense_like = any(k in aid_lower for k in ['expense', 'cost', 'liabilit'])
        if is_expense_like and sys_name in REVENUE_LIKE:
            violations.append((aid, sys_name))

    if violations:
        for aid, sys_name in violations:
            print(f'  ✗ {aid} → {sys_name} (비용→수익 매핑 금지)')
        raise AssertionError(f'{len(violations)}건의 비용→수익 매핑 위반')
    print(f'  ✓ 비용→수익 매핑 없음')


def test_blacklist():
    """알려진 위험 매핑 블랙리스트 — 2026-05-04 SG&A 사고 등"""
    from dart_collector import ACCOUNT_ID_MAP

    BLACKLIST = {
        'dart_TotalSellingGeneralAdministrativeExpenses': '매출액',  # 2026-05-04 사고
        'dart_TotalSellingGeneralAdministrativeExpenses': '매출총이익',
        'ifrs-full_CostOfSales': '매출액',  # 매출원가
        'ifrs-full_CurrentTaxLiabilities': '자산',  # 부채를 자산으로
    }

    violations = []
    for aid, banned_sys in BLACKLIST.items():
        actual = ACCOUNT_ID_MAP.get(aid)
        if actual == banned_sys:
            violations.append((aid, banned_sys))

    if violations:
        for aid, sn in violations:
            print(f'  ✗ {aid} → {sn} (블랙리스트 위반)')
        raise AssertionError(f'{len(violations)}건의 블랙리스트 매핑 위반')
    print(f'  ✓ 블랙리스트 매핑 없음')


def test_required_mappings():
    """필수 매핑이 빠지지 않았는지"""
    from dart_collector import ACCOUNT_ID_MAP

    REQUIRED = {
        'ifrs-full_Revenue': '매출액',
        'ifrs-full_GrossProfit': '매출총이익',
        'dart_OperatingIncomeLoss': '영업이익',
        'ifrs-full_ProfitLoss': '당기순이익',
        'ifrs-full_CashFlowsFromUsedInOperatingActivities': '영업활동으로인한현금흐름',
        'ifrs-full_Assets': '자산',
        'ifrs-full_Equity': '자본',
    }

    missing = []
    wrong = []
    for aid, expected in REQUIRED.items():
        actual = ACCOUNT_ID_MAP.get(aid)
        if actual is None:
            missing.append(aid)
        elif actual != expected:
            wrong.append((aid, expected, actual))

    if missing:
        for aid in missing:
            print(f'  ✗ {aid} 매핑 누락')
        raise AssertionError(f'{len(missing)}건 필수 매핑 누락')
    if wrong:
        for aid, exp, act in wrong:
            print(f'  ✗ {aid}: 기대 {exp}, 실제 {act}')
        raise AssertionError(f'{len(wrong)}건 필수 매핑 잘못')

    print(f'  ✓ 필수 매핑 {len(REQUIRED)}개 모두 정상')


def test_legacy_prefix_consistency():
    """구형 ifrs_ prefix와 신형 ifrs-full_ prefix가 같은 시스템 계정명에 매핑되는지"""
    from dart_collector import ACCOUNT_ID_MAP

    LEGACY_PAIRS = [
        ('ifrs-full_Revenue', 'ifrs_Revenue'),
        ('ifrs-full_GrossProfit', 'ifrs_GrossProfit'),
        ('ifrs-full_ProfitLoss', 'ifrs_ProfitLoss'),
        ('ifrs-full_Assets', 'ifrs_Assets'),
        ('ifrs-full_Equity', 'ifrs_Equity'),
    ]

    violations = []
    for new, old in LEGACY_PAIRS:
        n = ACCOUNT_ID_MAP.get(new)
        o = ACCOUNT_ID_MAP.get(old)
        if n is None or o is None:
            continue  # 한쪽만 있는 건 OK
        if n != o:
            violations.append((new, n, old, o))

    if violations:
        for new, n, old, o in violations:
            print(f'  ✗ {new}={n} ≠ {old}={o}')
        raise AssertionError(f'{len(violations)}건 prefix 매핑 불일치')
    print(f'  ✓ legacy prefix 일관성 정상')


def main():
    print('=' * 50)
    print('dart_collector ACCOUNT_ID_MAP 무결성 검사')
    print('=' * 50)
    tests = [
        ('test_no_expense_to_revenue', test_no_expense_to_revenue),
        ('test_blacklist', test_blacklist),
        ('test_required_mappings', test_required_mappings),
        ('test_legacy_prefix_consistency', test_legacy_prefix_consistency),
    ]
    failed = 0
    for name, fn in tests:
        print(f'\n[{name}]')
        try:
            fn()
        except AssertionError as e:
            print(f'  FAILED: {e}')
            failed += 1
        except Exception as e:
            print(f'  ERROR: {type(e).__name__}: {e}')
            failed += 1

    print('\n' + '=' * 50)
    if failed:
        print(f'❌ {failed}/{len(tests)} 테스트 실패')
        return 1
    print(f'✅ 모든 테스트 통과 ({len(tests)}/{len(tests)})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
