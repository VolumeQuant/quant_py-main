"""
상세 텔레그램 메시지 전송
"""
import pandas as pd
import numpy as np
from pykrx import stock
from datetime import datetime
import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# ============================================================
# 데이터 로드
# ============================================================
today = '20260202'

# 시장 지수
kospi_idx = stock.get_index_ohlcv('20260130', '20260202', '1001')
kosdaq_idx = stock.get_index_ohlcv('20260130', '20260202', '2001')

kospi_close = kospi_idx.iloc[-1, 3]  # 종가
kospi_prev = kospi_idx.iloc[-2, 3] if len(kospi_idx) > 1 else kospi_close
kospi_chg = ((kospi_close / kospi_prev) - 1) * 100

kosdaq_close = kosdaq_idx.iloc[-1, 3]
kosdaq_prev = kosdaq_idx.iloc[-2, 3] if len(kosdaq_idx) > 1 else kosdaq_close
kosdaq_chg = ((kosdaq_close / kosdaq_prev) - 1) * 100

# 시장 상태 판단
if kospi_chg > 1:
    market_status = "🟢 상승장"
elif kospi_chg < -1:
    market_status = "🔴 하락장"
else:
    market_status = "🟡 보합장"

# 포트폴리오 결과 로드
a = pd.read_csv('output/portfolio_2026_01_strategy_a.csv', encoding='utf-8-sig')
b = pd.read_csv('output/portfolio_2026_01_strategy_b.csv', encoding='utf-8-sig')

# 시가총액 데이터
market_cap = pd.read_parquet('data_cache/market_cap_ALL_20260202.parquet')

# OHLCV 데이터 (기술 지표 계산용)
ohlcv = pd.read_parquet('data_cache/all_ohlcv_20241106_20260130.parquet')

# 공통 종목
a['종목코드'] = a['종목코드'].astype(str).str.zfill(6)
b['종목코드'] = b['종목코드'].astype(str).str.zfill(6)
set_a = set(a['종목코드'])
set_b = set(b['종목코드'])
common = set_a & set_b

# ============================================================
# 기술 지표 계산 함수
# ============================================================
def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return np.nan
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

def calc_52week_position(prices):
    if len(prices) < 250:
        return np.nan, np.nan
    high_52w = prices.tail(250).max()
    low_52w = prices.tail(250).min()
    current = prices.iloc[-1]
    position = (current - low_52w) / (high_52w - low_52w) * 100 if high_52w != low_52w else 50
    from_high = (current / high_52w - 1) * 100
    return position, from_high

def get_stock_details(ticker, name, rank, strategy_type):
    """종목별 상세 정보 생성"""
    ticker_str = str(ticker).zfill(6)

    # 현재가
    try:
        price = market_cap.loc[ticker_str].iloc[0]  # 종가
        cap = market_cap.loc[ticker_str].iloc[1] / 100000000  # 시가총액 (억)
        market_type = market_cap.loc[ticker_str]['market']
    except:
        price = 0
        cap = 0
        market_type = 'KOSDAQ'

    # 기술 지표
    if ticker_str in ohlcv.columns:
        prices = ohlcv[ticker_str].dropna()
        rsi = calc_rsi(prices)
        pos_52w, from_high = calc_52week_position(prices)
    else:
        rsi = np.nan
        pos_52w = np.nan
        from_high = np.nan

    # RSI 문자열 (참고용)
    if pd.notna(rsi):
        rsi_str = f"RSI {rsi:.0f}"
    else:
        rsi_str = "RSI -"

    return {
        'ticker': ticker_str,
        'name': name,
        'price': price,
        'cap': cap,
        'market': market_type,
        'rsi': rsi,
        'rsi_str': rsi_str,
        'from_high': from_high if pd.notna(from_high) else 0,
        'rank': rank
    }

# ============================================================
# 메시지 생성
# ============================================================

# 메시지 1: 개요 + 공통 종목
msg1 = f"""🇰🇷 한국주식 퀀트 포트폴리오 v3.0
━━━━━━━━━━━━━━━━━━━━━━━━━
📅 {today[:4]}-{today[4:6]}-{today[6:]} 마감 | 유니버스 777개
🚦 시장: {market_status}
   KOSPI {kospi_close:,.0f} ({kospi_chg:+.1f}%)
   KOSDAQ {kosdaq_close:,.0f} ({kosdaq_chg:+.1f}%)
━━━━━━━━━━━━━━━━━━━━━━━━━

📋 전략 구성
🔴 전략A: 마법공식 (Magic Formula)
   • 이익수익률 = EBIT / EV
   • 투하자본수익률 = EBIT / IC

🔵 전략B: 멀티팩터 (Multi-Factor)
   • 밸류 40% (PER, PBR, PCR, PSR)
   • 퀄리티 40% (ROE, GPA, CFO/자산)
   • 모멘텀 20% (12개월 수익률)

━━━━━━━━━━━━━━━━━━━━━━━━━

⭐ 공통 종목 ({len(common)}개) - 강력 추천
두 전략 모두 TOP 30 = 최고 확신 종목

"""

# 공통 종목 상세 정보
common_details = []
for ticker in common:
    name_a = a[a['종목코드'] == ticker]['종목명'].values
    name = name_a[0] if len(name_a) > 0 else ticker
    rank_a = a[a['종목코드'] == ticker]['마법공식_순위'].values
    rank_b = b[b['종목코드'] == ticker]['멀티팩터_순위'].values
    rank_avg = (rank_a[0] + rank_b[0]) / 2 if len(rank_a) > 0 and len(rank_b) > 0 else 99
    details = get_stock_details(ticker, name, rank_avg, 'A')
    details['rank_a'] = rank_a[0] if len(rank_a) > 0 else 99
    details['rank_b'] = rank_b[0] if len(rank_b) > 0 else 99
    common_details.append(details)

# 평균 순위 순 정렬 (낮을수록 좋음)
common_details.sort(key=lambda x: (x['rank_a'] + x['rank_b']) / 2)

rank_emoji = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟']
for i, d in enumerate(common_details):
    emoji = rank_emoji[i] if i < 10 else f'#{i+1}'
    trend = '📈' if d['rsi'] and d['rsi'] > 50 else ('📉' if d['rsi'] and d['rsi'] < 50 else '')

    msg1 += f"""──────────────────────
{emoji} {d['name']} ({d['ticker']}) {trend}
   💰 {d['price']:,.0f}원 | 시총 {d['cap']:,.0f}억
   • 순위: A전략 {d['rank_a']:.0f}위 / B전략 {d['rank_b']:.0f}위
   • 📊 {d['rsi_str']} | 고점대비 {d['from_high']:.0f}%
   • {d['market']}
"""

msg1 += '━━━━━━━━━━━━━━━━━━━━━━━━━'

# ============================================================
# 메시지 2: 전략 A TOP 10
# ============================================================
msg2 = """🔴 전략 A - 마법공식 TOP 10
━━━━━━━━━━━━━━━━━━━━━━━━━
저평가 + 고효율 기업 발굴
이익수익률↑ + 투하자본수익률↑

"""

for i, (_, row) in enumerate(a.head(10).iterrows()):
    ticker = row['종목코드']
    name = row['종목명']
    rank = row['마법공식_순위']
    d = get_stock_details(ticker, name, rank, 'A')

    emoji = rank_emoji[i] if i < 10 else f'#{i+1}'
    trend = '📈' if d['rsi'] and d['rsi'] > 50 else ('📉' if d['rsi'] and d['rsi'] < 50 else '')
    common_mark = '⭐' if ticker in common else ''

    msg2 += f"""──────────────────────
{emoji} {d['name']} ({d['ticker']}) {trend}{common_mark}
   💰 {d['price']:,.0f}원 | {d['market']}
   📊 {d['rsi_str']} | 고점대비 {d['from_high']:.0f}%
"""

msg2 += '━━━━━━━━━━━━━━━━━━━━━━━━━'

# ============================================================
# 메시지 3: 전략 B TOP 10
# ============================================================
msg3 = """🔵 전략 B - 멀티팩터 TOP 10
━━━━━━━━━━━━━━━━━━━━━━━━━
밸류40% + 퀄리티40% + 모멘텀20%
학술적 팩터 결합 (Fama-French)

"""

for i, (_, row) in enumerate(b.head(10).iterrows()):
    ticker = row['종목코드']
    name = row['종목명']
    rank = row['멀티팩터_순위']
    d = get_stock_details(ticker, name, rank, 'B')

    emoji = rank_emoji[i] if i < 10 else f'#{i+1}'
    trend = '📈' if d['rsi'] and d['rsi'] > 50 else ('📉' if d['rsi'] and d['rsi'] < 50 else '')
    common_mark = '⭐' if ticker in common else ''

    msg3 += f"""──────────────────────
{emoji} {d['name']} ({d['ticker']}) {trend}{common_mark}
   💰 {d['price']:,.0f}원 | {d['market']}
   📊 {d['rsi_str']} | 고점대비 {d['from_high']:.0f}%
"""

msg3 += """━━━━━━━━━━━━━━━━━━━━━━━━━

💡 참고사항
• ⭐ = 양 전략 공통 선정 (강력 추천)
• RSI = 참고용 기술지표 (전략과 무관)
• 분기 리밸런싱 권장 (3/6/9/12월)
━━━━━━━━━━━━━━━━━━━━━━━━━"""

# ============================================================
# 텔레그램 전송
# ============================================================
url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'

r1 = requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': msg1})
print(f'메시지 1 (공통종목): {r1.status_code}')

r2 = requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': msg2})
print(f'메시지 2 (전략A): {r2.status_code}')

r3 = requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': msg3})
print(f'메시지 3 (전략B): {r3.status_code}')

print()
print('=== 공통 종목 요약 ===')
for d in common_details[:5]:
    rsi_val = f"{d['rsi']:.0f}" if pd.notna(d['rsi']) else 'N/A'
    avg_rank = (d['rank_a'] + d['rank_b']) / 2
    print(f"{d['name']}: 평균순위 {avg_rank:.1f}, RSI {rsi_val}")
