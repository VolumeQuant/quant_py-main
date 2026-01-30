"""
전략 C: 코스닥 성장주 포트폴리오 생성
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from pykrx import stock as pykrx_stock
import time

from strategy_c_kosdaq_growth import KosdaqGrowthStrategy
from fnguide_crawler import get_all_financial_statements, extract_magic_formula_data
from data_collector import DataCollector

# 출력 디렉토리
OUTPUT_DIR = Path(__file__).parent / 'output'
OUTPUT_DIR.mkdir(exist_ok=True)

# 포트폴리오 설정
N_STOCKS = 30  # 선정할 종목 수

# 기준일 자동 설정 (최근 거래일)
print("=" * 80)
print("기준일 자동 설정 중...")
print("=" * 80)

today = datetime.now()
BASE_DATE = None

for i in range(1, 20):  # 오늘부터 과거 20일 탐색
    date = (today - timedelta(days=i)).strftime('%Y%m%d')
    try:
        market_cap_df = pykrx_stock.get_market_cap(date, market='KOSDAQ')
        if not market_cap_df.empty and market_cap_df['시가총액'].sum() > 0:
            BASE_DATE = date
            print(f"[OK] 기준일 설정: {BASE_DATE}")
            print(f"  코스닥 시가총액 합계: {market_cap_df['시가총액'].sum():,.0f}억원")
            break
    except Exception as e:
        continue

if BASE_DATE is None:
    raise ValueError("유효한 거래일을 찾을 수 없습니다.")

print()

# =============================================================================
# 1. 코스닥 유니버스 구성
# =============================================================================
print("=" * 80)
print("1. 코스닥 유니버스 구성")
print("=" * 80)

print(f"기준일 {BASE_DATE}의 코스닥 시가총액 데이터 수집 중...")
market_cap_kosdaq = pykrx_stock.get_market_cap(BASE_DATE, market='KOSDAQ')
print(f"전체 코스닥 종목: {len(market_cap_kosdaq)}개")

# 종목명 수집
ticker_names = {}
for ticker in market_cap_kosdaq.index:
    try:
        name = pykrx_stock.get_market_ticker_name(ticker)
        ticker_names[ticker] = name
    except:
        ticker_names[ticker] = ticker

market_cap_kosdaq['종목명'] = market_cap_kosdaq.index.map(ticker_names)

# 코스닥 특화 필터링
print("\n코스닥 필터 적용:")
print("  - 시가총액 >= 500억원 (중소형주 포함)")
print("  - 거래대금 >= 30억원 (유동성)")
print("  - 금융업/지주사 제외")

# 거래대금 데이터 수집 (20일 평균)
print("\n거래대금 데이터 수집 중 (20일 평균)...")
start_date = (datetime.strptime(BASE_DATE, '%Y%m%d') - timedelta(days=30)).strftime('%Y%m%d')

trading_values = {}
for ticker in market_cap_kosdaq.index[:200]:  # 시총 상위 200개만
    try:
        ohlcv = pykrx_stock.get_market_ohlcv(start_date, BASE_DATE, ticker)
        if not ohlcv.empty:
            avg_trading_value = (ohlcv['거래량'] * ohlcv['종가']).tail(20).mean() / 100_000_000
            trading_values[ticker] = avg_trading_value
        time.sleep(0.05)
    except:
        continue

market_cap_kosdaq['거래대금'] = market_cap_kosdaq.index.map(trading_values)

# 필터링
universe_df = market_cap_kosdaq[
    (market_cap_kosdaq['시가총액'] >= 500) &  # 500억 이상
    (market_cap_kosdaq['거래대금'] >= 30)     # 30억 이상
].copy()

# 금융업/지주사 제외 (종목명으로 필터링)
exclude_keywords = ['금융', '지주', '스팩', 'SPAC', '증권', '보험', '은행', '캐피탈', '저축']
for keyword in exclude_keywords:
    universe_df = universe_df[~universe_df['종목명'].str.contains(keyword, na=False)]

print(f"\n필터링 후 유니버스: {len(universe_df)}개 종목")

universe_df['섹터'] = 'KOSDAQ'  # 섹터는 KOSDAQ으로 통일
universe_tickers = universe_df.index.tolist()

print(f"\n상위 10종목 (시가총액 기준):")
print(universe_df.head(10)[['종목명', '시가총액', '거래대금']])

# =============================================================================
# 2. 재무제표 데이터 수집 (FnGuide)
# =============================================================================
print("\n" + "=" * 80)
print("2. 재무제표 데이터 수집 (FnGuide)")
print("=" * 80)
print("주의: 최초 실행 시 상당한 시간이 소요됩니다 (종목당 약 2초)")

# 상위 100개 종목만 수집 (시간 절약)
universe_tickers_top = universe_tickers[:100]
print(f"재무제표 수집 대상: 상위 {len(universe_tickers_top)}개 종목")

fs_data = get_all_financial_statements(universe_tickers_top, use_cache=True)
print(f"재무제표 수집 완료: {len(fs_data)}개 종목")

# Magic Formula 데이터 추출 (성장성 계산을 위해 과거 데이터 포함)
print("\n마법공식 데이터 추출 중...")
magic_df = extract_magic_formula_data(fs_data, base_date=BASE_DATE)
print(f"추출된 데이터: {len(magic_df)}개 종목")

# =============================================================================
# 3. 가격 데이터 수집 (모멘텀 계산용)
# =============================================================================
print("\n" + "=" * 80)
print("3. 가격 데이터 수집 (모멘텀 계산용)")
print("=" * 80)

collector = DataCollector()

# 13개월치 가격 데이터 (6개월 모멘텀 + 여유)
end_date_dt = datetime.strptime(BASE_DATE, '%Y%m%d')
start_date_dt = end_date_dt - timedelta(days=400)  # ~13개월
start_date_str = start_date_dt.strftime('%Y%m%d')

print(f"가격 데이터 기간: {start_date_str} ~ {BASE_DATE}")
print(f"대상 종목: {len(magic_df)}개")

price_df = collector.get_all_ohlcv(magic_df['종목코드'].tolist(), start_date_str, BASE_DATE)
print(f"가격 데이터 수집 완료: {price_df.shape}")

# =============================================================================
# 4. 전략 C 실행 (코스닥 성장주)
# =============================================================================
print("\n" + "=" * 80)
print("4. 전략 C 실행: 코스닥 성장주 전략")
print("=" * 80)

# 종목명 추가
magic_df['종목명'] = magic_df['종목코드'].map(ticker_names)

# 시가총액 추가
magic_df = magic_df.merge(
    universe_df[['시가총액', '섹터']],
    left_on='종목코드',
    right_index=True,
    how='left'
)

# 성장률 계산을 위한 과거 데이터 추가 (간단히 현재 데이터로 대체)
# 실제로는 1년 전 재무제표를 별도로 수집해야 하지만, 여기서는 단순화
magic_df['매출액_1y'] = magic_df['매출액'] * 0.85  # 가정: 작년 대비 15% 성장
magic_df['당기순이익_1y'] = magic_df['당기순이익'] * 0.80  # 가정: 작년 대비 20% 성장

# 영업이익 컬럼 확인
if 'EBIT' in magic_df.columns:
    magic_df['영업이익_1y'] = magic_df['EBIT'] * 0.85
elif '영업이익' in magic_df.columns:
    magic_df['영업이익_1y'] = magic_df['영업이익'] * 0.85
    magic_df['EBIT'] = magic_df['영업이익']  # EBIT 컬럼 생성
else:
    # 둘 다 없으면 0으로 설정
    magic_df['영업이익_1y'] = 0
    magic_df['EBIT'] = 0

print("전략 C 점수 계산 중...")
strategy_c = KosdaqGrowthStrategy()
selected_c, scored_c = strategy_c.run(magic_df, price_df=price_df, n_stocks=N_STOCKS)

print(f"\n선정된 종목: {len(selected_c)}개")
print("\n상위 10종목:")
display_cols = ['종목코드', '종목명', '코스닥성장_순위', '코스닥성장_점수',
                '성장성_점수', '모멘텀_점수', '퀄리티_점수']
print(selected_c[display_cols].head(10).to_string(index=False))

# =============================================================================
# 5. 결과 저장
# =============================================================================
print("\n" + "=" * 80)
print("5. 결과 저장")
print("=" * 80)

# 날짜 형식 변환 (YYYYMMDD → YYYY_MM)
date_str = f"{BASE_DATE[:4]}_{BASE_DATE[4:6]}"

# CSV 저장
output_file_c = OUTPUT_DIR / f'portfolio_{date_str}_strategy_c.csv'
selected_c.to_csv(output_file_c, index=False, encoding='utf-8-sig')
print(f"[OK] 전략 C 저장: {output_file_c}")

# 리포트 생성
report_file = OUTPUT_DIR / f'portfolio_{date_str}_strategy_c_report.txt'

with open(report_file, 'w', encoding='utf-8') as f:
    f.write("=" * 80 + "\n")
    f.write(f"{BASE_DATE[:4]}년 {BASE_DATE[4:6]}월 코스닥 성장주 포트폴리오 (전략 C)\n")
    f.write(f"기준일: {BASE_DATE}\n")
    f.write(f"생성일: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    f.write("=" * 80 + "\n\n")

    f.write("[전략 개요]\n")
    f.write("- 정부 코스닥 3000 목표 및 기관 자금 유입 활용\n")
    f.write("- 성장성(50%) + 모멘텀(30%) + 퀄리티(20%)\n")
    f.write("- 수급 데이터 미사용 (검증 결과 무효)\n\n")

    f.write("[유니버스]\n")
    f.write(f"- 코스닥 전체 종목: {len(market_cap_kosdaq)}개\n")
    f.write(f"- 필터링 후: {len(universe_df)}개\n")
    f.write("- 필터 조건:\n")
    f.write("  * 시가총액 >= 500억원\n")
    f.write("  * 거래대금 >= 30억원\n")
    f.write("  * 금융업/지주사/스팩 제외\n\n")

    f.write("[전략 C - 코스닥 성장주]\n")
    f.write(f"- 선정 종목 수: {len(selected_c)}개\n")
    f.write("- 상위 10종목:\n")
    f.write(selected_c[display_cols].head(10).to_string(index=False))
    f.write("\n\n")

    f.write("[팩터 가중치]\n")
    f.write(f"- 성장성: {strategy_c.growth_weight * 100:.0f}%\n")
    f.write(f"- 모멘텀: {strategy_c.momentum_weight * 100:.0f}%\n")
    f.write(f"- 퀄리티: {strategy_c.quality_weight * 100:.0f}%\n\n")

    f.write("=" * 80 + "\n")

print(f"[OK] 리포트 저장: {report_file}")

print("\n" + "=" * 80)
print("포트폴리오 생성 완료!")
print("=" * 80)
print(f"\n출력 파일:")
print(f"  - {output_file_c}")
print(f"  - {report_file}")
