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
import re
from bs4 import BeautifulSoup
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
# 뉴스 크롤링 및 센티먼트 분석 (구글 뉴스 RSS)
# ============================================================
import urllib.parse

# 긍정/부정 키워드
POSITIVE_KEYWORDS = [
    '호실적', '상향', '흑자', '신고가', '계약', '수주', '성장', '개선',
    '증가', '확대', '돌파', '상승', '최대', '신규', '진출', '협력',
    '투자', '기대', '긍정', '매수', '목표가', '상향조정', '실적개선',
    '급등', '강세', '호재', '수혜', '낙관'
]
NEGATIVE_KEYWORDS = [
    '하향', '적자', '감소', '하락', '소송', '리콜', '손실', '감자',
    '위기', '우려', '부진', '악화', '철수', '중단', '폐쇄', '매도',
    '목표가하향', '실적악화', '경고', '조사', '제재', '급락', '약세',
    '악재', '피해', '비관'
]

def get_stock_news(ticker, stock_name, max_news=10):
    """
    구글 뉴스 RSS에서 종목 뉴스 크롤링

    Returns:
        {
            'headlines': [뉴스 제목 리스트],
            'positive': 긍정 키워드 개수,
            'negative': 부정 키워드 개수,
            'summary': 요약 문자열
        }
    """
    try:
        query = urllib.parse.quote(stock_name)
        url = f'https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)

        soup = BeautifulSoup(response.text, 'xml')
        items = soup.find_all('item')

        # 뉴스 제목 추출
        headlines = []
        for item in items[:max_news]:
            title = item.find('title')
            if title:
                text = title.get_text(strip=True)
                if text and len(text) > 5:
                    headlines.append(text)

        # 센티먼트 분석
        all_text = ' '.join(headlines)
        positive_found = [kw for kw in POSITIVE_KEYWORDS if kw in all_text]
        negative_found = [kw for kw in NEGATIVE_KEYWORDS if kw in all_text]

        positive_count = len(positive_found)
        negative_count = len(negative_found)

        # 헤드라인에서 종목명 제거하고 핵심 내용만 추출
        def clean_headline(headline, stock_name):
            import re
            clean = headline

            # 종목명 제거 (앞뒤 구분자 + 조사 포함: 도, 는, 가, 이, 을, 를, 의 등)
            clean = re.sub(rf'[,·|\s]*{re.escape(stock_name)}(도|는|가|이|을|를|의|에|와|과)?[,·|\s]*', ' ', clean)

            # " - 언론사" 패턴 제거
            if ' - ' in clean:
                clean = clean.split(' - ')[0].strip()

            # [단독], [속보], [클릭 e종목] 등 태그 제거
            clean = re.sub(r'\[[^\]]+\]', '', clean)

            # 무의미한 시세 뉴스 필터
            if re.search(r'주가.*장중|장중.*주가', clean):
                return None
            # "주가 X월 X일" 패턴 필터
            if re.search(r'주가\s*\d+월\s*\d+일', clean):
                return None
            # "+X.X% 상승/하락" 패턴 필터
            if re.search(r'^[+\-]?\d+\.?\d*%\s*(상승|하락|급등|급락|VI|발동)', clean):
                return None
            # "X.XX% 상승/하락 마감" 패턴 필터
            if re.search(r'\d+\.?\d*%\s*(상승|하락)\s*마감', clean):
                return None
            # "상승폭 확대/축소" 패턴 필터
            if re.search(r'상승폭\s*(확대|축소)|하락폭\s*(확대|축소)', clean):
                return None

            # 빈 따옴표 '' "" 제거
            clean = re.sub(r"''\s*|''\s*", '', clean)
            clean = re.sub(r'""\s*|""\s*', '', clean)

            # 연속 특수문자 정리 (··, ,,  등)
            clean = re.sub(r'[·,\s]{2,}', ' ', clean)

            # 앞뒤 특수문자, 쉼표, 공백 정리
            clean = clean.strip('[]()…·""\'\'", ')
            clean = re.sub(r'^[,·\s]+', '', clean)

            return clean if len(clean) > 5 else None

        # 의미있는 헤드라인 찾기 (시세 뉴스 제외)
        summary = None
        for hl in headlines[:5]:  # 최대 5개까지 확인
            cleaned = clean_headline(hl, stock_name)
            if cleaned:
                # 35자로 늘림 (더 많은 맥락 제공)
                if len(cleaned) > 35:
                    cleaned = cleaned[:34] + '..'
                if negative_count > positive_count:
                    summary = f"📰⚠️ {cleaned}"
                else:
                    summary = f"📰 {cleaned}"
                break

        return {
            'headlines': headlines,
            'positive': positive_count,
            'negative': negative_count,
            'positive_keywords': positive_found,
            'negative_keywords': negative_found,
            'summary': summary
        }
    except Exception as e:
        return {
            'headlines': [],
            'positive': 0,
            'negative': 0,
            'positive_keywords': [],
            'negative_keywords': [],
            'summary': None
        }

# ============================================================
# 날짜 자동 계산 (한국 시간 기준)
# ============================================================
from zoneinfo import ZoneInfo
KST = ZoneInfo('Asia/Seoul')

def get_korea_now():
    """한국 시간 기준 현재 시각"""
    return datetime.now(KST)

def get_latest_trading_date():
    """최근 거래일 찾기 (오늘 또는 어제)"""
    now = get_korea_now()
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

# 날짜 설정 (한국 시간 기준)
# 인사: 오늘 날짜 (KST)
# 분석: 오늘 기준 직전 영업일 (오늘 제외)
TODAY = get_korea_now().strftime('%Y%m%d')
BASE_DATE = get_previous_trading_date(TODAY)  # 오늘 기준 직전 영업일

print(f"오늘: {TODAY}, 분석기준일: {BASE_DATE}")

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

    철학: 좋은 사과를 싸게 사자!
    - RSI 낮을수록 좋음 (싸게)
    - 52주 고점 대비 할인 클수록 좋음 (싸게)
    - 신고가 돌파는 감점 안 함 (중립), 보너스도 없음

    구성:
    - RSI (40점): 과매도일수록 좋음
    - 52주 위치 (30점): 할인 클수록 좋음
    - 거래량 (20점): 스파이크 확인
    - 기본 점수 (10점): 통과 종목 기본
    """
    # 신고가 돌파 판단 (52주 고점 -2% 이내)
    is_breakout = w52_pct > -2

    # RSI (40점) - 낮을수록 좋음
    if rsi <= 30:
        rsi_score = 40  # 과매도 - 최고 매수 기회
    elif rsi <= 50:
        rsi_score = 30  # 양호
    elif rsi <= 70:
        rsi_score = 20  # 중립
    else:
        # RSI > 70
        if is_breakout:
            rsi_score = 20  # 신고가 돌파시 감점 안 함 (중립)
        else:
            rsi_score = 10  # 일반 과매수 위험

    # 52주 고점 대비 (30점) - 할인 클수록 좋음
    if w52_pct <= -20:
        w52_score = 30  # 큰 할인 - 최고
    elif w52_pct <= -10:
        w52_score = 25  # 의미있는 할인
    elif w52_pct <= -5:
        w52_score = 20  # 적당한 조정
    elif is_breakout:
        w52_score = 15  # 신고가 돌파 - 감점 안 함 (중립)
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

def generate_reasons(ticker, tech, rank_a, rank_b, news=None):
    """선정이유 자동 생성 (뉴스 포함)"""
    reasons = []
    is_breakout = tech['w52_pct'] > -2  # 신고가 돌파

    # 신고가 돌파 모멘텀
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

def generate_risk(tech, rank_a, rank_b, news=None):
    """리스크 자동 생성 (뉴스 포함)"""
    risks = []
    is_breakout = tech['w52_pct'] > -2  # 신고가 돌파

    # 뉴스 부정적이면 경고 (간략하게)
    if news and news.get('negative', 0) > news.get('positive', 0):
        risks.append("뉴스 부정적⚠️")

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

# 시장 RSI 계산 (KOSPI 기준)
market_rsi = 50  # 기본값
try:
    kospi_30d = stock.get_index_ohlcv(
        (datetime.strptime(BASE_DATE, '%Y%m%d') - timedelta(days=45)).strftime('%Y%m%d'),
        BASE_DATE, '1001'
    )
    if len(kospi_30d) >= 15:
        market_rsi = calc_rsi(kospi_30d.iloc[:, 3])  # 종가 컬럼
        print(f"시장 RSI (KOSPI): {market_rsi:.1f}")
except Exception as e:
    print(f"시장 RSI 계산 실패: {e}")

# ============================================================
# 포트폴리오 결과 로드 (최신 파일 자동 탐색)
# ============================================================
import glob

# 최신 전략 A/B 파일 찾기
strategy_a_files = sorted(glob.glob(str(OUTPUT_DIR / 'portfolio_*_strategy_a.csv')), reverse=True)
strategy_b_files = sorted(glob.glob(str(OUTPUT_DIR / 'portfolio_*_strategy_b.csv')), reverse=True)

if not strategy_a_files or not strategy_b_files:
    print("포트폴리오 파일을 찾을 수 없습니다. create_current_portfolio.py를 먼저 실행하세요.")
    sys.exit(1)

print(f"전략A 파일: {Path(strategy_a_files[0]).name}")
print(f"전략B 파일: {Path(strategy_b_files[0]).name}")

a = pd.read_csv(strategy_a_files[0], encoding='utf-8-sig')
b = pd.read_csv(strategy_b_files[0], encoding='utf-8-sig')

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
    relative_rsi = tech['rsi'] - market_rsi  # 상대 RSI 계산

    # 뉴스 크롤링
    news = get_stock_news(ticker, name)
    news_str = ""
    if news.get('headlines'):
        first_headline = news['headlines'][0][:30] + '..' if len(news['headlines'][0]) > 30 else news['headlines'][0]
        sentiment = "⚠️" if news['negative'] > news['positive'] else ""
        news_str = f" | {sentiment}{first_headline}"

    stock_analysis.append({
        'ticker': ticker,
        'name': name,
        'rank_a': rank_a,
        'rank_b': rank_b,
        'entry_score': entry_score,
        'sector': SECTOR_DB.get(ticker, '기타'),
        'relative_rsi': relative_rsi,
        'news': news,
        **tech,
        'reasons': generate_reasons(ticker, tech, rank_a, rank_b, news),
        'risk': generate_risk(tech, rank_a, rank_b, news),
    })
    print(f"  {name}: 진입 {entry_score}점, RSI {tech['rsi']:.0f} (상대 {relative_rsi:+.0f}), 52주 {tech['w52_pct']:.0f}%{news_str}")

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
"""
    # 주요 뉴스 (있을 경우만)
    if s.get('news') and s['news'].get('summary'):
        msg1 += f"📰 주요뉴스: {s['news']['summary'].replace('📰 ', '').replace('📰⚠️ ', '⚠️')}\n"

    msg1 += "📝 선정이유: "
    msg1 += ' / '.join(s['reasons']) + "\n"

    msg1 += f"⚠️ 리스크: {s['risk']}\n"
    msg1 += "━━━━━━━━━━━━━━━━━━━\n"


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
• 분기별 리밸런싱 권장 (4/5/8/11월)
━━━━━━━━━━━━━━━━━━━
📊 Quant Portfolio v2.0
"""

# ============================================================
# 텔레그램 전송
# ============================================================
import os
url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'

# 개인 채팅 ID (전체 메시지)
PRIVATE_CHAT_ID = getattr(__import__('config'), 'TELEGRAM_PRIVATE_ID', None)

# GitHub Actions 환경인지 확인
IS_GITHUB_ACTIONS = os.environ.get('GITHUB_ACTIONS') == 'true'

print("\n=== 메시지 미리보기 ===")
print(msg1[:2000])
print("\n... (생략)")

if IS_GITHUB_ACTIONS:
    # GitHub Actions: 채널(공통종목) + 개인(전체)
    r1 = requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': msg1})
    print(f'\n채널 메시지 전송: {r1.status_code}')

    if PRIVATE_CHAT_ID:
        r_p1 = requests.post(url, data={'chat_id': PRIVATE_CHAT_ID, 'text': msg1})
        r_p2 = requests.post(url, data={'chat_id': PRIVATE_CHAT_ID, 'text': msg2})
        r_p3 = requests.post(url, data={'chat_id': PRIVATE_CHAT_ID, 'text': msg3})
        print(f'개인 메시지 전송: {r_p1.status_code}, {r_p2.status_code}, {r_p3.status_code}')
else:
    # 로컬 테스트: 개인채팅만 (전체 메시지)
    target_id = PRIVATE_CHAT_ID or TELEGRAM_CHAT_ID
    r1 = requests.post(url, data={'chat_id': target_id, 'text': msg1})
    r2 = requests.post(url, data={'chat_id': target_id, 'text': msg2})
    r3 = requests.post(url, data={'chat_id': target_id, 'text': msg3})
    print(f'\n테스트 메시지 전송: {r1.status_code}, {r2.status_code}, {r3.status_code}')

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
