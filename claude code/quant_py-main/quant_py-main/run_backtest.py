"""
한국 주식 멀티팩터 전략 백테스팅 실행 스크립트
- 전략 A: 마법공식
- 전략 B: 멀티팩터
- 벤치마크: 코스피
"""

import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

from fnguide_crawler import get_all_financial_statements, extract_magic_formula_data
from data_collector import DataCollector
from strategy_a_magic import MagicFormulaStrategy, prepare_financial_data_for_magic
from strategy_b_multifactor import MultiFactorStrategy

print("=" * 80)
print("한국 주식 멀티팩터 전략 백테스팅 시스템")
print("=" * 80)

# ============================================================================
# 1단계: 샘플 종목으로 테스트 (대형주 20개)
# ============================================================================
print("\n[1단계] 샘플 종목 설정")

# 코스피 대표 종목 (시가총액 상위)
sample_tickers = [
    '005930',  # 삼성전자
    '000660',  # SK하이닉스
    '051910',  # LG화학
    '006400',  # 삼성SDI
    '035420',  # NAVER
    '005380',  # 현대차
    '035720',  # 카카오
    '000270',  # 기아
    '068270',  # 셀트리온
    '207940',  # 삼성바이오로직스
    '005490',  # POSCO홀딩스
    '105560',  # KB금융
    '055550',  # 신한지주
    '028260',  # 삼성물산
    '012330',  # 현대모비스
    '066570',  # LG전자
    '096770',  # SK이노베이션
    '003550',  # LG
    '034730',  # SK
    '017670',  # SK텔레콤
]

print(f"샘플 종목 수: {len(sample_tickers)}개")

# ============================================================================
# 2단계: 재무제표 데이터 수집 (FnGuide 크롤링)
# ============================================================================
print("\n[2단계] 재무제표 데이터 수집 (FnGuide)")
print("주의: 최초 실행 시 약 2-3분 소요될 수 있습니다.")
print("캐시가 있으면 즉시 로드됩니다.\n")

fs_data = get_all_financial_statements(sample_tickers, use_cache=True)

print(f"\n수집 완료: {len(fs_data)}개 종목")

# ============================================================================
# 3단계: 마법공식 데이터 추출
# ============================================================================
print("\n[3단계] 마법공식용 재무 데이터 추출")

magic_df = extract_magic_formula_data(fs_data)

if not magic_df.empty:
    print(f"추출된 종목 수: {len(magic_df)}")
    print("\n컬럼:")
    print(magic_df.columns.tolist())

    print("\n샘플 데이터:")
    print(magic_df.head())
else:
    print("경고: 마법공식 데이터 추출 실패")

# ============================================================================
# 4단계: 시가총액 데이터 수집
# ============================================================================
print("\n[4단계] 시가총액 데이터 수집 (pykrx)")

collector = DataCollector(start_date='20150101', end_date='20251231')

# 최근 시가총액
latest_date = '20241231'
market_cap_df = collector.get_market_cap(latest_date, market='ALL')

# 샘플 종목만 필터링
market_cap_sample = market_cap_df[market_cap_df.index.isin(sample_tickers)]

print(f"시가총액 데이터: {len(market_cap_sample)}개 종목")
print(market_cap_sample.head())

# ============================================================================
# 5단계: 전략 A - 마법공식 실행
# ============================================================================
print("\n[5단계] 전략 A - 마법공식 실행")

# 재무제표 + 시가총액 데이터 결합
if not magic_df.empty:
    # 시가총액 데이터 추가
    magic_df_with_mcap = magic_df.merge(
        market_cap_sample[['시가총액']],
        left_on='종목코드',
        right_index=True,
        how='left'
    )

    # 억원 단위로 변환 (FnGuide는 억원, pykrx는 원)
    magic_df_with_mcap['시가총액'] = magic_df_with_mcap['시가총액'] / 100_000_000

    print(f"\n마법공식 입력 데이터:")
    print(magic_df_with_mcap.head())

    # 마법공식 전략 실행
    strategy_a = MagicFormulaStrategy()

    try:
        selected_a, scored_a = strategy_a.run(magic_df_with_mcap, n_stocks=10)

        print(f"\n[전략 A 결과] 상위 10개 종목:")
        print(selected_a[['종목코드', '이익수익률', '투하자본수익률', '마법공식_순위']])

    except Exception as e:
        print(f"마법공식 실행 중 오류: {e}")
        print("재무제표 항목이 부족할 수 있습니다. 계정명을 확인하세요.")

        # 사용 가능한 계정 확인
        if not magic_df.empty:
            print("\n사용 가능한 계정:")
            print([col for col in magic_df.columns if col not in ['종목코드', '기준일']])

else:
    print("마법공식 데이터가 없어 전략 A를 실행할 수 없습니다.")

# ============================================================================
# 6단계: 전략 B - 멀티팩터 실행
# ============================================================================
print("\n[6단계] 전략 B - 멀티팩터 실행")

# 펀더멘털 데이터 (pykrx) - 캐시 사용 안함 (테스트)
import os
cache_file = os.path.join('data_cache', f'fundamentals_{latest_date}.parquet')
if os.path.exists(cache_file):
    os.remove(cache_file)
    print(f"기존 캐시 삭제: {cache_file}")

fundamental_df = collector.get_all_fundamentals(latest_date, sample_tickers)

if not fundamental_df.empty:
    print(f"펀더멘털 데이터: {len(fundamental_df)}개 종목")
    print(fundamental_df.head())

    # 멀티팩터 전략 실행
    strategy_b = MultiFactorStrategy()

    try:
        selected_b, scored_b = strategy_b.run(fundamental_df, price_df=None, n_stocks=10)

        print(f"\n[전략 B 결과] 상위 10개 종목:")
        result_cols = ['종목코드', '멀티팩터_점수', '밸류_점수', '퀄리티_점수']
        available_cols = [col for col in result_cols if col in selected_b.columns]
        print(selected_b[available_cols])

    except Exception as e:
        print(f"멀티팩터 실행 중 오류: {e}")
        import traceback
        traceback.print_exc()

else:
    print("펀더멘털 데이터가 없어 전략 B를 실행할 수 없습니다.")

# ============================================================================
# 7단계: 결과 저장
# ============================================================================
print("\n[7단계] 결과 저장")

# 결과를 CSV로 저장
if 'selected_a' in locals() and not selected_a.empty:
    selected_a.to_csv('strategy_a_portfolio.csv', index=False, encoding='utf-8-sig')
    print("전략 A 포트폴리오 저장: strategy_a_portfolio.csv")

if 'selected_b' in locals() and not selected_b.empty:
    selected_b.to_csv('strategy_b_portfolio.csv', index=False, encoding='utf-8-sig')
    print("전략 B 포트폴리오 저장: strategy_b_portfolio.csv")

print("\n" + "=" * 80)
print("테스트 완료!")
print("=" * 80)
print("\n다음 단계:")
print("1. 재무제표 계정명 매핑 확인 및 수정")
print("2. 전체 종목으로 확장 (현재는 샘플 20개만)")
print("3. 주가 데이터 수집 및 백테스트 실행")
print("4. 리밸런싱 로직 구현")
