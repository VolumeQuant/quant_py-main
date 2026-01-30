"""
2026년 1월 현재 포트폴리오 생성
- 전체 KOSPI/KOSDAQ 유니버스에서 필터링
- 2025년 12월 말 기준 재무데이터 수집
- 전략 A (마법공식), 전략 B (멀티팩터) 실행
"""

import pandas as pd
import numpy as np
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings('ignore')

from fnguide_crawler import get_all_financial_statements, extract_magic_formula_data
from data_collector import DataCollector
from strategy_a_magic import MagicFormulaStrategy
from strategy_b_multifactor import MultiFactorStrategy

# 설정
# 최근 거래일 자동 탐지
from pykrx import stock as pykrx_stock
from datetime import datetime as dt, timedelta as td
_today = dt.now()
BASE_DATE = None
for _i in range(1, 20):  # 1부터 시작 (오늘 제외)
    _date = (_today - td(days=_i)).strftime('%Y%m%d')
    try:
        _df = pykrx_stock.get_market_cap(_date, market='KOSPI')
        # 시가총액 합계가 0보다 큰지 확인
        if not _df.empty and _df['시가총액'].sum() > 0:
            BASE_DATE = _date
            break
    except:
        continue
if BASE_DATE is None:
    BASE_DATE = '20260129'  # 기본값
MIN_MARKET_CAP = 1000  # 최소 시가총액 (억원)
MIN_TRADING_VALUE = 50  # 최소 거래대금 (억원) - 유동성 리스크 감소
N_STOCKS = 30  # 선정 종목 수
OUTPUT_DIR = Path(__file__).parent / 'output'
OUTPUT_DIR.mkdir(exist_ok=True)


def filter_universe(market_cap_df, fundamental_df):
    """
    유니버스 필터링

    조건:
    1. 시가총액 >= 1000억원
    2. 거래대금 >= 10억원 (일평균)
    3. 금융업/지주사 제외 (종목명 기준)
    """
    print("\n[유니버스 필터링]")
    print(f"전체 종목 수: {len(market_cap_df)}")

    # 1. 시가총액 필터 (원 → 억원 변환)
    market_cap_df['시가총액_억'] = market_cap_df['시가총액'] / 100_000_000
    filtered = market_cap_df[market_cap_df['시가총액_억'] >= MIN_MARKET_CAP].copy()
    print(f"시가총액 {MIN_MARKET_CAP}억원 이상: {len(filtered)}개")

    # 2. 거래대금 필터 (원 → 억원 변환)
    filtered['거래대금_억'] = filtered['거래대금'] / 100_000_000
    filtered = filtered[filtered['거래대금_억'] >= MIN_TRADING_VALUE]
    print(f"거래대금 {MIN_TRADING_VALUE}억원 이상: {len(filtered)}개")

    # 3. 금융업/지주사 제외 (종목명 기준 간단 필터)
    # 실제로는 업종 코드로 필터링하는 것이 정확함
    exclude_keywords = ['금융', '은행', '증권', '보험', '캐피탈', '카드', '저축',
                       '지주', '홀딩스', 'SPAC', '스팩', '리츠', 'REIT']

    # 종목명 가져오기
    from pykrx import stock
    ticker_names = {}
    for ticker in filtered.index:
        try:
            name = stock.get_market_ticker_name(ticker)
            ticker_names[ticker] = name
        except:
            ticker_names[ticker] = ''

    filtered['종목명'] = filtered.index.map(ticker_names)

    # 제외 키워드 필터링
    mask = ~filtered['종목명'].str.contains('|'.join(exclude_keywords), na=False)
    filtered = filtered[mask]
    print(f"금융업/지주사 제외 후: {len(filtered)}개")

    return filtered


def main():
    print("=" * 80)
    print("2026년 1월 현재 포트폴리오 생성")
    print(f"기준일: {BASE_DATE}")
    print("=" * 80)

    # =========================================================================
    # 1단계: 전체 종목 시가총액 데이터 수집
    # =========================================================================
    print("\n[1단계] 시가총액 데이터 수집")
    collector = DataCollector(start_date='20150101', end_date='20251231')

    # KOSPI와 KOSDAQ을 따로 수집하여 섹터 정보 추가
    market_cap_kospi = collector.get_market_cap(BASE_DATE, market='KOSPI')
    market_cap_kosdaq = collector.get_market_cap(BASE_DATE, market='KOSDAQ')
    market_cap_kospi['섹터'] = 'KOSPI'
    market_cap_kosdaq['섹터'] = 'KOSDAQ'
    market_cap_df = pd.concat([market_cap_kospi, market_cap_kosdaq])
    print(f"전체 종목 수: {len(market_cap_df)}")

    # =========================================================================
    # 2단계: 유니버스 필터링
    # =========================================================================
    print("\n[2단계] 유니버스 필터링")

    # 펀더멘털 데이터 (필터링용)
    tickers_all = market_cap_df.index.tolist()

    # 먼저 시가총액으로 1차 필터링 (크롤링 대상 축소)
    market_cap_df['시가총액_억'] = market_cap_df['시가총액'] / 100_000_000
    pre_filtered = market_cap_df[market_cap_df['시가총액_억'] >= MIN_MARKET_CAP]
    print(f"시가총액 {MIN_MARKET_CAP}억원 이상: {len(pre_filtered)}개")

    # 거래대금 필터
    pre_filtered = pre_filtered.copy()
    pre_filtered['거래대금_억'] = pre_filtered['거래대금'] / 100_000_000
    pre_filtered = pre_filtered[pre_filtered['거래대금_억'] >= MIN_TRADING_VALUE]
    print(f"거래대금 {MIN_TRADING_VALUE}억원 이상: {len(pre_filtered)}개")

    # 금융업/지주사 제외
    from pykrx import stock
    exclude_keywords = ['금융', '은행', '증권', '보험', '캐피탈', '카드', '저축',
                       '지주', '홀딩스', 'SPAC', '스팩', '리츠', 'REIT']

    ticker_names = {}
    print("종목명 수집 중...")
    for ticker in pre_filtered.index:
        try:
            name = stock.get_market_ticker_name(ticker)
            ticker_names[ticker] = name
        except:
            ticker_names[ticker] = ''

    pre_filtered['종목명'] = pre_filtered.index.map(ticker_names)
    mask = ~pre_filtered['종목명'].str.contains('|'.join(exclude_keywords), na=False)
    universe_df = pre_filtered[mask].copy()
    print(f"금융업/지주사 제외 후 유니버스: {len(universe_df)}개")

    universe_tickers = universe_df.index.tolist()

    # =========================================================================
    # 3단계: 재무제표 데이터 수집 (FnGuide)
    # =========================================================================
    print("\n[3단계] 재무제표 데이터 수집 (FnGuide)")
    print(f"수집 대상: {len(universe_tickers)}개 종목")
    print("주의: 최초 실행 시 상당한 시간이 소요됩니다 (종목당 약 2초)")

    fs_data = get_all_financial_statements(universe_tickers, use_cache=True)
    print(f"재무제표 수집 완료: {len(fs_data)}개 종목")

    # 마법공식용 데이터 추출 (공시 시차 3개월 반영)
    magic_df = extract_magic_formula_data(fs_data, base_date=BASE_DATE)
    print(f"마법공식 데이터 추출: {len(magic_df)}개 종목 (공시 시차 3개월 반영)")

    # =========================================================================
    # 4단계: 펀더멘털 데이터 수집 (pykrx) - 현재 미사용
    # =========================================================================
    # 전략 B도 FnGuide 데이터를 사용하므로 pykrx 펀더멘털 수집 비활성화
    # print("\n[4단계] 펀더멘털 데이터 수집 (pykrx)")
    # fundamental_df = collector.get_all_fundamentals(BASE_DATE, universe_tickers)
    # print(f"펀더멘털 데이터: {len(fundamental_df)}개 종목")

    # =========================================================================
    # 5단계: 전략 A - 마법공식 실행
    # =========================================================================
    print("\n[5단계] 전략 A - 마법공식 실행")

    if not magic_df.empty:
        # 시가총액 데이터 추가
        magic_df_with_mcap = magic_df.merge(
            universe_df[['시가총액', '종목명']],
            left_on='종목코드',
            right_index=True,
            how='left'
        )

        # 억원 단위로 변환
        magic_df_with_mcap['시가총액'] = magic_df_with_mcap['시가총액'] / 100_000_000

        # 마법공식 전략 실행
        strategy_a = MagicFormulaStrategy()

        try:
            selected_a, scored_a = strategy_a.run(magic_df_with_mcap, n_stocks=N_STOCKS)

            print(f"\n[전략 A 결과] 상위 {N_STOCKS}개 종목:")
            display_cols = ['종목코드', '종목명', '이익수익률', '투하자본수익률', '마법공식_순위']
            display_cols = [col for col in display_cols if col in selected_a.columns]
            print(selected_a[display_cols].to_string())

            # 저장
            selected_a.to_csv(OUTPUT_DIR / 'portfolio_2026_01_strategy_a.csv',
                            index=False, encoding='utf-8-sig')
            print(f"\n저장 완료: {OUTPUT_DIR / 'portfolio_2026_01_strategy_a.csv'}")

        except Exception as e:
            print(f"마법공식 실행 중 오류: {e}")
            import traceback
            traceback.print_exc()
            selected_a = pd.DataFrame()
    else:
        print("마법공식 데이터가 없습니다.")
        selected_a = pd.DataFrame()

    # =========================================================================
    # 6단계: 전략 B - 멀티팩터 실행
    # =========================================================================
    print("\n[6단계] 전략 B - 멀티팩터 실행")

    if not magic_df.empty:
        # 전략 B를 위한 데이터 준비 (FnGuide 데이터 사용)
        multifactor_df = magic_df.copy()

        # 종목명 추가
        multifactor_df['종목명'] = multifactor_df['종목코드'].map(ticker_names)

        # 시가총액 및 섹터 정보 추가 (억원 단위로 변환)
        multifactor_df = multifactor_df.merge(
            universe_df[['시가총액', '섹터']],
            left_on='종목코드',
            right_index=True,
            how='left'
        )
        multifactor_df['시가총액'] = multifactor_df['시가총액'] / 100_000_000
        print(f"섹터 정보 추가 완료 (KOSPI: {(multifactor_df['섹터']=='KOSPI').sum()}개, "
              f"KOSDAQ: {(multifactor_df['섹터']=='KOSDAQ').sum()}개)")

        # 모멘텀 계산을 위한 주가 데이터 수집
        print("\n주가 데이터 수집 중 (모멘텀 계산용)...")
        from datetime import datetime, timedelta
        end_date_dt = datetime.strptime(BASE_DATE, '%Y%m%d')
        start_date_dt = end_date_dt - timedelta(days=400)  # 약 13개월
        start_date_str = start_date_dt.strftime('%Y%m%d')

        universe_tickers_list = universe_tickers[:500]  # 상위 500개만 (시간 단축)
        print(f"  대상 종목: {len(universe_tickers_list)}개 (시가총액 상위)")

        try:
            price_df = collector.get_all_ohlcv(universe_tickers_list, start_date_str, BASE_DATE)
            print(f"  주가 데이터 수집 완료: {len(price_df.columns)}개 종목")
        except Exception as e:
            print(f"  주가 데이터 수집 실패: {e}")
            price_df = None

        # 멀티팩터 전략 실행
        strategy_b = MultiFactorStrategy()

        try:
            # 모멘텀 팩터 포함하여 실행
            selected_b, scored_b = strategy_b.run(multifactor_df, price_df=price_df, n_stocks=N_STOCKS)

            print(f"\n[전략 B 결과] 상위 {N_STOCKS}개 종목:")
            display_cols = ['종목코드', '종목명', '멀티팩터_점수', '밸류_점수', '퀄리티_점수']
            display_cols = [col for col in display_cols if col in selected_b.columns]
            print(selected_b[display_cols].to_string())

            # 저장
            selected_b.to_csv(OUTPUT_DIR / 'portfolio_2026_01_strategy_b.csv',
                            index=False, encoding='utf-8-sig')
            print(f"\n저장 완료: {OUTPUT_DIR / 'portfolio_2026_01_strategy_b.csv'}")

        except Exception as e:
            print(f"멀티팩터 실행 중 오류: {e}")
            import traceback
            traceback.print_exc()
            selected_b = pd.DataFrame()
    else:
        print("FnGuide 데이터가 없습니다.")
        selected_b = pd.DataFrame()

    # =========================================================================
    # 7단계: 전략 비교 및 최종 리포트
    # =========================================================================
    print("\n[7단계] 전략 비교 및 최종 리포트")

    if not selected_a.empty and not selected_b.empty:
        # 공통 종목 찾기
        tickers_a = set(selected_a['종목코드'].tolist())
        tickers_b = set(selected_b['종목코드'].tolist())
        common_tickers = tickers_a & tickers_b

        print(f"\n전략 A 선정 종목: {len(tickers_a)}개")
        print(f"전략 B 선정 종목: {len(tickers_b)}개")
        print(f"공통 선정 종목: {len(common_tickers)}개")

        if common_tickers:
            print("\n공통 종목:")
            for ticker in common_tickers:
                name = ticker_names.get(ticker, '')
                rank_a = selected_a[selected_a['종목코드'] == ticker]['마법공식_순위'].values
                rank_b = selected_b[selected_b['종목코드'] == ticker]['멀티팩터_순위'].values
                rank_a = int(rank_a[0]) if len(rank_a) > 0 else '-'
                rank_b = int(rank_b[0]) if len(rank_b) > 0 else '-'
                print(f"  - {name} ({ticker}): 전략A {rank_a}위, 전략B {rank_b}위")

        # 리포트 저장
        report = f"""
================================================================================
2026년 1월 포트폴리오 분석 리포트
기준일: {BASE_DATE}
생성일: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
================================================================================

[유니버스]
- 전체 종목: {len(market_cap_df)}개
- 필터링 후: {len(universe_df)}개
- 필터 조건:
  * 시가총액 >= {MIN_MARKET_CAP}억원
  * 거래대금 >= {MIN_TRADING_VALUE}억원
  * 금융업/지주사 제외

[전략 A - 마법공식]
- 선정 종목 수: {len(selected_a)}개
- 상위 10종목:
{selected_a.head(10)[['종목코드', '종목명', '마법공식_순위']].to_string() if '종목명' in selected_a.columns else selected_a.head(10).to_string()}

[전략 B - 멀티팩터]
- 선정 종목 수: {len(selected_b)}개
- 상위 10종목:
{selected_b.head(10)[['종목코드', '종목명', '멀티팩터_순위']].to_string() if '종목명' in selected_b.columns else selected_b.head(10).to_string()}

[공통 종목]
- 공통 선정: {len(common_tickers)}개
- 종목: {', '.join([f"{ticker_names.get(t, t)}({t})" for t in common_tickers])}

================================================================================
"""

        with open(OUTPUT_DIR / 'portfolio_2026_01_report.txt', 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"\n리포트 저장: {OUTPUT_DIR / 'portfolio_2026_01_report.txt'}")

    print("\n" + "=" * 80)
    print("포트폴리오 생성 완료!")
    print("=" * 80)


if __name__ == '__main__':
    main()
