"""
FnGuide Company Guide 재무제표 크롤링 모듈
기존 책의 코드를 기반으로 구현

TODO Task #9: 생존 편향 제거
- 과거 상장폐지 종목 DB 구축
- 상장폐지 시점의 손실 반영 (-100% 또는 최종 거래가)
- 데이터 소스: KRX 상장폐지 종목 리스트
- 구현 우선순위: 중간 (백테스트 정확도 향상)
"""

import pandas as pd
import numpy as np
import requests as rq
from bs4 import BeautifulSoup
import re
import time
from pathlib import Path
from tqdm import tqdm

# 데이터 캐싱 디렉토리
DATA_DIR = Path(__file__).parent / 'data_cache'
DATA_DIR.mkdir(exist_ok=True)


def clean_fs(df, ticker, frequency):
    """
    재무제표 데이터를 정규화하는 함수

    Parameters:
    - df: 원본 재무제표 데이터프레임
    - ticker: 종목 코드
    - frequency: 공시구분 ('y' for 연간, 'q' for 분기)

    Returns:
    - 정규화된 데이터프레임
    """
    # 모든 데이터가 NaN인 행 제거
    df = df[~df.loc[:, ~df.columns.isin(['계정'])].isna().all(axis=1)]

    # 계정명 중복 제거 (첫 번째 값만 유지)
    df = df.drop_duplicates(['계정'], keep='first')

    # Wide format을 Long format으로 변환
    df = pd.melt(df, id_vars='계정', var_name='기준일', value_name='값')

    # 값이 Null인 행 제거
    df = df[~pd.isnull(df['값'])]

    # '[+]' 버튼에 해당하는 '계산에 참여한 계정 펼치기' 텍스트 제거
    df['계정'] = df['계정'].replace({'계산에 참여한 계정 펼치기': ''}, regex=True)

    # 기준일을 월말 날짜로 변환
    df['기준일'] = pd.to_datetime(df['기준일'],
                               format='%Y/%m') + pd.tseries.offsets.MonthEnd()

    # 종목코드와 공시구분 추가
    df['종목코드'] = ticker
    df['공시구분'] = frequency

    return df


def get_financial_statement(ticker, use_cache=True, cache_max_age_days=7):
    """
    FnGuide에서 특정 종목의 재무제표 크롤링

    Args:
        ticker: 6자리 종목코드
        use_cache: 캐시 사용 여부
        cache_max_age_days: 캐시 유효 기간 (일). 이보다 오래된 캐시는 자동 갱신.

    Returns:
        dict: {'annual': 연간 데이터, 'quarter': 분기 데이터}
    """
    cache_file = DATA_DIR / f'fs_fnguide_{ticker}.parquet'

    if use_cache and cache_file.exists():
        import os
        from datetime import datetime, timedelta
        cache_age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(cache_file))
        if cache_age <= timedelta(days=cache_max_age_days):
            print(f"캐시에서 재무제표 로드: {ticker}")
            return pd.read_parquet(cache_file)
        else:
            print(f"캐시 만료 ({cache_age.days}일 경과), 재수집: {ticker}")

    # CACHE_ONLY 모드: 캐시 없으면 크롤링하지 않고 스킵
    if os.environ.get('FNGUIDE_CACHE_ONLY') == '1' and not cache_file.exists():
        print(f"종목 {ticker} 캐시 없음 — CACHE_ONLY 모드, 스킵")
        return pd.DataFrame()

    try:
        # URL 생성
        url = f'http://comp.fnguide.com/SVO2/ASP/SVD_Finance.asp?pGB=1&gicode=A{ticker}'

        # 데이터 받아오기 (HTML 테이블 파싱, 타임아웃 10초)
        import requests as _rq
        _resp = _rq.get(url, timeout=10)
        _resp.raise_for_status()
        data = pd.read_html(_resp.text, displayed_only=False, encoding='utf-8')

        # ========== 연간(Annual) 재무제표 처리 ==========
        # data[0]: 포괄손익계산서 (연간)
        # data[2]: 재무상태표 (연간)
        # data[4]: 현금흐름표 (연간)

        # '전년동기' 열 제외 후 세 테이블 병합
        data_fs_y = pd.concat([
            data[0].iloc[:, ~data[0].columns.str.contains('전년동기')],
            data[2],
            data[4]
        ])
        data_fs_y = data_fs_y.rename(columns={data_fs_y.columns[0]: "계정"})

        # 결산년(fiscal year) 찾기
        page_data = rq.get(url, timeout=10)
        page_data_html = BeautifulSoup(page_data.content, 'html.parser')

        fiscal_data = page_data_html.select('div.corp_group1 > h2')
        if len(fiscal_data) > 1:
            fiscal_data_text = fiscal_data[1].text
            fiscal_data_text = re.findall('[0-9]+', fiscal_data_text)

            # 결산년에 해당하는 계정만 남기기
            data_fs_y = data_fs_y.loc[:, (data_fs_y.columns == '계정') | (
                data_fs_y.columns.str[-2:].isin(fiscal_data_text))]

        # 연간 데이터 클렌징
        data_fs_y_clean = clean_fs(data_fs_y, ticker, 'y')

        # ========== 분기(Quarterly) 재무제표 처리 ==========
        # data[1]: 포괄손익계산서 (분기)
        # data[3]: 재무상태표 (분기)
        # data[5]: 현금흐름표 (분기)

        # '전년동기' 열 제외 후 세 테이블 병합
        data_fs_q = pd.concat([
            data[1].iloc[:, ~data[1].columns.str.contains('전년동기')],
            data[3],
            data[5]
        ])
        data_fs_q = data_fs_q.rename(columns={data_fs_q.columns[0]: "계정"})

        # 분기 데이터 클렌징
        data_fs_q_clean = clean_fs(data_fs_q, ticker, 'q')

        # 연간과 분기 데이터 통합
        data_fs_bind = pd.concat([data_fs_y_clean, data_fs_q_clean])

        # 캐시 저장
        data_fs_bind.to_parquet(cache_file)

        time.sleep(1)  # 크롤링 예의 (캐시 히트 시 건너뜀)

        return data_fs_bind

    except Exception as e:
        print(f"종목 {ticker} 재무제표 수집 실패: {e}")
        return pd.DataFrame()


def get_all_financial_statements(tickers, use_cache=True):
    """
    여러 종목의 재무제표 크롤링 (4스레드 병렬)

    Args:
        tickers: 종목 리스트
        use_cache: 캐시 사용 여부

    Returns:
        dict: {ticker: 재무제표 데이터프레임}
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    print(f"FnGuide에서 재무제표 수집 중 (총 {len(tickers)}개 종목, 4스레드)...")

    def _fetch_one(ticker):
        try:
            fs = get_financial_statement(ticker, use_cache=use_cache)
            return ticker, fs, None
        except Exception as e:
            return ticker, None, str(e)

    fs_data = {}
    error_list = []
    done = 0

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(_fetch_one, t): t for t in tickers}
        for future in as_completed(futures, timeout=600):
            try:
                ticker, fs, err = future.result(timeout=15)
            except Exception as e:
                ticker = futures[future]
                err = f"timeout: {e}"
                fs = None
            done += 1
            if err:
                error_list.append(ticker)
            elif fs is not None and not fs.empty:
                fs_data[ticker] = fs
            if done % 100 == 0:
                print(f"  재무제표 진행: {done}/{len(tickers)}")

    print(f"수집 완료: {len(fs_data)}개 성공, {len(error_list)}개 실패")
    if error_list:
        print(f"실패 종목: {error_list[:10]}...")

    return fs_data


def extract_magic_formula_data(fs_dict, base_date=None, use_ttm=True):
    """
    재무제표에서 마법공식 계산에 필요한 항목 추출

    필요 항목:
    - 당기순이익, 법인세비용, 이자비용
    - 자산, 부채, 유동부채, 유동자산, 비유동자산
    - 현금및현금성자산
    - 감가상각비

    Args:
        fs_dict: {ticker: 재무제표 데이터프레임}
        base_date: 기준일 (str, YYYYMMDD). None이면 최신 데이터 사용.
                   공시 시차 반영: 분기는 45일, 연간은 90일
        use_ttm: True면 TTM(최근 4분기 합산) 사용, False면 연간 데이터만 사용

    Returns:
        데이터프레임: 종목별 TTM 또는 연간 재무제표 항목
    """
    result_list = []

    # 손익계산서/현금흐름표 항목 (4분기 합산 대상)
    flow_accounts = [
        '당기순이익', '법인세비용', '세전계속사업이익',
        '매출액', '매출총이익', '영업이익',
        '영업활동으로인한현금흐름', '감가상각비'
    ]

    # 재무상태표 항목 (최근 분기 값 사용 - 스냅샷)
    stock_accounts = [
        '자산', '부채', '유동부채', '유동자산', '비유동자산',
        '현금및현금성자산', '자본'
    ]

    # 기준일 설정 (공시 시차 반영)
    if base_date:
        from datetime import datetime, timedelta
        base_dt = datetime.strptime(base_date, '%Y%m%d')
        # 분기 공시 시차: 45일, 연간 공시 시차: 90일
        cutoff_date_quarterly = base_dt - timedelta(days=45)
        cutoff_date_annual = base_dt - timedelta(days=90)
    else:
        cutoff_date_quarterly = None
        cutoff_date_annual = None

    for ticker, fs_df in fs_dict.items():
        if use_ttm:
            # TTM 방식: 분기 데이터 사용
            quarterly_data = fs_df[fs_df['공시구분'] == 'q'].copy()

            if quarterly_data.empty:
                # 분기 데이터 없으면 연간 데이터로 폴백
                annual_data = fs_df[fs_df['공시구분'] == 'y'].copy()
                if cutoff_date_annual:
                    annual_data = annual_data[annual_data['기준일'] <= cutoff_date_annual]
                if annual_data.empty:
                    continue
                latest_date = annual_data['기준일'].max()
                latest_data = annual_data[annual_data['기준일'] == latest_date]
                pivot_data = latest_data.pivot_table(
                    index='종목코드', columns='계정', values='값', aggfunc='first'
                )
                pivot_data['기준일'] = latest_date
                result_list.append(pivot_data)
                continue

            # 공시 시차 반영
            if cutoff_date_quarterly:
                quarterly_data = quarterly_data[quarterly_data['기준일'] <= cutoff_date_quarterly]

            if quarterly_data.empty:
                continue

            # 최근 4분기 찾기
            unique_dates = sorted(quarterly_data['기준일'].unique(), reverse=True)
            if len(unique_dates) < 4:
                # 4분기 미만이면 있는 만큼만 사용 (비율 조정)
                recent_dates = unique_dates
            else:
                recent_dates = unique_dates[:4]

            latest_date = recent_dates[0]  # 가장 최근 분기

            # 최근 4분기 데이터 추출
            ttm_data = quarterly_data[quarterly_data['기준일'].isin(recent_dates)]

            # 손익계산서/현금흐름표: 가중 TTM (최신분기 가중치 높음)
            # 가중치: 최신 40%, 2번째 30%, 3번째 20%, 4번째 10%
            # 합=4 스케일(1.6/1.2/0.8/0.4)로 기존 TTM 합산과 동일 스케일 유지
            # 4분기 미만 시 합이 4.0이 되도록 정규화
            base_weights = [1.6, 1.2, 0.8, 0.4]  # 최신→과거 순
            n_quarters = len(recent_dates)
            raw_weights = base_weights[:n_quarters]
            scale = 4.0 / sum(raw_weights)  # 합이 4.0이 되도록 정규화

            weight_map = {}
            for i, d in enumerate(sorted(recent_dates, reverse=True)):
                weight_map[d] = raw_weights[i] * scale if i < n_quarters else base_weights[-1]

            flow_data = ttm_data[ttm_data['계정'].isin(flow_accounts)].copy()
            flow_data['가중치'] = flow_data['기준일'].map(weight_map)
            flow_data['가중값'] = flow_data['값'] * flow_data['가중치']
            flow_sum = flow_data.groupby(['종목코드', '계정'])['가중값'].sum().reset_index()
            flow_sum = flow_sum.rename(columns={'가중값': '값'})
            flow_pivot = flow_sum.pivot_table(
                index='종목코드', columns='계정', values='값', aggfunc='first'
            )

            # 재무상태표: 최근 분기 값
            stock_data = ttm_data[
                (ttm_data['계정'].isin(stock_accounts)) &
                (ttm_data['기준일'] == latest_date)
            ]
            stock_pivot = stock_data.pivot_table(
                index='종목코드', columns='계정', values='값', aggfunc='first'
            )

            # 합치기
            if flow_pivot.empty and stock_pivot.empty:
                continue

            pivot_data = pd.concat([flow_pivot, stock_pivot], axis=1)
            pivot_data['기준일'] = latest_date
            result_list.append(pivot_data)

        else:
            # 기존 방식: 연간 데이터만 사용
            annual_data = fs_df[fs_df['공시구분'] == 'y'].copy()

            if annual_data.empty:
                continue

            if cutoff_date_annual:
                annual_data = annual_data[annual_data['기준일'] <= cutoff_date_annual]

            if annual_data.empty:
                continue

            latest_date = annual_data['기준일'].max()
            latest_data = annual_data[annual_data['기준일'] == latest_date]

            pivot_data = latest_data.pivot_table(
                index='종목코드', columns='계정', values='값', aggfunc='first'
            )

            pivot_data['기준일'] = latest_date
            result_list.append(pivot_data)

    if not result_list:
        return pd.DataFrame()

    # 전체 결합
    result_df = pd.concat(result_list)
    result_df = result_df.reset_index()

    # 주요 계정명 매핑 (FnGuide 실제 계정명 확인 완료)
    # ※ '이자비용'은 FnGuide에 없으므로 대안 사용
    account_mapping = {
        '당기순이익': '당기순이익',
        '세전계속사업이익': '세전계속사업이익',  # EBIT 계산용
        '법인세비용': '법인세비용',
        '자산': '자산',
        '부채': '총부채',  # '부채'를 '총부채'로 매핑
        '유동부채': '유동부채',
        '유동자산': '유동자산',
        '비유동자산': '비유동자산',
        '현금및현금성자산': '현금',
        '감가상각비': '감가상각비',
        '자본': '자본',
        '매출액': '매출액',
        '매출총이익': '매출총이익',
        '영업활동으로인한현금흐름': '영업현금흐름',
        '영업이익': '영업이익',
    }

    # 컬럼명 변경 (원본 계정명 → 간소화된 이름)
    rename_dict = {}
    for original_name, simple_name in account_mapping.items():
        if original_name in result_df.columns and original_name != simple_name:
            rename_dict[original_name] = simple_name

    if rename_dict:
        result_df = result_df.rename(columns=rename_dict)

    # 가능한 컬럼만 선택
    available_cols = ['종목코드', '기준일']
    for simple_name in account_mapping.values():
        if simple_name in result_df.columns:
            available_cols.append(simple_name)

    result_df = result_df[[col for col in available_cols if col in result_df.columns]]

    return result_df


def extract_revenue_growth(fs_dict, base_date=None):
    """
    재무제표에서 매출성장률(YoY) 추출

    연간 매출액 2개년 비교:
      매출성장률 = (최근매출액 - 전기매출액) / |전기매출액| × 100

    Args:
        fs_dict: {ticker: 재무제표 데이터프레임}
        base_date: 기준일 (str, YYYYMMDD)

    Returns:
        DataFrame: 종목코드, 매출성장률
    """
    if base_date:
        from datetime import datetime, timedelta
        base_dt = datetime.strptime(base_date, '%Y%m%d')
        cutoff_date = base_dt - timedelta(days=90)  # 연간 공시 시차
    else:
        cutoff_date = None

    results = []

    for ticker, fs_df in fs_dict.items():
        annual = fs_df[(fs_df['공시구분'] == 'y') & (fs_df['계정'] == '매출액')].copy()

        if cutoff_date is not None:
            annual = annual[annual['기준일'] <= cutoff_date]

        if len(annual) < 2:
            continue

        annual = annual.sort_values('기준일', ascending=False)
        latest_rev = annual.iloc[0]['값']
        prior_rev = annual.iloc[1]['값']

        if pd.isna(prior_rev) or prior_rev == 0:
            continue

        yoy = (latest_rev - prior_rev) / abs(prior_rev) * 100
        results.append({'종목코드': ticker, '매출성장률': yoy})

    if not results:
        return pd.DataFrame(columns=['종목코드', '매출성장률'])

    df = pd.DataFrame(results)
    valid = df['매출성장률'].notna().sum()
    print(f"매출성장률(YoY) 계산: {valid}/{len(fs_dict)}개 종목 (연간 매출액 2개년 비교)")
    return df


# ============================================================================
# 컨센서스 데이터 크롤링 (Forward EPS/PER)
# ============================================================================

def get_consensus_data(ticker):
    """
    FnGuide 메인 페이지에서 컨센서스 데이터 추출

    URL: comp.fnguide.com/SVO2/ASP/SVD_Main.asp?gicode=A{ticker}
    테이블: 투자의견 / 컨센서스 요약

    Returns:
        dict: forward_eps, forward_per, analyst_count, target_price 등
    """
    result = {
        'ticker': ticker,
        'forward_eps': None,
        'forward_per': None,
        'analyst_count': None,
        'target_price': None,
        'has_consensus': False,
    }

    try:
        url = f'http://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?pGB=1&gicode=A{ticker}'

        # HTML 테이블 파싱 (timeout 적용)
        import requests as _rq2
        _resp2 = _rq2.get(url, timeout=10)
        _resp2.raise_for_status()
        tables = pd.read_html(_resp2.text, displayed_only=False, encoding='utf-8')

        # 컨센서스 테이블 찾기 (보통 인덱스 7~10 사이)
        for i, tbl in enumerate(tables):
            tbl_str = str(tbl.columns.tolist()) + str(tbl.values.tolist())

            # EPS, PER 컬럼이 있는 테이블 찾기
            if 'EPS' in tbl_str and 'PER' in tbl_str:
                # EPS 추출
                if 'EPS' in tbl.columns:
                    try:
                        eps_val = tbl['EPS'].iloc[0]
                        eps_str = str(eps_val).replace(',', '').replace('원', '').strip()
                        if eps_str and eps_str not in ['nan', '-', '']:
                            result['forward_eps'] = float(eps_str)
                            result['has_consensus'] = True
                    except Exception:
                        pass

                # PER 추출
                if 'PER' in tbl.columns:
                    try:
                        per_val = tbl['PER'].iloc[0]
                        per_str = str(per_val).replace('배', '').strip()
                        if per_str and per_str not in ['nan', '-', '']:
                            result['forward_per'] = float(per_str)
                    except Exception:
                        pass

                # 목표주가 추출
                for col in tbl.columns:
                    if '목표' in str(col):
                        try:
                            target_val = tbl[col].iloc[0]
                            target_str = str(target_val).replace(',', '').replace('원', '').strip()
                            if target_str and target_str not in ['nan', '-', '']:
                                result['target_price'] = float(target_str)
                        except Exception:
                            pass
                        break

                break

        # 애널리스트 수 추출 시도
        if result['has_consensus'] and result['analyst_count'] is None:
            result['analyst_count'] = 1  # 기본값

    except Exception as e:
        pass

    return result


def get_consensus_batch(tickers, delay=1.0):
    """
    여러 종목의 컨센서스 데이터 일괄 수집 (4스레드 병렬)

    Args:
        tickers: 종목코드 리스트
        delay: 요청 간 딜레이 (초, 스레드별 적용)

    Returns:
        pd.DataFrame: 컨센서스 데이터
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _fetch_one(ticker):
        try:
            data = get_consensus_data(ticker)
            time.sleep(delay)
            return data
        except Exception:
            return {'ticker': ticker, 'has_consensus': False}

    print(f"\n📊 컨센서스 데이터 수집 중... ({len(tickers)}개 종목, 4스레드)")

    results_map = {}
    done = 0

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(_fetch_one, t): t for t in tickers}
        for future in as_completed(futures, timeout=600):
            ticker = futures[future]
            results_map[ticker] = future.result(timeout=15)
            done += 1
            if done % 40 == 0:
                print(f"   {done}/{len(tickers)} 완료...")

    # 원래 순서 유지
    results = [results_map[t] for t in tickers]
    df = pd.DataFrame(results)

    # 커버리지 통계
    coverage = df['has_consensus'].sum()
    print(f"\n✅ 컨센서스 커버리지: {coverage}/{len(tickers)} ({coverage/len(tickers)*100:.1f}%)")

    return df


# ============================================================================
# 메인 테스트
# ============================================================================

if __name__ == '__main__':
    # 테스트
    print("FnGuide 크롤러 테스트")

    # 삼성전자 재무제표 수집
    test_ticker = '005930'
    print(f"\n{test_ticker} 재무제표 수집 중...")

    fs_data = get_financial_statement(test_ticker, use_cache=False)

    if not fs_data.empty:
        print(f"\n수집된 데이터 크기: {fs_data.shape}")
        print(f"\n계정 목록 (일부):")
        print(fs_data['계정'].unique()[:20])

        print(f"\n최근 연간 데이터:")
        annual_latest = fs_data[(fs_data['공시구분'] == 'y') &
                               (fs_data['기준일'] == fs_data['기준일'].max())]
        print(annual_latest.head(20))

        # 마법공식 데이터 추출 테스트
        print(f"\n마법공식 데이터 추출 테스트:")
        magic_data = extract_magic_formula_data({test_ticker: fs_data})
        print(magic_data)

    # 컨센서스 데이터 테스트
    print(f"\n\n{'='*70}")
    print("컨센서스 데이터 테스트")
    print('='*70)

    test_tickers = ['005930', '018290', '419530']  # 삼성전자, 브이티, SAMG엔터

    for ticker in test_tickers:
        consensus = get_consensus_data(ticker)
        print(f"\n{ticker}:")
        print(f"  Forward EPS: {consensus.get('forward_eps')}")
        print(f"  Forward PER: {consensus.get('forward_per')}")
        print(f"  목표주가: {consensus.get('target_price')}")
        print(f"  커버리지: {consensus.get('has_consensus')}")
        time.sleep(1)
