"""
FnGuide 컨센서스 데이터 크롤링 테스트
Forward EPS, Forward PER 수집 가능 여부 확인
"""

import pandas as pd
import requests as rq
from bs4 import BeautifulSoup
import time
import warnings
warnings.filterwarnings('ignore')


def get_consensus_data(ticker):
    """
    FnGuide 메인 페이지에서 컨센서스 데이터 추출
    """
    url = f'http://comp.fnguide.com/SVO2/ASP/SVD_Main.asp?pGB=1&gicode=A{ticker}'

    try:
        # HTML 테이블 파싱
        tables = pd.read_html(url, displayed_only=False, encoding='utf-8')

        print(f"\n[{ticker}] 테이블 수: {len(tables)}")

        result = {
            '종목코드': ticker,
            'forward_eps': None,
            'forward_per': None,
            'analyst_count': None,
            'target_price': None,
        }

        # 테이블 7: 투자의견 / 컨센서스 요약
        if len(tables) > 7:
            consensus_summary = tables[7]
            print(f"\n[컨센서스 요약 테이블]")
            print(consensus_summary)

            # EPS, PER 추출
            if 'EPS' in consensus_summary.columns:
                result['forward_eps'] = consensus_summary['EPS'].iloc[0]
            if 'PER' in consensus_summary.columns:
                result['forward_per'] = consensus_summary['PER'].iloc[0]

        # 테이블 8-10: 연간 추정치 (매출, 영업이익, 순이익 등)
        for i in range(8, min(12, len(tables))):
            table = tables[i]
            table_str = str(table.columns.tolist()) + str(table.values.tolist())

            # 연간 추정치 테이블 찾기
            if '2024' in table_str or '2025' in table_str or '2026' in table_str:
                if len(table) <= 10 and len(table.columns) >= 3:
                    print(f"\n[테이블 {i} - 추정치]")
                    print(table)

        return result

    except Exception as e:
        print(f"[{ticker}] 크롤링 실패: {type(e).__name__}: {str(e)[:100]}")
        return None


def get_consensus_detail(ticker):
    """
    FnGuide Consensus 상세 페이지 크롤링
    """
    # 컨센서스 상세 페이지 URL
    url = f'http://comp.fnguide.com/SVO2/ASP/SVD_Consensus.asp?pGB=1&gicode=A{ticker}'

    try:
        tables = pd.read_html(url, displayed_only=False, encoding='utf-8')
        print(f"\n[{ticker}] 컨센서스 상세 페이지 테이블 수: {len(tables)}")

        for i, table in enumerate(tables[:5]):
            print(f"\n[테이블 {i}]")
            print(table)

        return tables

    except Exception as e:
        print(f"컨센서스 상세 페이지 실패: {e}")
        return None


if __name__ == '__main__':
    print("="*60)
    print("FnGuide 컨센서스 데이터 크롤링 테스트")
    print("="*60)

    # 테스트 종목
    test_tickers = [
        ('005930', '삼성전자', '대형'),
        ('018290', '브이티', '중형'),
        ('419530', 'SAMG엔터', '소형'),
    ]

    for ticker, name, size in test_tickers:
        print(f"\n{'='*60}")
        print(f"{name} ({ticker}) - {size}")
        print('='*60)

        # 메인 페이지 컨센서스
        result = get_consensus_data(ticker)

        # 컨센서스 상세 페이지
        print(f"\n--- 컨센서스 상세 페이지 ---")
        detail = get_consensus_detail(ticker)

        time.sleep(1)

        print("\n")
