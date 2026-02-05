"""
한국주식 퀀트 포트폴리오 텔레그램 메시지 (완전 자동화)
실행: python send_telegram_auto.py
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

# 섹터 데이터베이스 (공통 종목 후보들)
SECTOR_DB = {
    '000660': 'AI반도체/메모리',
    '001060': '바이오/제약',
    '018290': 'K-뷰티',
    '033500': 'LNG단열재',
    '035900': '엔터/K-POP',
    '039130': '여행',
    '067160': '스트리밍',
    '119850': '에너지/발전설비',
    '123330': 'K-뷰티/화장품',
    '124500': 'IT/금거래',
    '204620': '택스리펀드/면세',
    '383220': '패션/브랜드',
    '402340': '투자지주/AI반도체',
    '419530': '애니/캐릭터',
    '278470': '뷰티디바이스',
    '336570': '의료기기',
    '033100': '변압기/전력',
    '250060': 'AI/핵융합',
    '041510': '엔터/K-POP',
    '259960': '게임',
    '043260': '전자부품',
    '008770': '면세점/호텔',
    '084670': '자동차부품',
    '036620': '아웃도어패션',
}

# ============================================================
# 날짜 자동 계산
# ============================================================
def get_latest_trading_date():
    """최근 거래일 찾기 (오늘 또는 어제)"""
    now = datetime.now()
    for i in range(10):
        date = (now - timedelta(days=i)).strftime('%Y%m%d')
        try:
            df = stock.get_market_cap(date, market='KOSPI')
            if not df.empty and df.iloc[:, 0].sum() > 0:
                return date
        except:
            continue
    return None

def get_previous_trading_date(date_str):
    """이전 거래일 찾기"""
    current = datetime.strptime(date_str, '%Y%m%d')
    for i in range(1, 10):
        prev = (current - timedelta(days=i)).strftime('%Y%m%d')
        try:
            df = stock.get_market_cap(prev, market='KOSPI')
            if not df.empty and df.iloc[:, 0].sum() > 0:
                return prev
        except:
            continue
    return None

# 날짜 설정
TODAY = datetime.now().strftime('%Y%m%d')
BASE_DATE = get_latest_trading_date()  # 가장 최근 거래일 (분석 기준일)
print(f"오늘: {TODAY}, 분석 기준일: {BASE_DATE}")

if BASE_DATE is None:
    print("거래일을 찾을 수 없습니다.")
    sys.exit(1)

# ============================================================
# 기술 지표 계산 함수
# ============================================================
def calc_rsi(prices, period=14):
    """RSI 계산"""
    if len(prices) < period + 1:
        return 50
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50

def get_stock_technical(ticker):
    """종목 기술적 지표 계산"""
    ticker_str = str(ticker).zfill(6)
    try:
        # 1년 OHLCV 조회
        start = (datetime.strptime(BASE_DATE, '%Y%m%d') - timedelta(days=365)).strftime('%Y%m%d')
        ohlcv = stock.get_market_ohlcv(start, BASE_DATE, ticker_str)

        if ohlcv.empty or len(ohlcv) < 20:
            return None

        # 현재가, 전일비
        price = ohlcv.iloc[-1]['종가']
        prev_price = ohlcv.iloc[-2]['종가'] if len(ohlcv) >= 2 else price
        daily_chg = (price / prev_price - 1) * 100

        # RSI
        rsi = calc_rsi(ohlcv['종가'])

        # 52주 고점 대비
        high_52w = ohlcv['고가'].max()
        w52_pct = (price / high_52w - 1) * 100

        # 거래량 비율 (20일 평균 대비)
        current_vol = ohlcv.iloc[-1]['거래량']
        avg_vol = ohlcv['거래량'].tail(20).mean()
        vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1

        return {
            'price': price,
            'daily_chg': daily_chg,
            'rsi': rsi,
            'w52_pct': w52_pct,
            'vol_ratio': vol_ratio,
        }
    except Exception as e:
        print(f"  기술지표 계산 실패 {ticker_str}: {e}")
        return None

def calc_entry_score(rsi, w52_pct, vol_ratio):
    """
    진입점수 계산 (100점 만점)

    구성:
    - RSI (40점): 과매도일수록 좋음, 단 신고가 돌파시 과매수도 OK
    - 52주 위치 (30점): 할인 or 돌파 모멘텀
    - 거래량 (20점): 스파이크 확인
    - 기본 점수 (10점): 통과 종목 기본
    """
    # 신고가 돌파 판단 (52주 고점 -2% 이내)
    is_breakout = w52_pct > -2

    # RSI (40점)
    if rsi <= 30:
        rsi_score = 40  # 과매도 - 매수 기회
    elif rsi <= 50:
        rsi_score = 30  # 양호
    elif rsi <= 70:
        rsi_score = 20  # 중립
    else:
        # RSI > 70
        if is_breakout:
            rsi_score = 35  # 신고가 돌파 모멘텀 OK
        else:
            rsi_score = 10  # 일반 과매수 위험

    # 52주 고점 대비 (30점)
    if is_breakout:  # -2% 이내 (신고가)
        w52_score = 30  # 돌파 모멘텀
    elif w52_pct <= -20:
        w52_score = 30  # 큰 할인
    elif w52_pct <= -10:
        w52_score = 25  # 의미있는 할인
    elif w52_pct <= -5:
        w52_score = 20  # 적당한 조정
    else:
        w52_score = 15  # 소폭 조정

    # 거래량 (20점)
    if vol_ratio >= 1.5:
        vol_score = 20  # 거래량 스파이크
    else:
        vol_score = 10  # 일반

    # 기본 점수 (10점) - 통과 종목 기본
    base_score = 10

    return rsi_score + w52_score + vol_score + base_score

def generate_reasons(ticker, tech, rank_a, rank_b):
    """선정이유 자동 생성"""
    reasons = []
    is_breakout = tech['w52_pct'] > -2  # 신고가 돌파

    # 신고가 돌파 모멘텀 (최우선)
    if is_breakout:
        reasons.append(f"52주 신고가 돌파 모멘텀! ({tech['w52_pct']:+.1f}%)")

    # 거래량 급증
    if tech['vol_ratio'] >= 2.0:
        reasons.append(f"거래량 {tech['vol_ratio']:.1f}배 급증!")
    elif tech['vol_ratio'] >= 1.5:
        reasons.append(f"거래량 {tech['vol_ratio']:.1f}배 스파이크")

    # 전략 순위
    if rank_a <= 5:
        reasons.append(f"전략A {rank_a:.0f}위 최상위")
    if rank_b <= 5:
        reasons.append(f"전략B {rank_b:.0f}위 최상위")

    # 52주 저점 (신고가 돌파가 아닐 때만)
    if not is_breakout:
        if tech['w52_pct'] <= -40:
            reasons.append(f"52주고점 -40% 역대급 저점 할인")
        elif tech['w52_pct'] <= -20:
            reasons.append(f"52주고점 -20% 큰 할인 기회")
        elif tech['w52_pct'] <= -10:
            reasons.append(f"52주고점 대비 {tech['w52_pct']:.0f}% 할인")

    # RSI 과매도
    if tech['rsi'] <= 30:
        reasons.append(f"RSI {tech['rsi']:.0f} 과매도 반등 기회")

    # 당일 급등/급락
    if tech['daily_chg'] >= 5:
        reasons.append(f"당일 {tech['daily_chg']:+.1f}% 급등")

    # 최소 2개 이유 보장
    if len(reasons) < 2:
        reasons.append(f"공통종목 선정 (A+B 통과)")

    return reasons[:3]  # 최대 3개

def generate_risk(tech, rank_a, rank_b):
    """리스크 자동 생성"""
    risks = []
    is_breakout = tech['w52_pct'] > -2  # 신고가 돌파

    # RSI 과매수 (신고가 돌파가 아닐 때만 경고)
    if tech['rsi'] >= 75:
        if is_breakout:
            risks.append(f"RSI {tech['rsi']:.0f} 고점, 돌파 추세 확인 필요")
        else:
            risks.append(f"RSI {tech['rsi']:.0f} 과매수!")
    elif tech['rsi'] >= 70 and not is_breakout:
        risks.append(f"RSI {tech['rsi']:.0f} 과열")

    # 거래량 부족
    if tech['vol_ratio'] < 0.8:
        risks.append(f"거래량 {tech['vol_ratio']:.1f}x 약함")

    # 전략순위
    if rank_a > 20 and rank_b > 20:
        risks.append("전략순위 하위권")
    elif rank_a > 20 or rank_b > 20:
        risks.append("전략순위 중위권")

    # 단기 조정
    if tech['daily_chg'] < -3:
        risks.append("단기 조정 중")

    return ', '.join(risks[:2]) if risks else '특이사항 없음'

# ============================================================
# 시장 지수 가져오기
# ============================================================
start_date = (datetime.strptime(BASE_DATE, '%Y%m%d') - timedelta(days=7)).strftime('%Y%m%d')
kospi_idx = stock.get_index_ohlcv(start_date, BASE_DATE, '1001')
kosdaq_idx = stock.get_index_ohlcv(start_date, BASE_DATE, '2001')

kospi_close = kospi_idx.iloc[-1, 3]
kospi_prev = kospi_idx.iloc[-2, 3] if len(kospi_idx) > 1 else kospi_close
kospi_chg = ((kospi_close / kospi_prev) - 1) * 100

kosdaq_close = kosdaq_idx.iloc[-1, 3]
kosdaq_prev = kosdaq_idx.iloc[-2, 3] if len(kosdaq_idx) > 1 else kosdaq_close
kosdaq_chg = ((kosdaq_close / kosdaq_prev) - 1) * 100

# 시장 상태
if kospi_chg > 1:
    market_color = "🟢"
    market_status = "상승장 (GREEN)"
elif kospi_chg < -1:
    market_color = "🔴"
    market_status = "하락장 (RED)"
else:
    market_color = "🟡"
    market_status = "보합장 (NEUTRAL)"

# MA50 상태
ma_status = ""
try:
    kospi_60d = stock.get_index_ohlcv(
        (datetime.strptime(BASE_DATE, '%Y%m%d') - timedelta(days=90)).strftime('%Y%m%d'),
        BASE_DATE, '1001'
    )
    if len(kospi_60d) >= 50:
        ma50 = kospi_60d.iloc[-50:, 3].mean()
        ma_status = " ⚠️MA50 하회" if kospi_close < ma50 else " ✅MA50 상회"
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

# 전략 순위 딕셔너리
a_ranks = dict(zip(a['종목코드'], a['마법공식_순위']))
b_ranks = dict(zip(b['종목코드'], b['멀티팩터_순위']))

print(f"공통종목: {len(common_today)}개")

# ============================================================
# 공통종목 분석 및 순위 계산
# ============================================================
print("\n공통종목 기술지표 계산 중...")
stock_analysis = []

for ticker in common_today:
    name = ticker_names.get(ticker, ticker)
    tech = get_stock_technical(ticker)

    if tech is None:
        print(f"  {name}({ticker}): 데이터 없음, 건너뜀")
        continue

    rank_a = a_ranks.get(ticker, 31)
    rank_b = b_ranks.get(ticker, 31)

    entry_score = calc_entry_score(tech['rsi'], tech['w52_pct'], tech['vol_ratio'])

    stock_analysis.append({
        'ticker': ticker,
        'name': name,
        'rank_a': rank_a,
        'rank_b': rank_b,
        'entry_score': entry_score,
        'sector': SECTOR_DB.get(ticker, '기타'),
        **tech,
        'reasons': generate_reasons(ticker, tech, rank_a, rank_b),
        'risk': generate_risk(tech, rank_a, rank_b),
    })
    print(f"  {name}: 진입 {entry_score}점, RSI {tech['rsi']:.0f}, 52주 {tech['w52_pct']:.0f}%")

# 진입점수 기준 정렬
stock_analysis.sort(key=lambda x: x['entry_score'], reverse=True)

# 순위 부여
for i, s in enumerate(stock_analysis):
    s['rank'] = i + 1

# ============================================================
# 메시지 생성
# ============================================================
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

[1단계] 밸류 - 뭘 살까? (630개 → {len(common_today)}개)
• 전략A 마법공식 30개 ∩ 전략B 멀티팩터 30개
• 공통종목 {len(common_today)}개 선정

[2단계] 가격 - 언제 살까? ({len(common_today)}개 → 순위)
• 진입점수로 정렬 (RSI↓ 52주저점↓ 거래량↑)

━━━━━━━━━━━━━━━━━━━
🏆 진입점수 기준 TOP {len(stock_analysis)} ({len(common_today)}개 공통종목)
━━━━━━━━━━━━━━━━━━━
"""

for s in stock_analysis:
    rank = s['rank']
    if rank == 1:
        medal = "🥇"
    elif rank == 2:
        medal = "🥈"
    elif rank == 3:
        medal = "🥉"
    else:
        medal = "📌"

    msg1 += f"""
{medal} {rank}위 {s['name']} ({s['ticker']}) {s['sector']}
💰 {s['price']:,.0f}원 ({s['daily_chg']:+.2f}%)
📊 진입 {s['entry_score']:.0f}점 | A순위 {s['rank_a']:.0f}위 | B순위 {s['rank_b']:.0f}위
📈 진입타이밍: RSI {s['rsi']:.0f} | 52주 {s['w52_pct']:+.0f}%
📝 선정이유:
"""
    for reason in s['reasons']:
        msg1 += f"• {reason}\n"

    msg1 += f"⚠️ 리스크: {s['risk']}\n"
    msg1 += "━━━━━━━━━━━━━━━━━━━\n"

# 핵심 추천 섹션 (자동 생성)
msg1 += "\n🎯 핵심 추천\n\n"

# 적극 매수 (진입점수 70+, 거래량 1.5x+)
active_buy = [s for s in stock_analysis if s['entry_score'] >= 70 and s['vol_ratio'] >= 1.5]
if active_buy:
    msg1 += "✅ 적극 매수 (진입점수 70+, 거래량↑)\n"
    for s in active_buy[:2]:
        msg1 += f"• {s['name']} - 진입{s['entry_score']:.0f}점, 거래량{s['vol_ratio']:.1f}x\n"
    msg1 += "\n"

# 저점 매수 (52주 -30% 이하)
low_buy = [s for s in stock_analysis if s['w52_pct'] <= -30]
if low_buy:
    msg1 += "💰 저점 매수 기회 (52주 -30% 이하)\n"
    for s in low_buy[:2]:
        msg1 += f"• {s['name']} - 52주 {s['w52_pct']:.0f}%\n"
    msg1 += "  ⚠️ RSI 확인 후 분할매수 권장\n\n"

# 조정 대기 (RSI 75+)
wait_list = [s for s in stock_analysis if s['rsi'] >= 75]
if wait_list:
    msg1 += "⏸️ 조정 대기 (RSI 75+ 과매수)\n"
    for s in wait_list[:2]:
        msg1 += f"• {s['name']} (RSI {s['rsi']:.0f})\n"

msg1 += "\n━━━━━━━━━━━━━━━━━━━\n"

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

    tech = get_stock_technical(ticker)
    if tech:
        price, chg = tech['price'], tech['daily_chg']
    else:
        price, chg = 0, 0

    if i == 0:
        rank_icon = "🥇"
    elif i == 1:
        rank_icon = "🥈"
    elif i == 2:
        rank_icon = "🥉"
    else:
        rank_icon = f"{i+1:2d}."

    msg2 += f"{rank_icon} {name} {is_common} | {price:,.0f}원 ({chg:+.1f}%)\n"

msg2 += "━━━━━━━━━━━━━━━━━━━\n"

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

    tech = get_stock_technical(ticker)
    if tech:
        price, chg = tech['price'], tech['daily_chg']
    else:
        price, chg = 0, 0

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
print('\n완료!')
