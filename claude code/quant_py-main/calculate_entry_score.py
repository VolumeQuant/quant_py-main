"""
공통 종목 진입가격 점수 계산
기준일: 2026-02-04
"""
import pandas as pd
import numpy as np
from pykrx import stock

# 공통 종목 8개
COMMON_STOCKS = {
    '018290': '브이티',
    '402340': 'SK스퀘어',
    '001060': 'JW중외제약',
    '000660': 'SK하이닉스',
    '119850': '지엔씨에너지',
    '124500': '아이티센글로벌',
    '204620': '글로벌텍스프리',
    '123330': '제닉',
}

BASE_DATE = '20260204'

def calculate_rsi(prices, period=14):
    """RSI 계산"""
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

def get_rsi_score(rsi):
    """RSI 점수 (40점 만점)"""
    if rsi <= 30:
        return 40
    elif rsi <= 50:
        return 30
    elif rsi <= 70:
        return 20
    else:
        return 10

def get_52week_score(current_price, high_52w):
    """52주 고점 대비 점수 (30점 만점)"""
    pct = (current_price - high_52w) / high_52w * 100
    if pct <= -20:
        return 30
    elif pct <= -10:
        return 25
    elif pct <= -5:
        return 20
    else:
        return 15

def get_volume_score(current_vol, avg_vol):
    """거래량 점수 (20점 만점)"""
    ratio = current_vol / avg_vol if avg_vol > 0 else 1
    if ratio >= 2.0:
        return 20
    elif ratio >= 1.5:
        return 15
    elif ratio >= 1.2:
        return 10
    else:
        return 5

def get_daily_change_score(change_pct):
    """일봉 변화 점수 (10점 만점)"""
    if change_pct > 0:
        return 10
    elif change_pct == 0:
        return 5
    else:
        return 0

def main():
    print("=" * 70)
    print("공통 종목 진입가격 점수 계산")
    print(f"기준일: {BASE_DATE}")
    print("=" * 70)

    results = []

    for ticker, name in COMMON_STOCKS.items():
        print(f"\n[{ticker}] {name}")

        try:
            # OHLCV 데이터 (1년)
            df = stock.get_market_ohlcv('20250204', BASE_DATE, ticker)
            if df.empty or len(df) < 20:
                print(f"  데이터 부족")
                continue

            current_price = df['종가'].iloc[-1]
            high_52w = df['고가'].max()
            current_vol = df['거래량'].iloc[-1]
            avg_vol = df['거래량'].iloc[-20:].mean()

            # 일봉 변화율
            prev_close = df['종가'].iloc[-2] if len(df) >= 2 else current_price
            change_pct = (current_price - prev_close) / prev_close * 100

            # RSI 계산
            rsi = calculate_rsi(df['종가'])

            # 점수 계산
            rsi_score = get_rsi_score(rsi)
            w52_score = get_52week_score(current_price, high_52w)
            vol_score = get_volume_score(current_vol, avg_vol)
            daily_score = get_daily_change_score(change_pct)

            total_score = rsi_score + w52_score + vol_score + daily_score

            print(f"  현재가: {current_price:,.0f}원")
            print(f"  52주 고점: {high_52w:,.0f}원 ({(current_price/high_52w-1)*100:+.1f}%)")
            print(f"  RSI: {rsi:.1f} → {rsi_score}점")
            print(f"  52주 점수: {w52_score}점")
            print(f"  거래량 비율: {current_vol/avg_vol:.2f}x → {vol_score}점")
            print(f"  일봉: {change_pct:+.2f}% → {daily_score}점")
            print(f"  ★ 진입점수: {total_score}점")

            results.append({
                'ticker': ticker,
                'name': name,
                'price': current_price,
                'high_52w': high_52w,
                'pct_from_high': (current_price/high_52w-1)*100,
                'rsi': rsi,
                'vol_ratio': current_vol/avg_vol,
                'daily_change': change_pct,
                'rsi_score': rsi_score,
                'w52_score': w52_score,
                'vol_score': vol_score,
                'daily_score': daily_score,
                'entry_score': total_score,
            })

        except Exception as e:
            print(f"  에러: {e}")

    # 결과 정렬 (진입점수 높은 순)
    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values('entry_score', ascending=False)

    print("\n" + "=" * 70)
    print("진입점수 순위 (높을수록 좋은 진입 타이밍)")
    print("=" * 70)

    for i, row in results_df.iterrows():
        print(f"{results_df.index.get_loc(i)+1}. {row['name']}({row['ticker']}): {row['entry_score']:.0f}점")
        print(f"   RSI={row['rsi']:.1f}, 52주고점대비={row['pct_from_high']:.1f}%, 거래량={row['vol_ratio']:.2f}x, 일봉={row['daily_change']:+.2f}%")

    # CSV 저장
    results_df.to_csv('output/entry_scores_20260204.csv', index=False, encoding='utf-8-sig')
    print(f"\n결과 저장: output/entry_scores_20260204.csv")

    return results_df

if __name__ == '__main__':
    main()
