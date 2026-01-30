"""
전략 B 수정 테스트 - FnGuide 데이터 사용 확인
"""

import pandas as pd
import numpy as np
import sys

# UTF-8 출력 설정
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from strategy_b_multifactor import MultiFactorStrategy

# 기존 전략 A CSV 파일에서 샘플 데이터 로드
print("기존 전략 A 데이터 로드...")
strategy_a_df = pd.read_csv('output/portfolio_2026_01_strategy_a.csv', encoding='utf-8-sig')

print(f"데이터 shape: {strategy_a_df.shape}")
print(f"\n컬럼 목록: {list(strategy_a_df.columns)}")

# 필요한 컬럼 확인
required_cols = ['종목코드', '당기순이익', '자본', '자산', '매출액', '매출총이익',
                 '영업현금흐름', '시가총액', '종목명']
missing_cols = [col for col in required_cols if col not in strategy_a_df.columns]

if missing_cols:
    print(f"\n[!] 누락된 컬럼: {missing_cols}")
else:
    print(f"\n[OK] 모든 필수 컬럼 존재")

# 전략 B 실행 테스트
print("\n" + "=" * 80)
print("전략 B 실행 테스트 (상위 10종목)")
print("=" * 80)

strategy_b = MultiFactorStrategy()

try:
    # 전략 B 실행
    selected, scored = strategy_b.run(strategy_a_df, price_df=None, n_stocks=10)

    print("\n[OK] 전략 B 실행 성공!")
    print(f"\n상위 10종목:")

    display_cols = ['종목코드', '종목명', '멀티팩터_점수', '밸류_점수', '퀄리티_점수']
    display_cols = [col for col in display_cols if col in selected.columns]
    print(selected[display_cols].to_string(index=False))

    # 계산된 팩터 확인
    print(f"\n계산된 팩터:")
    factor_cols = ['PER', 'PBR', 'PCR', 'PSR', 'ROE', 'GPA', 'CFO']
    available_factors = [col for col in factor_cols if col in scored.columns]
    print(f"  사용 가능: {available_factors}")

    # 샘플 종목의 팩터 값 확인
    if len(selected) > 0:
        print(f"\n1위 종목 ({selected.iloc[0]['종목명']}) 팩터 값:")
        first_ticker = selected.iloc[0]['종목코드']
        first_row = scored[scored['종목코드'] == first_ticker].iloc[0]

        for col in available_factors:
            value = first_row[col]
            print(f"  {col}: {value:.2f}" if not pd.isna(value) else f"  {col}: N/A")

    print("\n" + "=" * 80)
    print("[OK] 테스트 완료! 전략 B가 FnGuide 데이터로 정상 작동합니다.")
    print("=" * 80)

except Exception as e:
    print(f"\n[ERROR] 전략 B 실행 중 오류:")
    print(f"  {e}")
    import traceback
    traceback.print_exc()
