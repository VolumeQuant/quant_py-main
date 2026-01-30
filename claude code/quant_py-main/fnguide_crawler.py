"""
FnGuide Company Guide 재무제표 크롤링 모듈
기존 책의 코드를 기반으로 구현

TODO Task #8: DART API 통합
- FnGuide 크롤링을 DART Open API로 대체
- 법적 리스크 제거 및 안정성 향상
- API 키 발급: https://opendart.fss.or.kr/
- 재무제표 API: /api/fnlttSinglAcntAll.json
- 구현 우선순위: 높음

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


def get_financial_statement(ticker, use_cache=True):
    """
    FnGuide에서 특정 종목의 재무제표 크롤링

    Args:
        ticker: 6자리 종목코드
        use_cache: 캐시 사용 여부

    Returns:
        dict: {'annual': 연간 데이터, 'quarter': 분기 데이터}
    """
    cache_file = DATA_DIR / f'fs_fnguide_{ticker}.parquet'

    if use_cache and cache_file.exists():
        print(f"캐시에서 재무제표 로드: {ticker}")
        return pd.read_parquet(cache_file)

    try:
        # URL 생성
        url = f'http://comp.fnguide.com/SVO2/ASP/SVD_Finance.asp?pGB=1&gicode=A{ticker}'

        # 데이터 받아오기 (HTML 테이블 파싱)
        data = pd.read_html(url, displayed_only=False, encoding='utf-8')

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
        page_data = rq.get(url)
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

        time.sleep(2)  # 크롤링 예의

        return data_fs_bind

    except Exception as e:
        print(f"종목 {ticker} 재무제표 수집 실패: {e}")
        return pd.DataFrame()


def get_all_financial_statements(tickers, use_cache=True):
    """
    여러 종목의 재무제표 크롤링

    Args:
        tickers: 종목 리스트
        use_cache: 캐시 사용 여부

    Returns:
        dict: {ticker: 재무제표 데이터프레임}
    """
    print(f"FnGuide에서 재무제표 수집 중 (총 {len(tickers)}개 종목)...")

    fs_data = {}
    error_list = []

    for ticker in tqdm(tickers):
        try:
            fs = get_financial_statement(ticker, use_cache=use_cache)
            if not fs.empty:
                fs_data[ticker] = fs
        except Exception as e:
            print(f"\n종목 {ticker} 실패: {e}")
            error_list.append(ticker)
            continue

    print(f"\n수집 완료: {len(fs_data)}개 성공, {len(error_list)}개 실패")
    if error_list:
        print(f"실패 종목: {error_list[:10]}...")

    return fs_data


def extract_magic_formula_data(fs_dict, base_date=None):
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
                   공시 시차 반영: base_date - 3개월 이전 재무제표만 사용

    Returns:
        데이터프레임: 종목별 최근 연간 재무제표 항목
    """
    result_list = []

    # 기준일 설정 (공시 시차 3개월 반영)
    if base_date:
        from datetime import datetime, timedelta
        base_dt = datetime.strptime(base_date, '%Y%m%d')
        # 3개월 전
        cutoff_date = base_dt - timedelta(days=90)
    else:
        cutoff_date = None

    for ticker, fs_df in fs_dict.items():
        # 연간 데이터만 추출
        annual_data = fs_df[fs_df['공시구분'] == 'y'].copy()

        if annual_data.empty:
            continue

        # 공시 시차 반영: cutoff_date 이전 데이터만 사용
        if cutoff_date:
            annual_data = annual_data[annual_data['기준일'] <= cutoff_date]

        if annual_data.empty:
            continue

        # 최근 기준일 찾기
        latest_date = annual_data['기준일'].max()
        latest_data = annual_data[annual_data['기준일'] == latest_date]

        # 피벗: 계정을 컬럼으로
        pivot_data = latest_data.pivot_table(
            index='종목코드',
            columns='계정',
            values='값',
            aggfunc='first'
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
        '법인세차감전순이익': '법인세차감전순이익',  # EBIT 계산용
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
