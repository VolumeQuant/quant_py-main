"""
데이터 수집 모듈 (pykrx 기반)
MySQL DB 의존성 제거, API에서 직접 데이터 수집
"""

import pandas as pd
import numpy as np
from pykrx import stock
from datetime import datetime, timedelta
import time
import os
from pathlib import Path

# FinanceDataReader는 선택적 사용 (설치되어 있으면 사용)
try:
    import FinanceDataReader as fdr
    HAS_FDR = True
except ImportError:
    HAS_FDR = False

# 데이터 캐싱 디렉토리
DATA_DIR = Path(__file__).parent / 'data_cache'
DATA_DIR.mkdir(exist_ok=True)


class DataCollector:
    """한국 주식 데이터 수집 클래스"""

    def __init__(self, start_date='20150101', end_date='20251231'):
        self.start_date = start_date
        self.end_date = end_date

    def get_ticker_list(self, date, market='ALL'):
        """특정 날짜의 종목 리스트 조회

        Args:
            date: 조회 날짜 (YYYYMMDD)
            market: 'KOSPI', 'KOSDAQ', 'ALL'
        """
        cache_file = DATA_DIR / f'tickers_{market}_{date}.parquet'

        if cache_file.exists():
            print(f"캐시에서 종목 리스트 로드: {cache_file}")
            return pd.read_parquet(cache_file)

        print(f"{date} 종목 리스트 수집 중...")

        if market == 'ALL':
            kospi = stock.get_market_ticker_list(date, market='KOSPI')
            kosdaq = stock.get_market_ticker_list(date, market='KOSDAQ')
            tickers = list(set(kospi + kosdaq))
        else:
            tickers = stock.get_market_ticker_list(date, market=market)

        # 종목명과 섹터 정보 추가
        ticker_data = []
        for ticker in tickers:
            try:
                name = stock.get_market_ticker_name(ticker)
                # 섹터 정보는 별도로 수집 필요
                ticker_data.append({
                    '종목코드': ticker,
                    '종목명': name,
                })
                time.sleep(0.05)  # API 호출 제한 고려
            except Exception as e:
                print(f"종목 {ticker} 정보 수집 실패: {e}")
                continue

        df = pd.DataFrame(ticker_data)
        df.to_parquet(cache_file)

        return df

    def get_market_cap(self, date, market='ALL'):
        """특정 날짜의 시가총액 데이터 조회"""
        cache_file = DATA_DIR / f'market_cap_{market}_{date}.parquet'

        if cache_file.exists():
            print(f"캐시에서 시가총액 로드: {cache_file}")
            return pd.read_parquet(cache_file)

        print(f"{date} 시가총액 데이터 수집 중...")

        if market == 'ALL':
            df_kospi = stock.get_market_cap(date, market='KOSPI')
            df_kosdaq = stock.get_market_cap(date, market='KOSDAQ')
            df = pd.concat([df_kospi, df_kosdaq])
        else:
            df = stock.get_market_cap(date, market=market)

        df.to_parquet(cache_file)
        time.sleep(0.1)

        return df

    def get_ohlcv(self, ticker, start_date=None, end_date=None):
        """특정 종목의 OHLCV 데이터 조회"""
        if start_date is None:
            start_date = self.start_date
        if end_date is None:
            end_date = self.end_date

        cache_file = DATA_DIR / f'ohlcv_{ticker}_{start_date}_{end_date}.parquet'

        if cache_file.exists():
            return pd.read_parquet(cache_file)

        try:
            df = stock.get_market_ohlcv(start_date, end_date, ticker)
            df.to_parquet(cache_file)
            time.sleep(0.05)
            return df
        except Exception as e:
            print(f"종목 {ticker} OHLCV 수집 실패: {e}")
            return pd.DataFrame()

    def get_all_ohlcv(self, tickers, start_date=None, end_date=None):
        """모든 종목의 OHLCV 데이터 수집 (수정주가 기준)"""
        if start_date is None:
            start_date = self.start_date
        if end_date is None:
            end_date = self.end_date

        cache_file = DATA_DIR / f'all_ohlcv_{start_date}_{end_date}.parquet'

        if cache_file.exists():
            print(f"캐시에서 전체 OHLCV 로드: {cache_file}")
            return pd.read_parquet(cache_file)

        print(f"전체 종목 OHLCV 수집 중 (총 {len(tickers)}개 종목)...")

        price_data = {}
        for i, ticker in enumerate(tickers):
            if i % 50 == 0:
                print(f"진행률: {i}/{len(tickers)} ({i/len(tickers)*100:.1f}%)")

            df = self.get_ohlcv(ticker, start_date, end_date)
            if not df.empty:
                price_data[ticker] = df['종가']

        # 데이터프레임으로 변환
        df_prices = pd.DataFrame(price_data)
        df_prices.to_parquet(cache_file)

        print(f"OHLCV 수집 완료: {len(price_data)}개 종목")
        return df_prices

    def get_fundamental(self, date, ticker):
        """특정 종목의 재무 지표 조회 (PER, PBR, EPS, BPS 등)"""
        try:
            # pykrx는 날짜 범위가 필요하므로 같은 날짜를 시작/종료로 사용하면 안됨
            # 해당 날짜가 포함된 범위 사용 (최근 1주일)
            from datetime import datetime, timedelta
            end_date = datetime.strptime(date, '%Y%m%d')
            start_date = end_date - timedelta(days=7)
            start_date_str = start_date.strftime('%Y%m%d')

            df = stock.get_market_fundamental(start_date_str, date, ticker)
            time.sleep(0.05)

            # 가장 최근 데이터 반환
            return df.iloc[-1] if not df.empty else None
        except Exception as e:
            print(f"종목 {ticker} 펀더멘털 수집 실패: {e}")
            return None

    def get_all_fundamentals(self, date, tickers):
        """모든 종목의 펀더멘털 데이터 수집"""
        cache_file = DATA_DIR / f'fundamentals_{date}.parquet'

        if cache_file.exists():
            print(f"캐시에서 펀더멘털 로드: {cache_file}")
            return pd.read_parquet(cache_file)

        print(f"{date} 전체 종목 펀더멘털 수집 중...")

        fundamental_data = []
        for i, ticker in enumerate(tickers):
            if i % 50 == 0:
                print(f"진행률: {i}/{len(tickers)} ({i/len(tickers)*100:.1f}%)")

            fund = self.get_fundamental(date, ticker)
            if fund is not None:
                fund_dict = fund.to_dict()
                fund_dict['종목코드'] = ticker
                fundamental_data.append(fund_dict)

        df = pd.DataFrame(fundamental_data)
        df.to_parquet(cache_file)

        print(f"펀더멘털 수집 완료: {len(fundamental_data)}개 종목")
        return df

    def get_market_fundamental_batch(self, date, market='ALL'):
        """전체 시장 펀더멘털 일괄 조회 (PER/PBR/EPS/BPS/DIV)

        pykrx stock.get_market_fundamental()을 사용하여
        한 번의 호출로 전체 시장 데이터를 반환합니다.
        """
        cache_file = DATA_DIR / f'fundamental_batch_{market}_{date}.parquet'

        if cache_file.exists():
            print(f"캐시에서 펀더멘털 배치 로드: {cache_file}")
            return pd.read_parquet(cache_file)

        print(f"{date} 전체 시장 펀더멘털 일괄 수집 중...")

        try:
            if market == 'ALL':
                df_kospi = stock.get_market_fundamental(date, market='KOSPI')
                df_kosdaq = stock.get_market_fundamental(date, market='KOSDAQ')
                df = pd.concat([df_kospi, df_kosdaq])
            else:
                df = stock.get_market_fundamental(date, market=market)

            df.to_parquet(cache_file)
            time.sleep(0.1)
            print(f"펀더멘털 배치 수집 완료: {len(df)}개 종목")
            return df
        except Exception as e:
            print(f"펀더멘털 배치 수집 실패: {e}")
            return pd.DataFrame()

    def get_krx_sector(self, date):
        """KRX 섹터 정보 조회"""
        cache_file = DATA_DIR / f'krx_sector_{date}.parquet'

        if cache_file.exists():
            print(f"캐시에서 섹터 정보 로드: {cache_file}")
            return pd.read_parquet(cache_file)

        print(f"{date} 섹터 정보 수집 중...")

        # pykrx로 업종 정보 가져오기
        try:
            df = stock.get_market_ticker_and_name(date)
            sectors = []

            for ticker in df.index:
                try:
                    # 개별 종목의 업종 정보
                    # Note: pykrx에서 직접 업종을 가져오는 방법이 제한적일 수 있음
                    sectors.append({
                        '종목코드': ticker,
                        '종목명': df.loc[ticker]
                    })
                    time.sleep(0.03)
                except:
                    continue

            sector_df = pd.DataFrame(sectors)
            sector_df.to_parquet(cache_file)
            return sector_df

        except Exception as e:
            print(f"섹터 정보 수집 실패: {e}")
            return pd.DataFrame()

    def get_financial_statement_fdr(self, ticker):
        """FinanceDataReader로 재무제표 조회 (선택적)

        Returns:
            dict: {'income': 손익계산서, 'balance': 재무상태표, 'cashflow': 현금흐름표}
        """
        if not HAS_FDR:
            # FinanceDataReader가 없으면 빈 DataFrame 반환
            # FnGuide 크롤러를 대신 사용할 수 있음
            return pd.DataFrame()

        cache_file = DATA_DIR / f'fs_{ticker}.parquet'

        if cache_file.exists():
            return pd.read_parquet(cache_file)

        try:
            # 연간 재무제표 조회
            fs = fdr.DataReader(ticker, data_type='financial-statement')
            time.sleep(0.1)

            if isinstance(fs, dict):
                # 모든 재무제표를 하나의 데이터프레임으로 결합
                df_list = []
                for key, df in fs.items():
                    if df is not None and not df.empty:
                        df_copy = df.copy()
                        df_copy['statement_type'] = key
                        df_list.append(df_copy)

                if df_list:
                    combined_df = pd.concat(df_list, axis=0)
                    combined_df.to_parquet(cache_file)
                    return combined_df

            return pd.DataFrame()

        except Exception as e:
            print(f"종목 {ticker} 재무제표 수집 실패: {e}")
            return pd.DataFrame()

    def get_all_financial_statements(self, tickers):
        """모든 종목의 재무제표 수집 (병렬 처리 권장)"""
        print(f"전체 종목 재무제표 수집 중 (총 {len(tickers)}개 종목)...")

        fs_data = {}
        for i, ticker in enumerate(tickers):
            if i % 20 == 0:
                print(f"진행률: {i}/{len(tickers)} ({i/len(tickers)*100:.1f}%)")

            fs = self.get_financial_statement_fdr(ticker)
            if not fs.empty:
                fs_data[ticker] = fs

        print(f"재무제표 수집 완료: {len(fs_data)}개 종목")
        return fs_data

    def get_index_ohlcv(self, start_date=None, end_date=None, ticker='1001'):
        """코스피 지수 데이터 조회

        Args:
            ticker: '1001' (코스피), '2001' (코스닥)
        """
        if start_date is None:
            start_date = self.start_date
        if end_date is None:
            end_date = self.end_date

        cache_file = DATA_DIR / f'index_{ticker}_{start_date}_{end_date}.parquet'

        if cache_file.exists():
            print(f"캐시에서 지수 데이터 로드: {cache_file}")
            return pd.read_parquet(cache_file)

        print(f"지수 데이터 수집 중: {ticker}")

        df = stock.get_index_ohlcv(start_date, end_date, ticker)
        df.to_parquet(cache_file)

        return df


if __name__ == '__main__':
    # 테스트
    collector = DataCollector(start_date='20150101', end_date='20251231')

    # 1. 최근 종목 리스트 조회
    tickers_df = collector.get_ticker_list('20251231', market='ALL')
    print(f"\n총 종목 수: {len(tickers_df)}")
    print(tickers_df.head())

    # 2. 시가총액 조회
    market_cap = collector.get_market_cap('20251231', market='ALL')
    print(f"\n시가총액 데이터 수: {len(market_cap)}")
    print(market_cap.head())

    # 3. 코스피 지수 조회
    kospi = collector.get_index_ohlcv(ticker='1001')
    print(f"\n코스피 지수 데이터: {len(kospi)} days")
    print(kospi.tail())
