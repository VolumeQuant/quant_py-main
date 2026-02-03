"""
전략 C: Forward EPS 하이브리드 전략 (Korea Hybrid Strategy v2.0)

성장성(Forward EPS 상향) + 안전성(부채비율, 이자보상배율) + 가치(Forward PER) 결합

필터 조건:
- Growth Filter: Forward EPS 상향 추세 (컨센서스 리비전)
- Safety Filter: 부채비율 < 200%, 이자보상배율 > 1
- Value Filter: Forward PER < 20
- Ranking: 섹터 내 상대평가 (Z-Score) + 수급

데이터 소스: FnGuide 컨센서스 (comp.fnguide.com)
"""

import pandas as pd
import numpy as np
from pykrx import stock
from datetime import datetime, timedelta
from pathlib import Path
import time
import warnings

warnings.filterwarnings('ignore')

# ============================================================================
# 설정
# ============================================================================

DATA_DIR = Path(__file__).parent / 'data_cache'
DATA_DIR.mkdir(exist_ok=True)

# 필터 기준
DEBT_RATIO_MAX = 200          # 부채비율 < 200%
INTEREST_COVERAGE_MIN = 1.0   # 이자보상배율 > 1
FORWARD_PER_MAX = 20          # Forward PER < 20
MIN_ANALYST_COUNT = 2         # 최소 애널리스트 수

# 팩터 가중치
GROWTH_WEIGHT = 0.40          # 성장성 (EPS 수정률)
SAFETY_WEIGHT = 0.25          # 안전성 (부채비율, 이자보상배율)
VALUE_WEIGHT = 0.20           # 가치 (Forward PER)
MOMENTUM_WEIGHT = 0.15        # 모멘텀 (가격 추세)


# ============================================================================
# 컨센서스 데이터 크롤링
# ============================================================================

def get_consensus_data(ticker):
    """
    FnGuide 메인 페이지에서 컨센서스 데이터 추출

    URL: comp.fnguide.com/SVO2/ASP/SVD_Main.asp?gicode=A{ticker}
    테이블 7: 투자의견 / 컨센서스 요약

    Returns:
        dict: forward_eps, forward_per, analyst_count, target_price, eps_growth 등
    """
    import requests

    result = {
        'ticker': ticker,
        'forward_eps': None,
        'forward_per': None,
        'analyst_count': None,
        'target_price': None,
        'target_upside': None,
        'eps_yoy_growth': None,
        'has_consensus': False,
    }

    try:
        url = f'http://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?pGB=1&gicode=A{ticker}'

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        # HTML 테이블 파싱
        tables = pd.read_html(url, displayed_only=False, encoding='utf-8')

        # 테이블 7: 컨센서스 요약 (인덱스는 0부터 시작하므로 tables[7])
        if len(tables) > 7:
            consensus_df = tables[7]

            # EPS 추출
            if 'EPS' in consensus_df.columns:
                try:
                    eps_str = str(consensus_df['EPS'].iloc[0])
                    eps_str = eps_str.replace(',', '').replace('원', '').strip()
                    if eps_str and eps_str != 'nan' and eps_str != '-':
                        result['forward_eps'] = float(eps_str)
                        result['has_consensus'] = True
                except:
                    pass

            # PER 추출
            if 'PER' in consensus_df.columns:
                try:
                    per_str = str(consensus_df['PER'].iloc[0])
                    per_str = per_str.replace('배', '').strip()
                    if per_str and per_str != 'nan' and per_str != '-':
                        result['forward_per'] = float(per_str)
                except:
                    pass

            # 목표주가 추출
            for col in consensus_df.columns:
                if '목표' in str(col) or 'Target' in str(col):
                    try:
                        target_str = str(consensus_df[col].iloc[0])
                        target_str = target_str.replace(',', '').replace('원', '').strip()
                        if target_str and target_str != 'nan' and target_str != '-':
                            result['target_price'] = float(target_str)
                    except:
                        pass
                    break

        # 애널리스트 수 추출 (다른 테이블에서)
        for tbl in tables:
            if '애널리스트' in str(tbl.columns) or '커버리지' in str(tbl.values):
                for col in tbl.columns:
                    if '애널' in str(col) or 'Analyst' in str(col):
                        try:
                            count_val = tbl[col].iloc[0]
                            if pd.notna(count_val):
                                result['analyst_count'] = int(float(str(count_val).replace('명', '')))
                        except:
                            pass
                        break

        # 기본 애널리스트 수 (커버리지 있으면 최소 1명)
        if result['has_consensus'] and result['analyst_count'] is None:
            result['analyst_count'] = 1

    except Exception as e:
        pass

    return result


def get_consensus_batch(tickers, delay=1.0):
    """
    여러 종목의 컨센서스 데이터 일괄 수집

    Args:
        tickers: 종목코드 리스트
        delay: 요청 간 딜레이 (초)

    Returns:
        pd.DataFrame: 컨센서스 데이터
    """
    results = []

    print(f"\n📊 컨센서스 데이터 수집 중... ({len(tickers)}개 종목)")

    for i, ticker in enumerate(tickers):
        try:
            data = get_consensus_data(ticker)
            results.append(data)

            if (i + 1) % 20 == 0:
                print(f"   {i + 1}/{len(tickers)} 완료...")

            time.sleep(delay)

        except Exception as e:
            print(f"   ⚠️ {ticker} 실패: {e}")
            results.append({'ticker': ticker, 'has_consensus': False})

    df = pd.DataFrame(results)

    # 커버리지 통계
    coverage = df['has_consensus'].sum()
    print(f"\n✅ 컨센서스 커버리지: {coverage}/{len(tickers)} ({coverage/len(tickers)*100:.1f}%)")

    return df


# ============================================================================
# 재무 데이터 로드 (FnGuide 캐시 활용)
# ============================================================================

def load_financial_data(ticker):
    """
    FnGuide 재무제표 캐시에서 데이터 로드

    Returns:
        dict: 부채비율, 이자보상배율, 영업이익 등
    """
    cache_file = DATA_DIR / f'fs_fnguide_{ticker}.parquet'

    result = {
        'ticker': ticker,
        'debt_ratio': None,
        'interest_coverage': None,
        'operating_income': None,
        'net_income': None,
        'equity': None,
        'has_financials': False,
    }

    if not cache_file.exists():
        return result

    try:
        df = pd.read_parquet(cache_file)

        # 최신 분기 데이터 사용
        if df.empty:
            return result

        latest = df.iloc[-1] if len(df) > 0 else None
        if latest is None:
            return result

        # 부채비율 = 부채 / 자본 * 100
        total_debt = latest.get('부채', latest.get('총부채', 0))
        equity = latest.get('자본', latest.get('자기자본', 0))

        if equity and equity > 0:
            result['debt_ratio'] = (total_debt / equity) * 100
            result['equity'] = equity

        # 이자보상배율 = 영업이익 / 이자비용
        operating_income = latest.get('영업이익', 0)
        interest_expense = latest.get('이자비용', latest.get('금융비용', 0))

        result['operating_income'] = operating_income

        if interest_expense and interest_expense > 0:
            result['interest_coverage'] = operating_income / interest_expense
        elif interest_expense == 0:
            result['interest_coverage'] = 999  # 무차입

        # 당기순이익
        result['net_income'] = latest.get('당기순이익', latest.get('지배주주순이익', 0))

        result['has_financials'] = True

    except Exception as e:
        pass

    return result


def load_financials_batch(tickers):
    """여러 종목의 재무 데이터 일괄 로드"""
    results = []

    for ticker in tickers:
        data = load_financial_data(ticker)
        results.append(data)

    return pd.DataFrame(results)


# ============================================================================
# 가격 모멘텀 계산
# ============================================================================

def calculate_momentum(ticker, days=60):
    """
    가격 모멘텀 계산 (최근 N일 수익률)

    Args:
        ticker: 종목코드
        days: 모멘텀 기간 (일)

    Returns:
        float: 모멘텀 (%)
    """
    try:
        end_date = datetime.now().strftime('%Y%m%d')
        start_date = (datetime.now() - timedelta(days=days + 30)).strftime('%Y%m%d')

        ohlcv = stock.get_market_ohlcv(start_date, end_date, ticker)

        if len(ohlcv) < days:
            return None

        current_price = ohlcv['종가'].iloc[-1]
        past_price = ohlcv['종가'].iloc[-days]

        momentum = ((current_price - past_price) / past_price) * 100

        return momentum

    except:
        return None


# ============================================================================
# 팩터 점수 계산
# ============================================================================

def calculate_zscore(series):
    """Z-Score 계산 (평균=0, 표준편차=1)"""
    mean = series.mean()
    std = series.std()
    if std == 0:
        return pd.Series([0] * len(series), index=series.index)
    return (series - mean) / std


def calculate_growth_score(df):
    """
    성장성 점수 계산

    - Forward EPS가 있는 종목: EPS 기반 점수
    - Forward EPS YoY 성장률 (Forward EPS / 전년 실적 EPS)
    """
    scores = pd.Series(index=df.index, dtype=float)

    # Forward EPS가 있는 종목
    has_eps = df['forward_eps'].notna() & (df['forward_eps'] > 0)

    if has_eps.sum() > 2:
        # EPS 절대값의 Z-Score (높을수록 좋음)
        eps_zscore = calculate_zscore(df.loc[has_eps, 'forward_eps'])
        scores.loc[has_eps] = eps_zscore

    # Forward EPS가 없는 종목은 0점
    scores.fillna(0, inplace=True)

    return scores


def calculate_safety_score(df):
    """
    안전성 점수 계산

    - 부채비율 역수 (낮을수록 좋음)
    - 이자보상배율 (높을수록 좋음)
    """
    scores = pd.Series(0, index=df.index, dtype=float)

    # 부채비율 점수 (역수 사용, 낮을수록 높은 점수)
    has_debt = df['debt_ratio'].notna() & (df['debt_ratio'] > 0)
    if has_debt.sum() > 2:
        # 부채비율 역수의 Z-Score
        debt_inv = 1 / (df.loc[has_debt, 'debt_ratio'] / 100 + 0.1)
        debt_zscore = calculate_zscore(debt_inv)
        scores.loc[has_debt] += debt_zscore * 0.5

    # 이자보상배율 점수
    has_ic = df['interest_coverage'].notna() & (df['interest_coverage'] > 0)
    if has_ic.sum() > 2:
        # 상한 클리핑 (999는 무차입)
        ic_clipped = df.loc[has_ic, 'interest_coverage'].clip(upper=20)
        ic_zscore = calculate_zscore(ic_clipped)
        scores.loc[has_ic] += ic_zscore * 0.5

    return scores


def calculate_value_score(df):
    """
    가치 점수 계산

    - Forward PER 역수 (낮을수록 좋음)
    """
    scores = pd.Series(0, index=df.index, dtype=float)

    has_per = df['forward_per'].notna() & (df['forward_per'] > 0)
    if has_per.sum() > 2:
        # PER 역수의 Z-Score
        per_inv = 1 / df.loc[has_per, 'forward_per']
        per_zscore = calculate_zscore(per_inv)
        scores.loc[has_per] = per_zscore

    return scores


def calculate_momentum_score(df):
    """
    모멘텀 점수 계산

    - 60일 가격 모멘텀
    """
    scores = pd.Series(0, index=df.index, dtype=float)

    has_mom = df['momentum_60d'].notna()
    if has_mom.sum() > 2:
        # 모멘텀 클리핑 (-50% ~ +100%)
        mom_clipped = df.loc[has_mom, 'momentum_60d'].clip(-50, 100)
        mom_zscore = calculate_zscore(mom_clipped)
        scores.loc[has_mom] = mom_zscore

    return scores


# ============================================================================
# 전략 실행
# ============================================================================

def run_strategy_c(universe_df=None, base_date=None):
    """
    전략 C 실행: Forward EPS 하이브리드

    Args:
        universe_df: 유니버스 DataFrame (없으면 자동 생성)
        base_date: 기준일 (없으면 최근 거래일)

    Returns:
        pd.DataFrame: 최종 포트폴리오 (상위 30개)
    """
    print("=" * 70)
    print("📊 전략 C: Forward EPS 하이브리드")
    print("=" * 70)

    # 1. 기준일 설정
    if base_date is None:
        today = datetime.now()
        for i in range(10):
            check_date = (today - timedelta(days=i)).strftime('%Y%m%d')
            try:
                test_df = stock.get_market_ohlcv(check_date, check_date, "005930")
                if not test_df.empty:
                    base_date = check_date
                    break
            except:
                continue

    print(f"\n📅 기준일: {base_date}")

    # 2. 유니버스 구성
    if universe_df is None:
        print("\n📋 유니버스 구성 중...")

        # KOSPI + KOSDAQ 시가총액 상위 종목
        kospi_tickers = stock.get_market_ticker_list(base_date, market="KOSPI")
        kosdaq_tickers = stock.get_market_ticker_list(base_date, market="KOSDAQ")

        all_tickers = kospi_tickers + kosdaq_tickers

        # 시가총액 조회
        mcap_data = []
        for ticker in all_tickers:
            try:
                mcap_df = stock.get_market_cap(base_date, base_date, ticker)
                if not mcap_df.empty:
                    mcap_data.append({
                        'ticker': ticker,
                        'market_cap': mcap_df['시가총액'].iloc[0] / 100_000_000,  # 억원
                    })
            except:
                continue

        universe_df = pd.DataFrame(mcap_data)

        # 시가총액 500억 이상 필터
        universe_df = universe_df[universe_df['market_cap'] >= 500]

        # 시가총액 상위 200개로 제한 (컨센서스 커버리지 고려)
        universe_df = universe_df.nlargest(200, 'market_cap')

        print(f"   유니버스: {len(universe_df)}개 종목")

    tickers = universe_df['ticker'].tolist()

    # 3. 컨센서스 데이터 수집
    consensus_df = get_consensus_batch(tickers, delay=0.5)

    # 4. 재무 데이터 로드
    print("\n📈 재무 데이터 로드 중...")
    financials_df = load_financials_batch(tickers)

    # 5. 데이터 병합
    df = universe_df.merge(consensus_df, on='ticker', how='left')
    df = df.merge(financials_df, on='ticker', how='left')

    print(f"\n📊 데이터 병합 완료: {len(df)}개 종목")

    # 6. 필터 적용
    print("\n🔍 필터 적용 중...")
    initial_count = len(df)

    # 컨센서스 있는 종목만
    df = df[df['has_consensus'] == True]
    print(f"   컨센서스 보유: {len(df)}개")

    # 부채비율 필터
    df = df[(df['debt_ratio'].isna()) | (df['debt_ratio'] < DEBT_RATIO_MAX)]
    print(f"   부채비율 < {DEBT_RATIO_MAX}%: {len(df)}개")

    # 이자보상배율 필터
    df = df[(df['interest_coverage'].isna()) | (df['interest_coverage'] > INTEREST_COVERAGE_MIN)]
    print(f"   이자보상배율 > {INTEREST_COVERAGE_MIN}: {len(df)}개")

    # Forward PER 필터
    df = df[(df['forward_per'].isna()) | (df['forward_per'] < FORWARD_PER_MAX)]
    print(f"   Forward PER < {FORWARD_PER_MAX}: {len(df)}개")

    # Forward EPS 양수
    df = df[(df['forward_eps'].isna()) | (df['forward_eps'] > 0)]
    print(f"   Forward EPS > 0: {len(df)}개")

    if len(df) < 10:
        print(f"\n⚠️ 필터 후 종목 수가 너무 적습니다 ({len(df)}개). 필터 완화...")
        # 필터 완화: Forward PER만 적용
        df = universe_df.merge(consensus_df, on='ticker', how='left')
        df = df.merge(financials_df, on='ticker', how='left')
        df = df[df['has_consensus'] == True]
        df = df[(df['forward_per'].isna()) | (df['forward_per'] < FORWARD_PER_MAX * 1.5)]
        print(f"   완화 후: {len(df)}개")

    # 7. 모멘텀 계산
    print("\n📈 모멘텀 계산 중...")
    momentums = []
    for ticker in df['ticker'].tolist():
        mom = calculate_momentum(ticker, days=60)
        momentums.append(mom)
        time.sleep(0.02)

    df['momentum_60d'] = momentums

    # 8. 팩터 점수 계산
    print("\n📊 팩터 점수 계산 중...")

    df['growth_score'] = calculate_growth_score(df)
    df['safety_score'] = calculate_safety_score(df)
    df['value_score'] = calculate_value_score(df)
    df['momentum_score'] = calculate_momentum_score(df)

    # 9. 종합 점수 계산
    df['hybrid_score'] = (
        df['growth_score'] * GROWTH_WEIGHT +
        df['safety_score'] * SAFETY_WEIGHT +
        df['value_score'] * VALUE_WEIGHT +
        df['momentum_score'] * MOMENTUM_WEIGHT
    )

    # 10. 상위 30개 선정
    df = df.sort_values('hybrid_score', ascending=False)
    portfolio = df.head(30).copy()

    # 종목명 조회
    names = []
    for ticker in portfolio['ticker']:
        try:
            name = stock.get_market_ticker_name(ticker)
            names.append(name)
        except:
            names.append('')

    portfolio['종목명'] = names

    print(f"\n✅ 포트폴리오 선정 완료: {len(portfolio)}개 종목")

    return portfolio


# ============================================================================
# 결과 저장
# ============================================================================

def save_portfolio(portfolio, base_date=None):
    """포트폴리오 저장"""

    if base_date is None:
        base_date = datetime.now().strftime('%Y%m%d')

    output_dir = Path(__file__).parent / 'output'
    output_dir.mkdir(exist_ok=True)

    # CSV 저장
    year_month = base_date[:4] + '_' + base_date[4:6]
    csv_file = output_dir / f'portfolio_{year_month}_strategy_c.csv'

    save_cols = ['ticker', '종목명', 'market_cap', 'forward_eps', 'forward_per',
                 'debt_ratio', 'interest_coverage', 'momentum_60d',
                 'growth_score', 'safety_score', 'value_score', 'momentum_score',
                 'hybrid_score']

    df_save = portfolio[[c for c in save_cols if c in portfolio.columns]].copy()
    df_save.columns = ['종목코드', '종목명', '시가총액', 'Forward_EPS', 'Forward_PER',
                       '부채비율', '이자보상배율', '60일모멘텀',
                       '성장점수', '안전점수', '가치점수', '모멘텀점수',
                       '하이브리드_점수'][:len(df_save.columns)]

    df_save.to_csv(csv_file, index=False, encoding='utf-8-sig')

    # 텍스트 리포트
    txt_file = output_dir / f'portfolio_{year_month}_strategy_c_report.txt'

    with open(txt_file, 'w', encoding='utf-8') as f:
        f.write("=" * 70 + "\n")
        f.write("전략 C: Forward EPS 하이브리드 포트폴리오\n")
        f.write(f"기준일: {base_date}\n")
        f.write(f"생성: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 70 + "\n\n")

        f.write("📊 전략 개요\n")
        f.write("-" * 70 + "\n")
        f.write(f"• 성장성 (Forward EPS): {GROWTH_WEIGHT*100:.0f}%\n")
        f.write(f"• 안전성 (부채비율, 이자보상배율): {SAFETY_WEIGHT*100:.0f}%\n")
        f.write(f"• 가치 (Forward PER): {VALUE_WEIGHT*100:.0f}%\n")
        f.write(f"• 모멘텀 (60일 수익률): {MOMENTUM_WEIGHT*100:.0f}%\n\n")

        f.write("📋 필터 조건\n")
        f.write("-" * 70 + "\n")
        f.write(f"• 부채비율 < {DEBT_RATIO_MAX}%\n")
        f.write(f"• 이자보상배율 > {INTEREST_COVERAGE_MIN}\n")
        f.write(f"• Forward PER < {FORWARD_PER_MAX}\n")
        f.write(f"• Forward EPS > 0 (흑자 예상)\n\n")

        f.write("🏆 포트폴리오 (상위 30개)\n")
        f.write("-" * 70 + "\n")

        for i, (_, row) in enumerate(portfolio.head(30).iterrows(), 1):
            name = row.get('종목명', '')
            ticker = row.get('ticker', '')
            f_eps = row.get('forward_eps', 0)
            f_per = row.get('forward_per', 0)
            score = row.get('hybrid_score', 0)

            f.write(f"{i:2d}. {name} ({ticker})\n")
            f.write(f"    Forward EPS: {f_eps:,.0f}원 | Forward PER: {f_per:.1f}배\n")
            f.write(f"    하이브리드 점수: {score:.3f}\n\n")

        f.write("\n" + "=" * 70 + "\n")

    print(f"\n📁 저장 완료:")
    print(f"   - {csv_file}")
    print(f"   - {txt_file}")

    return csv_file, txt_file


# ============================================================================
# 메인 실행
# ============================================================================

def main():
    """메인 실행 함수"""
    try:
        # 전략 실행
        portfolio = run_strategy_c()

        if portfolio is not None and len(portfolio) > 0:
            # 결과 저장
            save_portfolio(portfolio)

            # 상위 10개 출력
            print("\n" + "=" * 70)
            print("🏆 TOP 10 종목")
            print("=" * 70)

            for i, (_, row) in enumerate(portfolio.head(10).iterrows(), 1):
                name = row.get('종목명', '')
                ticker = row.get('ticker', '')
                f_per = row.get('forward_per', 0)
                score = row.get('hybrid_score', 0)

                print(f"{i:2d}. {name} ({ticker})")
                print(f"    Forward PER: {f_per:.1f}배 | 점수: {score:.3f}")

            print("\n✅ 전략 C 실행 완료!")

        else:
            print("\n❌ 포트폴리오 생성 실패")

    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
