"""
미국주식 EPS 모멘텀 포맷과 동일한 스타일의 텔레그램 메시지
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import pandas as pd
import numpy as np
from pykrx import stock
from datetime import datetime, timedelta
from pathlib import Path
import requests
import json
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# ============================================================
# 설정
# ============================================================
CACHE_DIR = Path('data_cache')
OUTPUT_DIR = Path('output')
HISTORY_FILE = CACHE_DIR / 'portfolio_history.json'

# ============================================================
# Claude 최종 순위 (공통 종목 대상)
# 진입점수 기반 순위: RSI + 52주위치 + 거래량 + 일봉
# ============================================================
CLAUDE_FINAL_RANKING = {
    '119850': {  # 지엔씨에너지
        'rank': 1,
        'strategy_a_score': 33,  # A 21위 → (31-21)/30*100 = 33
        'strategy_b_score': 27,  # B 23위 → (31-23)/30*100 = 27
        'entry_score': 75,
        'total_score': 84.0,  # 진입점수 기반
        'rsi': 62.8,
        'w52_pct': -14.8,
        'vol_ratio': 2.75,
        'daily_chg': 9.78,
        'sector': '에너지/발전설비',
        'reason': [
            '거래량 2.75배 급증! 당일 +9.78% 급등',
            'AI 데이터센터 비상발전기 국내 1위',
            'SK울산 수주, 영업이익 115%↑'
        ],
        'risk': '중소형주 변동성, 전략순위 중위권'
    },
    '204620': {  # 글로벌텍스프리
        'rank': 2,
        'strategy_a_score': 13,  # A 27위
        'strategy_b_score': 63,  # B 12위
        'entry_score': 75,
        'total_score': 82.5,
        'rsi': 83.9,
        'w52_pct': -33.8,
        'vol_ratio': 3.05,
        'daily_chg': 5.07,
        'sector': '택스리펀드/면세',
        'reason': [
            '거래량 3.05배 폭발',
            '52주고점 -33.8% 저점매수 기회',
            '면세사업 회복, 중국 관광객 증가'
        ],
        'risk': 'RSI 83.9 과매수! 단기 차익실현 가능'
    },
    '123330': {  # 제닉
        'rank': 3,
        'strategy_a_score': 97,  # A 2위
        'strategy_b_score': 50,  # B 16위
        'entry_score': 75,
        'total_score': 81.0,
        'rsi': 69.7,
        'w52_pct': -50.1,
        'vol_ratio': 2.09,
        'daily_chg': -2.65,
        'sector': 'K-뷰티/화장품',
        'reason': [
            '전략A 2위 최상위',
            '52주고점 -50.1% 역대급 저점!',
            'ROE 52.4% 초고수익, 마스크팩 수출'
        ],
        'risk': 'RSI 69.7 과열 접근, 당일 -2.65% 조정'
    },
    '018290': {  # 브이티
        'rank': 4,
        'strategy_a_score': 100,  # A 1위
        'strategy_b_score': 37,   # B 20위
        'entry_score': 60,
        'total_score': 78.5,
        'rsi': 74.3,
        'w52_pct': -55.9,
        'vol_ratio': 0.71,
        'daily_chg': 0.90,
        'sector': 'K-뷰티',
        'reason': [
            '전략A 1위! 마법공식 최고 순위',
            '52주고점 -55.9% 역대급 저점',
            'K-뷰티 대장주, 영업이익률 29%'
        ],
        'risk': 'RSI 74.3 과매수, 거래량 0.71x 약함'
    },
    '402340': {  # SK스퀘어
        'rank': 5,
        'strategy_a_score': 75,  # A 8.5위
        'strategy_b_score': 70,  # B 10위
        'entry_score': 55,
        'total_score': 75.0,
        'rsi': 71.8,
        'w52_pct': -2.1,
        'vol_ratio': 1.67,
        'daily_chg': 4.21,
        'sector': '투자지주/AI반도체',
        'reason': [
            'SK하이닉스 20% 지분 보유!',
            '거래량 1.67배, 당일 +4.21% 급등',
            'AI 반도체 간접투자, 주주환원 확대'
        ],
        'risk': 'RSI 71.8 과매수, 52주고점 근접'
    },
    '001060': {  # JW중외제약
        'rank': 6,
        'strategy_a_score': 43,  # A 18위
        'strategy_b_score': 10,  # B 28위
        'entry_score': 55,
        'total_score': 72.0,
        'rsi': 75.6,
        'w52_pct': -1.8,
        'vol_ratio': 1.60,
        'daily_chg': 6.48,
        'sector': '바이오/제약',
        'reason': [
            '거래량 1.60배, 당일 +6.48% 급등',
            '영업이익 971억, ROE 17.7%',
            '안정적 제약주, 배당 매력'
        ],
        'risk': 'RSI 75.6 과매수! 전략순위 중하위'
    },
    '124500': {  # 아이티센글로벌
        'rank': 7,
        'strategy_a_score': 28,  # A 22.5위
        'strategy_b_score': 93,  # B 3위
        'entry_score': 45,
        'total_score': 68.0,
        'rsi': 72.7,
        'w52_pct': -8.4,
        'vol_ratio': 0.36,
        'daily_chg': 0.79,
        'sector': 'IT/금거래',
        'reason': [
            '전략B 3위! 한국금거래소 운영',
            '금값 상승 수혜, 영업이익 293%↑',
            '디지털 금 플랫폼, 스테이블코인'
        ],
        'risk': 'RSI 72.7 과매수, 거래량 0.36x 약함'
    },
    '000660': {  # SK하이닉스
        'rank': 8,
        'strategy_a_score': 3,   # A 30위
        'strategy_b_score': 77,  # B 8위
        'entry_score': 40,
        'total_score': 65.0,
        'rsi': 67.4,
        'w52_pct': -3.3,
        'vol_ratio': 0.80,
        'daily_chg': -0.77,
        'sector': 'AI반도체/메모리',
        'reason': [
            'HBM 글로벌 1위, AI 대장주',
            '2026년 영업이익 100조+ 전망',
            '실적 확실성 최고 대형주'
        ],
        'risk': '진입타이밍 비추! RSI 67, 당일 -0.77%'
    },
}

# ============================================================
# 날짜/시장 정보 가져오기
# ============================================================
# 오늘 날짜 (메시지 발송일)
TODAY = '20260205'
# 분석 기준일 (어제 데이터)
BASE_DATE = '20260204'
print(f"오늘: {TODAY}, 분석 기준일: {BASE_DATE}")

# 시장 지수 가져오기 (기준일 데이터)
start_date = (datetime.strptime(BASE_DATE, '%Y%m%d') - timedelta(days=7)).strftime('%Y%m%d')
kospi_idx = stock.get_index_ohlcv(start_date, BASE_DATE, '1001')
kosdaq_idx = stock.get_index_ohlcv(start_date, BASE_DATE, '2001')

kospi_close = kospi_idx.iloc[-1, 3]
kospi_prev = kospi_idx.iloc[-2, 3] if len(kospi_idx) > 1 else kospi_close
kospi_chg = ((kospi_close / kospi_prev) - 1) * 100

kosdaq_close = kosdaq_idx.iloc[-1, 3]
kosdaq_prev = kosdaq_idx.iloc[-2, 3] if len(kosdaq_idx) > 1 else kosdaq_close
kosdaq_chg = ((kosdaq_close / kosdaq_prev) - 1) * 100

# 시장 상태 판단
if kospi_chg > 1:
    market_color = "🟢"
    market_status = "상승장 (GREEN)"
elif kospi_chg < -1:
    market_color = "🔴"
    market_status = "하락장 (RED)"
else:
    market_color = "🟡"
    market_status = "보합장 (NEUTRAL)"

# MA 상태 체크 (간단히)
ma_status = ""
try:
    kospi_60d = stock.get_index_ohlcv(
        (datetime.strptime(BASE_DATE, '%Y%m%d') - timedelta(days=90)).strftime('%Y%m%d'),
        BASE_DATE, '1001'
    )
    if len(kospi_60d) >= 50:
        ma50 = kospi_60d.iloc[-50:, 3].mean()
        if kospi_close < ma50:
            ma_status = " ⚠️MA50 하회"
        else:
            ma_status = " ✅MA50 상회"
except:
    pass

# ============================================================
# 포트폴리오 결과 로드
# ============================================================
a = pd.read_csv(OUTPUT_DIR / 'portfolio_2026_01_strategy_a.csv', encoding='utf-8-sig')
b = pd.read_csv(OUTPUT_DIR / 'portfolio_2026_01_strategy_b.csv', encoding='utf-8-sig')

a['종목코드'] = a['종목코드'].astype(str).str.zfill(6)
b['종목코드'] = b['종목코드'].astype(str).str.zfill(6)

set_a = set(a['종목코드'])
set_b = set(b['종목코드'])
common_today = set_a & set_b

# 종목명 딕셔너리
ticker_names = {}
for _, row in a.iterrows():
    ticker_names[row['종목코드']] = row['종목명']
for _, row in b.iterrows():
    ticker_names[row['종목코드']] = row['종목명']

# 이전 결과와 비교
if HISTORY_FILE.exists():
    with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
        previous = json.load(f)
    prev_common = set(previous.get('common', []))
    common_added = common_today - prev_common
    common_removed = prev_common - common_today
else:
    common_added = set()
    common_removed = set()

# ============================================================
# 실시간 시세 조회
# ============================================================
def get_stock_price(ticker):
    """종목 현재가/변동률 조회"""
    ticker_str = str(ticker).zfill(6)
    try:
        start = (datetime.strptime(BASE_DATE, '%Y%m%d') - timedelta(days=7)).strftime('%Y%m%d')
        ohlcv = stock.get_market_ohlcv(start, BASE_DATE, ticker_str)
        if not ohlcv.empty and len(ohlcv) >= 2:
            price = ohlcv.iloc[-1, 3]
            prev_price = ohlcv.iloc[-2, 3]
            change_pct = (price / prev_price - 1) * 100
            return price, change_pct
    except:
        pass
    return 0, 0

# ============================================================
# 메시지 생성 (미국주식 EPS 모멘텀 스타일)
# ============================================================

# 날짜 포맷
today_str = f"{TODAY[4:6]}월{TODAY[6:]}일"
base_date_str = f"{BASE_DATE[:4]}년 {BASE_DATE[4:6]}월 {BASE_DATE[6:]}일"

msg1 = f"""안녕하세요! 오늘({today_str}) 한국주식 퀀트 포트폴리오입니다 📊

━━━━━━━━━━━━━━━━━━━
📅 {base_date_str} 기준 분석
{market_color} {market_status}
• 코스피 {kospi_close:,.0f} ({kospi_chg:+.2f}%){ma_status}
• 코스닥 {kosdaq_close:,.0f} ({kosdaq_chg:+.2f}%)
━━━━━━━━━━━━━━━━━━━

💡 전략 v2.0

• 유니버스: 거래대금 30억↑ 약 630개

[1단계] 밸류 - 뭘 살까? (630개 → 8개)
• 전략A 마법공식 30개 ∩ 전략B 멀티팩터 30개
• 공통종목 {len(common_today)}개 선정

[2단계] 가격 - 언제 살까? (8개 → 순위)
• 진입점수로 정렬 (RSI↓ 52주저점↓ 거래량↑)

━━━━━━━━━━━━━━━━━━━
🏆 진입점수 기준 TOP 8 ({len(common_today)}개 공통종목)
━━━━━━━━━━━━━━━━━━━
"""

# 순위별 정렬
sorted_stocks = sorted(CLAUDE_FINAL_RANKING.items(), key=lambda x: x[1]['rank'])

for ticker, data in sorted_stocks:
    name = ticker_names.get(ticker, ticker)
    rank = data['rank']
    price, daily_chg = get_stock_price(ticker)
    if price == 0:
        price = 0
        daily_chg = data['daily_chg']

    # 순위별 메달 이모지
    if rank == 1:
        medal = "🥇"
    elif rank == 2:
        medal = "🥈"
    elif rank == 3:
        medal = "🥉"
    else:
        medal = "📌"

    msg1 += f"""
{medal} {rank}위 {name} ({ticker}) {data['sector']}
💰 {price:,.0f}원 ({daily_chg:+.2f}%)
📊 진입 {data['entry_score']:.0f}점 | A순위 {int(100-data['strategy_a_score'])/3.33+1:.0f}위 | B순위 {int(100-data['strategy_b_score'])/3.33+1:.0f}위
📈 진입타이밍: RSI {data['rsi']:.0f} | 52주 {data['w52_pct']:+.0f}%
📝 선정이유:
"""
    for reason in data['reason']:
        msg1 += f"• {reason}\n"

    msg1 += f"⚠️ 리스크: {data['risk']}\n"
    msg1 += "━━━━━━━━━━━━━━━━━━━\n"

# 핵심 추천 섹션
msg1 += """
🎯 핵심 추천

✅ 적극 매수 (진입점수 70+, 거래량↑)
• 지엔씨에너지 - 진입75점, 거래량2.75x 폭발
• 글로벌텍스프리 - 진입75점, 52주 -33% 저점

💰 저점 매수 기회 (52주 -50% 이하)
• 제닉 - 52주 -50%, 전략A 2위
• 브이티 - 52주 -56%, 전략A 1위
  ⚠️ RSI 70+ 과매수, 분할매수 권장

⏸️ 조정 대기 (RSI 75+ 과매수)
• JW중외제약 (RSI 76)
• 아이티센글로벌 (RSI 73)

━━━━━━━━━━━━━━━━━━━
"""

# 메시지 2: 전략A TOP 15
msg2 = f"""🔴 전략A 마법공식 TOP 15
━━━━━━━━━━━━━━━━━━━
이익수익률↑ + ROIC↑ = 싸고 돈 잘 버는 기업
━━━━━━━━━━━━━━━━━━━
"""

for i, (_, row) in enumerate(a.head(15).iterrows()):
    ticker = row['종목코드']
    name = row['종목명']
    is_common = "⭐" if ticker in common_today else ""
    price, chg = get_stock_price(ticker)

    # 순위 이모지
    if i == 0:
        rank_icon = "🥇"
    elif i == 1:
        rank_icon = "🥈"
    elif i == 2:
        rank_icon = "🥉"
    else:
        rank_icon = f"{i+1:2d}."

    msg2 += f"{rank_icon} {name} {is_common} | {price:,.0f}원 ({chg:+.1f}%)\n"

msg2 += """━━━━━━━━━━━━━━━━━━━
"""

# 메시지 3: 전략B TOP 15
msg3 = f"""🔵 전략B 멀티팩터 TOP 15
━━━━━━━━━━━━━━━━━━━
밸류40% + 퀄리티40% + 모멘텀20%
━━━━━━━━━━━━━━━━━━━
"""

for i, (_, row) in enumerate(b.head(15).iterrows()):
    ticker = row['종목코드']
    name = row['종목명']
    is_common = "⭐" if ticker in common_today else ""
    price, chg = get_stock_price(ticker)

    # 순위 이모지
    if i == 0:
        rank_icon = "🥇"
    elif i == 1:
        rank_icon = "🥈"
    elif i == 2:
        rank_icon = "🥉"
    else:
        rank_icon = f"{i+1:2d}."

    msg3 += f"{rank_icon} {name} {is_common} | {price:,.0f}원 ({chg:+.1f}%)\n"

msg3 += """━━━━━━━━━━━━━━━━━━━

💡 범례: ⭐ = 공통종목 (A+B 모두 선정)

📌 투자 유의사항
• 본 정보는 투자 권유가 아닙니다
• 투자 결정은 본인 판단하에
• 분기별 리밸런싱 권장 (3/6/9/12월)
━━━━━━━━━━━━━━━━━━━
📊 Quant Portfolio v2.0
"""

# ============================================================
# 텔레그램 전송
# ============================================================
url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'

print("\n=== 메시지 1 미리보기 ===")
print(msg1[:2000])
print("\n... (생략)")

print("\n=== 메시지 2 (전략A) 미리보기 ===")
print(msg2)

print("\n=== 메시지 3 (전략B) 미리보기 ===")
print(msg3)

# 전송
r1 = requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': msg1})
print(f'\n메시지 1 전송: {r1.status_code}')

r2 = requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': msg2})
print(f'메시지 2 전송: {r2.status_code}')

r3 = requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': msg3})
print(f'메시지 3 전송: {r3.status_code}')

# 히스토리 저장
history = {
    'date': TODAY,
    'strategy_a': list(set_a),
    'strategy_b': list(set_b),
    'common': list(common_today),
    'ticker_names': ticker_names
}
with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
    json.dump(history, f, ensure_ascii=False, indent=2)

print(f'\n히스토리 저장: {HISTORY_FILE}')
print(f'공통종목: {len(common_today)}개')
