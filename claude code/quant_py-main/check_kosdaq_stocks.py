"""전략 A 포트폴리오에서 코스닥 종목 확인"""
from pykrx import stock
import pandas as pd

# 포트폴리오 읽기
df = pd.read_csv('output/portfolio_2026_01_strategy_a.csv', encoding='utf-8-sig')

# 코스닥 전체 종목 리스트
kosdaq_list = stock.get_market_ticker_list('20251231', market='KOSDAQ')

kosdaq_stocks = []
kospi_stocks = []

for idx, row in df.iterrows():
    ticker = str(row['종목코드']).zfill(6)
    name = row['종목명']

    if ticker in kosdaq_list:
        kosdaq_stocks.append({
            '순위': idx + 1,
            '종목코드': ticker,
            '종목명': name,
            '시가총액(억)': int(row['시가총액']),
            '마법공식_순위': int(row['마법공식_순위'])
        })
    else:
        kospi_stocks.append({'순위': idx + 1, '종목코드': ticker, '종목명': name})

print('=' * 80)
print('전략 A 포트폴리오 - 코스닥 종목 (19개)')
print('=' * 80)
kosdaq_df = pd.DataFrame(kosdaq_stocks)
print(kosdaq_df.to_string(index=False))
print(f'\n총 코스닥 종목: {len(kosdaq_stocks)}개')
print(f'총 코스피 종목: {len(kospi_stocks)}개')
print(f'전체: {len(df)}개')
