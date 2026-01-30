"""
전략 A, B, C 비교 분석
코스닥 150 벤치마크 포함
"""

import pandas as pd
from pathlib import Path
from pykrx import stock as pykrx_stock
from datetime import datetime

# 파일 경로
OUTPUT_DIR = Path(__file__).parent / 'output'

# 포트폴리오 파일 읽기
print("=" * 80)
print("전략 A, B, C 포트폴리오 비교 분석")
print("=" * 80)

portfolio_a = pd.read_csv(OUTPUT_DIR / 'portfolio_2026_01_strategy_a.csv')
portfolio_b = pd.read_csv(OUTPUT_DIR / 'portfolio_2026_01_strategy_b.csv')
portfolio_c = pd.read_csv(OUTPUT_DIR / 'portfolio_2026_01_strategy_c.csv')

print(f"\n전략 A (마법공식): {len(portfolio_a)}개 종목")
print(f"전략 B (멀티팩터): {len(portfolio_b)}개 종목")
print(f"전략 C (코스닥 성장주): {len(portfolio_c)}개 종목")

# =============================================================================
# 1. 시장별 분포 비교
# =============================================================================
print("\n" + "=" * 80)
print("1. 시장별 분포")
print("=" * 80)

# 코스피/코스닥 구분 (종목코드 앞자리로 구분)
def get_market(ticker):
    """종목코드로 시장 구분"""
    try:
        # pykrx로 확인
        if ticker in pykrx_stock.get_market_ticker_list(market='KOSPI'):
            return 'KOSPI'
        elif ticker in pykrx_stock.get_market_ticker_list(market='KOSDAQ'):
            return 'KOSDAQ'
        else:
            return 'Unknown'
    except:
        return 'Unknown'

# 전략 A, B에 시장 구분 추가
print("\n시장 구분 중...")
portfolio_a['시장'] = portfolio_a['종목코드'].apply(get_market)
portfolio_b['시장'] = portfolio_b['종목코드'].apply(get_market)
portfolio_c['시장'] = 'KOSDAQ'  # 전략 C는 코스닥만

# 시장별 집계
print("\n[전략 A - 마법공식]")
print(portfolio_a['시장'].value_counts())
print(f"코스닥 비중: {(portfolio_a['시장'] == 'KOSDAQ').sum() / len(portfolio_a) * 100:.1f}%")

print("\n[전략 B - 멀티팩터]")
print(portfolio_b['시장'].value_counts())
print(f"코스닥 비중: {(portfolio_b['시장'] == 'KOSDAQ').sum() / len(portfolio_b) * 100:.1f}%")

print("\n[전략 C - 코스닥 성장주]")
print(portfolio_c['시장'].value_counts())
print(f"코스닥 비중: 100.0%")

# =============================================================================
# 2. 종목 중복 분석
# =============================================================================
print("\n" + "=" * 80)
print("2. 전략 간 중복 종목")
print("=" * 80)

set_a = set(portfolio_a['종목코드'])
set_b = set(portfolio_b['종목코드'])
set_c = set(portfolio_c['종목코드'])

print(f"\n전략 A ∩ B: {len(set_a & set_b)}개")
if len(set_a & set_b) > 0:
    common_ab = portfolio_a[portfolio_a['종목코드'].isin(set_a & set_b)][['종목코드', '종목명']]
    print(common_ab.to_string(index=False))

print(f"\n전략 A ∩ C: {len(set_a & set_c)}개")
if len(set_a & set_c) > 0:
    common_ac = portfolio_a[portfolio_a['종목코드'].isin(set_a & set_c)][['종목코드', '종목명']]
    print(common_ac.to_string(index=False))

print(f"\n전략 B ∩ C: {len(set_b & set_c)}개")
if len(set_b & set_c) > 0:
    common_bc = portfolio_b[portfolio_b['종목코드'].isin(set_b & set_c)][['종목코드', '종목명']]
    print(common_bc.to_string(index=False))

print(f"\n전략 A ∩ B ∩ C: {len(set_a & set_b & set_c)}개")
if len(set_a & set_b & set_c) > 0:
    common_abc = portfolio_a[portfolio_a['종목코드'].isin(set_a & set_b & set_c)][['종목코드', '종목명']]
    print(common_abc.to_string(index=False))

# =============================================================================
# 3. 시가총액 분포 비교
# =============================================================================
print("\n" + "=" * 80)
print("3. 시가총액 분포 (억원)")
print("=" * 80)

print(f"\n[전략 A - 마법공식]")
print(f"평균: {portfolio_a['시가총액'].mean():,.0f}억")
print(f"중앙값: {portfolio_a['시가총액'].median():,.0f}억")
print(f"최소: {portfolio_a['시가총액'].min():,.0f}억")
print(f"최대: {portfolio_a['시가총액'].max():,.0f}억")

print(f"\n[전략 B - 멀티팩터]")
print(f"평균: {portfolio_b['시가총액'].mean():,.0f}억")
print(f"중앙값: {portfolio_b['시가총액'].median():,.0f}억")
print(f"최소: {portfolio_b['시가총액'].min():,.0f}억")
print(f"최대: {portfolio_b['시가총액'].max():,.0f}억")

print(f"\n[전략 C - 코스닥 성장주]")
print(f"평균: {portfolio_c['시가총액'].mean():,.0f}억")
print(f"중앙값: {portfolio_c['시가총액'].median():,.0f}억")
print(f"최소: {portfolio_c['시가총액'].min():,.0f}억")
print(f"최대: {portfolio_c['시가총액'].max():,.0f}억")

# =============================================================================
# 4. 팩터 점수 비교
# =============================================================================
print("\n" + "=" * 80)
print("4. 팩터 점수 비교")
print("=" * 80)

print(f"\n[전략 A - 마법공식]")
if '이익수익률' in portfolio_a.columns:
    print(f"평균 이익수익률: {portfolio_a['이익수익률'].mean() * 100:.2f}%")
if '투하자본수익률' in portfolio_a.columns:
    print(f"평균 투하자본수익률: {portfolio_a['투하자본수익률'].mean() * 100:.2f}%")

print(f"\n[전략 B - 멀티팩터]")
if '밸류_점수' in portfolio_b.columns:
    print(f"평균 밸류 점수: {portfolio_b['밸류_점수'].mean():.3f}")
if '퀄리티_점수' in portfolio_b.columns:
    print(f"평균 퀄리티 점수: {portfolio_b['퀄리티_점수'].mean():.3f}")
if '모멘텀_점수' in portfolio_b.columns:
    print(f"평균 모멘텀 점수: {portfolio_b['모멘텀_점수'].mean():.3f}")

print(f"\n[전략 C - 코스닥 성장주]")
if '성장성_점수' in portfolio_c.columns:
    print(f"평균 성장성 점수: {portfolio_c['성장성_점수'].mean():.3f}")
if '모멘텀_점수' in portfolio_c.columns:
    print(f"평균 모멘텀 점수: {portfolio_c['모멘텀_점수'].mean():.3f}")
if '퀄리티_점수' in portfolio_c.columns:
    print(f"평균 퀄리티 점수: {portfolio_c['퀄리티_점수'].mean():.3f}")

# =============================================================================
# 5. 코스닥만 추출해서 비교
# =============================================================================
print("\n" + "=" * 80)
print("5. 코스닥 종목만 비교 (전략 A, B에서 추출)")
print("=" * 80)

portfolio_a_kosdaq = portfolio_a[portfolio_a['시장'] == 'KOSDAQ'].copy()
portfolio_b_kosdaq = portfolio_b[portfolio_b['시장'] == 'KOSDAQ'].copy()

print(f"\n전략 A의 코스닥 종목: {len(portfolio_a_kosdaq)}개")
print(portfolio_a_kosdaq[['종목코드', '종목명', '시가총액']].head(10).to_string(index=False))

print(f"\n전략 B의 코스닥 종목: {len(portfolio_b_kosdaq)}개")
print(portfolio_b_kosdaq[['종목코드', '종목명', '시가총액']].head(10).to_string(index=False))

print(f"\n전략 C의 코스닥 종목: {len(portfolio_c)}개")
print(portfolio_c[['종목코드', '종목명', '시가총액']].head(10).to_string(index=False))

# =============================================================================
# 6. 코스닥 150 벤치마크와 비교
# =============================================================================
print("\n" + "=" * 80)
print("6. 코스닥 150 벤치마크 비교")
print("=" * 80)

# 코스닥 150 구성 종목 (시총 상위 150개)
BASE_DATE = '20260129'
print(f"\n기준일: {BASE_DATE}")

try:
    kosdaq_all = pykrx_stock.get_market_cap(BASE_DATE, market='KOSDAQ')
    kosdaq_150_tickers = kosdaq_all.nlargest(150, '시가총액').index.tolist()

    print(f"코스닥 150 구성: {len(kosdaq_150_tickers)}개 종목")
    print(f"코스닥 150 시가총액 합계: {kosdaq_all.loc[kosdaq_150_tickers, '시가총액'].sum():,.0f}억")

    # 전략별 코스닥 150 편입 종목 확인
    a_in_kq150 = set(portfolio_a_kosdaq['종목코드']) & set(kosdaq_150_tickers)
    b_in_kq150 = set(portfolio_b_kosdaq['종목코드']) & set(kosdaq_150_tickers)
    c_in_kq150 = set(portfolio_c['종목코드']) & set(kosdaq_150_tickers)

    print(f"\n[코스닥 150 편입 비율]")
    print(f"전략 A: {len(a_in_kq150)}/{len(portfolio_a_kosdaq)}개 ({len(a_in_kq150)/max(len(portfolio_a_kosdaq),1)*100:.1f}%)")
    print(f"전략 B: {len(b_in_kq150)}/{len(portfolio_b_kosdaq)}개 ({len(b_in_kq150)/max(len(portfolio_b_kosdaq),1)*100:.1f}%)")
    print(f"전략 C: {len(c_in_kq150)}/{len(portfolio_c)}개 ({len(c_in_kq150)/len(portfolio_c)*100:.1f}%)")

    # 코스닥 150 외 종목 (중소형주)
    print(f"\n[중소형주 비중 (코스닥 150 외)]")
    print(f"전략 A: {len(portfolio_a_kosdaq) - len(a_in_kq150)}개 ({(len(portfolio_a_kosdaq) - len(a_in_kq150))/max(len(portfolio_a_kosdaq),1)*100:.1f}%)")
    print(f"전략 B: {len(portfolio_b_kosdaq) - len(b_in_kq150)}개 ({(len(portfolio_b_kosdaq) - len(b_in_kq150))/max(len(portfolio_b_kosdaq),1)*100:.1f}%)")
    print(f"전략 C: {len(portfolio_c) - len(c_in_kq150)}개 ({(len(portfolio_c) - len(c_in_kq150))/len(portfolio_c)*100:.1f}%)")

except Exception as e:
    print(f"코스닥 150 데이터 수집 실패: {e}")

# =============================================================================
# 7. 요약 비교표
# =============================================================================
print("\n" + "=" * 80)
print("7. 전략 종합 비교")
print("=" * 80)

summary = pd.DataFrame({
    '항목': [
        '전략명',
        '선정 종목 수',
        '코스닥 비중',
        '평균 시가총액',
        '중앙 시가총액',
        '코스닥150 편입',
        '팩터 가중치',
    ],
    '전략 A': [
        '마법공식',
        f"{len(portfolio_a)}개",
        f"{(portfolio_a['시장'] == 'KOSDAQ').sum() / len(portfolio_a) * 100:.1f}%",
        f"{portfolio_a['시가총액'].mean():,.0f}억",
        f"{portfolio_a['시가총액'].median():,.0f}억",
        f"{len(a_in_kq150)}/{len(portfolio_a_kosdaq)}개" if 'a_in_kq150' in locals() else 'N/A',
        '이익수익률 + 투하자본수익률',
    ],
    '전략 B': [
        '멀티팩터',
        f"{len(portfolio_b)}개",
        f"{(portfolio_b['시장'] == 'KOSDAQ').sum() / len(portfolio_b) * 100:.1f}%",
        f"{portfolio_b['시가총액'].mean():,.0f}억",
        f"{portfolio_b['시가총액'].median():,.0f}억",
        f"{len(b_in_kq150)}/{len(portfolio_b_kosdaq)}개" if 'b_in_kq150' in locals() else 'N/A',
        '밸류(40%) + 퀄리티(40%) + 모멘텀(20%)',
    ],
    '전략 C': [
        '코스닥 성장주',
        f"{len(portfolio_c)}개",
        '100.0%',
        f"{portfolio_c['시가총액'].mean():,.0f}억",
        f"{portfolio_c['시가총액'].median():,.0f}억",
        f"{len(c_in_kq150)}/{len(portfolio_c)}개" if 'c_in_kq150' in locals() else 'N/A',
        '성장성(50%) + 모멘텀(30%) + 퀄리티(20%)',
    ],
})

print("\n" + summary.to_string(index=False))

# =============================================================================
# 8. 결과 저장
# =============================================================================
print("\n" + "=" * 80)
print("8. 비교 결과 저장")
print("=" * 80)

# CSV 저장
comparison_file = OUTPUT_DIR / 'strategy_comparison_abc.csv'
summary.to_csv(comparison_file, index=False, encoding='utf-8-sig')
print(f"[OK] 비교표 저장: {comparison_file}")

# 상세 리포트 저장
report_file = OUTPUT_DIR / 'strategy_comparison_abc_report.txt'
with open(report_file, 'w', encoding='utf-8') as f:
    f.write("=" * 80 + "\n")
    f.write("전략 A, B, C 비교 분석 리포트\n")
    f.write(f"생성일: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    f.write("=" * 80 + "\n\n")

    f.write("[전략 개요]\n")
    f.write("- 전략 A: 마법공식 (이익수익률 + 투하자본수익률)\n")
    f.write("- 전략 B: 멀티팩터 (밸류 + 퀄리티 + 모멘텀)\n")
    f.write("- 전략 C: 코스닥 성장주 (성장성 + 모멘텀 + 퀄리티)\n\n")

    f.write("[종합 비교]\n")
    f.write(summary.to_string(index=False))
    f.write("\n\n")

    f.write("[시장 분포]\n")
    f.write(f"전략 A - 코스닥: {(portfolio_a['시장'] == 'KOSDAQ').sum()}개 ")
    f.write(f"({(portfolio_a['시장'] == 'KOSDAQ').sum() / len(portfolio_a) * 100:.1f}%)\n")
    f.write(f"전략 B - 코스닥: {(portfolio_b['시장'] == 'KOSDAQ').sum()}개 ")
    f.write(f"({(portfolio_b['시장'] == 'KOSDAQ').sum() / len(portfolio_b) * 100:.1f}%)\n")
    f.write(f"전략 C - 코스닥: {len(portfolio_c)}개 (100.0%)\n\n")

    if 'a_in_kq150' in locals():
        f.write("[코스닥 150 편입]\n")
        f.write(f"전략 A: {len(a_in_kq150)}/{len(portfolio_a_kosdaq)}개\n")
        f.write(f"전략 B: {len(b_in_kq150)}/{len(portfolio_b_kosdaq)}개\n")
        f.write(f"전략 C: {len(c_in_kq150)}/{len(portfolio_c)}개\n\n")

    f.write("[중복 종목]\n")
    f.write(f"A ∩ B: {len(set_a & set_b)}개\n")
    f.write(f"A ∩ C: {len(set_a & set_c)}개\n")
    f.write(f"B ∩ C: {len(set_b & set_c)}개\n")
    f.write(f"A ∩ B ∩ C: {len(set_a & set_b & set_c)}개\n\n")

    f.write("=" * 80 + "\n")

print(f"[OK] 상세 리포트 저장: {report_file}")

print("\n" + "=" * 80)
print("비교 분석 완료!")
print("=" * 80)
print(f"\n출력 파일:")
print(f"  - {comparison_file}")
print(f"  - {report_file}")
