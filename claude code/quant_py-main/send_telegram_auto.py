"""
한국주식 퀀트 포트폴리오 텔레그램 메시지 v3.0
통합 포트폴리오 CSV 기반 2개 메시지 전송

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

# 섹터 데이터베이스
SECTOR_DB = {
    '000660': 'AI반도체/메모리',
    '001060': '바이오/제약',
    '002380': '건자재/도료',
    '005180': '식품',
    '006910': '원전/발전설비',
    '008770': '면세점/호텔',
    '017800': '승강기/기계',
    '018290': 'K-뷰티',
    '019180': '자동차부품/와이어링',
    '033100': '변압기/전력',
    '033500': 'LNG단열재',
    '033530': '건설/플랜트',
    '035900': '엔터/K-POP',
    '036620': '아웃도어패션',
    '039130': '여행',
    '041510': '엔터/K-POP',
    '043260': '전자부품',
    '052400': '디지털화폐/핀테크',
    '067160': '스트리밍',
    '067290': '바이오/제약',
    '084670': '자동차부품',
    '088130': '디스플레이장비',
    '098120': '반도체/패키징',
    '100840': '방산/에너지',
    '119850': '에너지/발전설비',
    '123330': 'K-뷰티/화장품',
    '123410': '자동차부품',
    '124500': 'IT/금거래',
    '190510': '로봇/센서',
    '200670': '의료기기/필러',
    '204620': '택스리펀드/면세',
    '206650': '바이오/백신',
    '223250': 'IT서비스',
    '250060': 'AI/핵융합',
    '259630': '2차전지장비',
    '259960': '게임',
    '278470': '뷰티디바이스',
    '336570': '의료기기',
    '383220': '패션/브랜드',
    '402340': '투자지주/AI반도체',
    '419530': '애니/캐릭터',
    '462870': '게임',
}

# ============================================================
# 뉴스 크롤링 및 센티먼트 분석 (구글 뉴스 RSS)
# ============================================================
import urllib.parse

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
    """구글 뉴스 RSS에서 종목 뉴스 크롤링"""
    try:
        query = urllib.parse.quote(stock_name)
        url = f'https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)

        soup = BeautifulSoup(response.text, 'xml')
        items = soup.find_all('item')

        headlines = []
        for item in items[:max_news]:
            title = item.find('title')
            if title:
                text = title.get_text(strip=True)
                if text and len(text) > 5:
                    headlines.append(text)

        all_text = ' '.join(headlines)
        positive_found = [kw for kw in POSITIVE_KEYWORDS if kw in all_text]
        negative_found = [kw for kw in NEGATIVE_KEYWORDS if kw in all_text]

        def clean_headline(headline, stock_name):
            clean = headline
            clean = re.sub(rf'[,·|\s\-]*{re.escape(stock_name)}(도|는|가|이|을|를|의|에|와|과)?[,·|\s\-]*', ' ', clean)
            if ' - ' in clean:
                clean = clean.split(' - ')[0].strip()
            clean = re.sub(r'\[[^\]]+\]', '', clean)

            if re.search(r'주가.*장중|장중.*주가', clean):
                return None
            if re.search(r'주가\s*\d+월\s*\d+일', clean):
                return None
            if re.search(r'^[+\-]?\d+\.?\d*%\s*(상승|하락|급등|급락|VI|발동)', clean):
                return None
            if re.search(r'\d+\.?\d*%\s*(상승|하락)\s*마감', clean):
                return None
            if re.search(r'상승폭\s*(확대|축소)|하락폭\s*(확대|축소)', clean):
                return None

            clean = re.sub(r"''\s*|''\s*", '', clean)
            clean = re.sub(r'""\s*|""\s*', '', clean)
            clean = re.sub(r'[·,\s]{2,}', ' ', clean)
            clean = clean.strip('[]()…·""\'\'", -')
            clean = re.sub(r'^[,·\s]+', '', clean)

            return clean if len(clean) > 5 else None

        def is_relevant(headline, stock_name):
            """헤드라인이 해당 종목과 관련있는지 확인"""
            # 채용공고 필터
            if re.search(r'채용|고용24|채용정보|구인|입사', headline):
                return False
            # 다종목 나열 필터 (·로 3개 이상 회사명 나열)
            if headline.count('·') >= 3:
                return False
            # 종목명이 원본에 없으면 무관한 뉴스
            if stock_name not in headline:
                return False
            # "vs" 패턴으로 다른 종목과 비교하는 기사 (종목 자체 분석이 아님)
            if re.search(r'vs\s+\S+\s+vs', headline, re.IGNORECASE):
                return False
            return True

        summary = None
        for hl in headlines[:8]:
            if not is_relevant(hl, stock_name):
                continue
            cleaned = clean_headline(hl, stock_name)
            if cleaned:
                if len(cleaned) > 35:
                    cleaned = cleaned[:34] + '..'
                if len(negative_found) > len(positive_found):
                    summary = f"📰⚠️ {cleaned}"
                else:
                    summary = f"📰 {cleaned}"
                break

        return {
            'headlines': headlines,
            'positive': len(positive_found),
            'negative': len(negative_found),
            'positive_keywords': positive_found,
            'negative_keywords': negative_found,
            'summary': summary
        }
    except Exception as e:
        return {
            'headlines': [], 'positive': 0, 'negative': 0,
            'positive_keywords': [], 'negative_keywords': [],
            'summary': None
        }

# ============================================================
# 날짜 자동 계산 (한국 시간 기준)
# ============================================================
from zoneinfo import ZoneInfo
KST = ZoneInfo('Asia/Seoul')

def get_korea_now():
    return datetime.now(KST)

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

TODAY = get_korea_now().strftime('%Y%m%d')
BASE_DATE = get_previous_trading_date(TODAY)

print(f"오늘: {TODAY}, 분석기준일: {BASE_DATE}")

if BASE_DATE is None:
    print("거래일을 찾을 수 없습니다.")
    sys.exit(1)

# ============================================================
# 기술 지표 계산 함수
# ============================================================
def calc_rsi(prices, period=14):
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
        start = (datetime.strptime(BASE_DATE, '%Y%m%d') - timedelta(days=365)).strftime('%Y%m%d')
        ohlcv = stock.get_market_ohlcv(start, BASE_DATE, ticker_str)

        if ohlcv.empty or len(ohlcv) < 20:
            return None

        price = ohlcv.iloc[-1]['종가']
        prev_price = ohlcv.iloc[-2]['종가'] if len(ohlcv) >= 2 else price
        daily_chg = (price / prev_price - 1) * 100
        rsi = calc_rsi(ohlcv['종가'])
        high_52w = ohlcv['고가'].max()
        w52_pct = (price / high_52w - 1) * 100
        current_vol = ohlcv.iloc[-1]['거래량']
        avg_vol = ohlcv['거래량'].tail(20).mean()
        vol_ratio = current_vol / avg_vol if avg_vol > 0 else 1

        return {
            'price': price, 'daily_chg': daily_chg,
            'rsi': rsi, 'w52_pct': w52_pct, 'vol_ratio': vol_ratio,
        }
    except Exception as e:
        print(f"  기술지표 계산 실패 {ticker_str}: {e}")
        return None


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

if kospi_chg > 1:
    market_color = "🟢"
    market_status = "상승장 (GREEN)"
elif kospi_chg < -1:
    market_color = "🔴"
    market_status = "하락장 (RED)"
else:
    market_color = "🟡"
    market_status = "보합장 (NEUTRAL)"

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

market_rsi = 50
try:
    kospi_30d = stock.get_index_ohlcv(
        (datetime.strptime(BASE_DATE, '%Y%m%d') - timedelta(days=45)).strftime('%Y%m%d'),
        BASE_DATE, '1001'
    )
    if len(kospi_30d) >= 15:
        market_rsi = calc_rsi(kospi_30d.iloc[:, 3])
        print(f"시장 RSI (KOSPI): {market_rsi:.1f}")
except Exception as e:
    print(f"시장 RSI 계산 실패: {e}")

# ============================================================
# 통합 포트폴리오 CSV 로드
# ============================================================
import glob

# 최신 통합 포트폴리오 파일 찾기
portfolio_files = sorted(glob.glob(str(OUTPUT_DIR / 'portfolio_*.csv')), reverse=True)
# strategy_a/b 파일 제외 (이전 버전 호환)
portfolio_files = [f for f in portfolio_files if 'strategy_' not in f and 'report' not in f]

if not portfolio_files:
    print("통합 포트폴리오 파일을 찾을 수 없습니다. create_current_portfolio.py를 먼저 실행하세요.")
    sys.exit(1)

print(f"포트폴리오 파일: {Path(portfolio_files[0]).name}")

portfolio = pd.read_csv(portfolio_files[0], encoding='utf-8-sig')
portfolio['종목코드'] = portfolio['종목코드'].astype(str).str.zfill(6)

# 종목명/순위 딕셔너리
ticker_names = dict(zip(portfolio['종목코드'], portfolio['종목명']))

# 통합순위 우선, 없으면 멀티팩터_순위 사용
if '통합순위' in portfolio.columns:
    portfolio_ranks = dict(zip(portfolio['종목코드'], portfolio['통합순위']))
    rank_label = '통합순위'
elif '멀티팩터_순위' in portfolio.columns:
    portfolio_ranks = dict(zip(portfolio['종목코드'], portfolio['멀티팩터_순위']))
    rank_label = '멀티팩터_순위'
else:
    portfolio_ranks = {t: i+1 for i, t in enumerate(portfolio['종목코드'])}
    rank_label = '순위'

# PER/PBR/ROE 정보
portfolio_per = dict(zip(portfolio['종목코드'], portfolio.get('PER', pd.Series()))) if 'PER' in portfolio.columns else {}
portfolio_pbr = dict(zip(portfolio['종목코드'], portfolio.get('PBR', pd.Series()))) if 'PBR' in portfolio.columns else {}
portfolio_roe = dict(zip(portfolio['종목코드'], portfolio.get('ROE', pd.Series()))) if 'ROE' in portfolio.columns else {}

print(f"포트폴리오: {len(portfolio)}개 종목 ({rank_label} 기준)")

# ============================================================
# 전 종목 기술지표 분석 (참고 정보)
# ============================================================
print("\n포트폴리오 기술지표 계산 중...")
stock_analysis = []

for _, row in portfolio.iterrows():
    ticker = row['종목코드']
    name = row['종목명']
    tech = get_stock_technical(ticker)

    if tech is None:
        print(f"  {name}({ticker}): 데이터 없음, 건너뜀")
        continue

    rank = portfolio_ranks.get(ticker, 31)
    news = get_stock_news(ticker, name)
    news_str = ""
    if news.get('headlines'):
        first_headline = news['headlines'][0][:30] + '..' if len(news['headlines'][0]) > 30 else news['headlines'][0]
        sentiment = "⚠️" if news['negative'] > news['positive'] else ""
        news_str = f" | {sentiment}{first_headline}"

    stock_analysis.append({
        'ticker': ticker,
        'name': name,
        'rank': rank,
        'per': portfolio_per.get(ticker, None),
        'pbr': portfolio_pbr.get(ticker, None),
        'roe': portfolio_roe.get(ticker, None),
        'sector': SECTOR_DB.get(ticker, '기타'),
        'news': news,
        **tech,
    })
    print(f"  {name}: {rank_label} {rank:.0f}위, RSI {tech['rsi']:.0f}, 52주 {tech['w52_pct']:.0f}%{news_str}")

# 통합순위 기준 정렬
stock_analysis.sort(key=lambda x: x['rank'])

# ============================================================
# 메시지 1: 시장개황 + TOP 10 상세분석
# ============================================================
today_str = f"{TODAY[4:6]}월{TODAY[6:]}일"
base_date_str = f"{BASE_DATE[:4]}년 {BASE_DATE[4:6]}월 {BASE_DATE[6:]}일"
n_total = len(stock_analysis)

msg1 = f"""안녕하세요! 오늘({today_str}) 한국주식 퀀트 포트폴리오입니다 📊

━━━━━━━━━━━━━━━━━━━
📅 {base_date_str} 기준 분석
{market_color} {market_status}
• 코스피 {kospi_close:,.0f} ({kospi_chg:+.2f}%){ma_status}
• 코스닥 {kosdaq_close:,.0f} ({kosdaq_chg:+.2f}%)
━━━━━━━━━━━━━━━━━━━

💡 전략 v3.1

• 유니버스: 시총1000억↑ 거래대금30억↑ 약 600개

[1단계] 마법공식 사전필터 → 상위 150개
• 이익수익률↑ + ROIC↑ = 근본 우량주 선별

[2단계] 통합순위 → 최종 {n_total}개
• 마법공식 30% + 멀티팩터 70%
• 멀티팩터: Value + Quality + Momentum
• PER/PBR: pykrx 실시간 데이터

━━━━━━━━━━━━━━━━━━━
🏆 통합순위 TOP 20
━━━━━━━━━━━━━━━━━━━
"""

def format_stock_detail(s):
    """종목 상세 포맷"""
    rank = int(s['rank'])
    if rank == 1:
        medal = "🥇"
    elif rank == 2:
        medal = "🥈"
    elif rank == 3:
        medal = "🥉"
    else:
        medal = "📌"

    factor_parts = []
    if s.get('per') and not pd.isna(s['per']):
        factor_parts.append(f"PER {s['per']:.1f}")
    if s.get('pbr') and not pd.isna(s['pbr']):
        factor_parts.append(f"PBR {s['pbr']:.1f}")
    if s.get('roe') and not pd.isna(s['roe']):
        factor_parts.append(f"ROE {s['roe']:.1f}%")
    factor_str = ' | '.join(factor_parts) if factor_parts else ''

    block = f"""
{medal} {rank}위 {s['name']} ({s['ticker']}) {s['sector']}
💰 {s['price']:,.0f}원 ({s['daily_chg']:+.2f}%)
📊 {factor_str}
📈 RSI {s['rsi']:.0f} | 52주 {s['w52_pct']:+.0f}%
"""
    if s.get('news') and s['news'].get('summary'):
        block += f"📰 {s['news']['summary'].replace('📰 ', '').replace('📰⚠️ ', '⚠️')}\n"
    block += "━━━━━━━━━━━━━━━━━━━\n"
    return block

# TOP 20을 msg1, msg1b로 분할 (텔레그램 4096자 제한)
top_n = min(20, len(stock_analysis))
msg1b = None

for i, s in enumerate(stock_analysis[:top_n]):
    block = format_stock_detail(s)
    # 4000자 근처에서 msg1b로 분할
    if msg1b is None and len(msg1) + len(block) > 3800 and i > 0:
        msg1b = f"🏆 통합순위 TOP 20 (계속)\n━━━━━━━━━━━━━━━━━━━\n"
    if msg1b is not None:
        msg1b += block
    else:
        msg1 += block

# ============================================================
# 메시지 2: 전체 30종목 간략 순위
# ============================================================
# 전송할 메시지 목록 구성
messages = [msg1]
if msg1b:
    messages.append(msg1b)

# ============================================================
# 텔레그램 전송
# ============================================================
import os
url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'

PRIVATE_CHAT_ID = getattr(__import__('config'), 'TELEGRAM_PRIVATE_ID', None)
IS_GITHUB_ACTIONS = os.environ.get('GITHUB_ACTIONS') == 'true'

print("\n=== 메시지 미리보기 ===")
print(msg1[:2000])
if msg1b:
    print("\n--- msg1b ---")
    print(msg1b[:1000])
print("\n... (생략)")
print(f"메시지 수: {len(messages)}개 (msg1: {len(msg1)}자{f', msg1b: {len(msg1b)}자' if msg1b else ''})")

if IS_GITHUB_ACTIONS:
    # GitHub Actions: 채널 + 개인
    results = []
    for msg in messages:
        r = requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': msg})
        results.append(r.status_code)
    print(f'\n채널 메시지 전송: {", ".join(map(str, results))}')

    if PRIVATE_CHAT_ID:
        results_p = []
        for msg in messages:
            r = requests.post(url, data={'chat_id': PRIVATE_CHAT_ID, 'text': msg})
            results_p.append(r.status_code)
        print(f'개인 메시지 전송: {", ".join(map(str, results_p))}')
else:
    # 로컬 테스트: 개인채팅만
    target_id = PRIVATE_CHAT_ID or TELEGRAM_CHAT_ID
    results = []
    for msg in messages:
        r = requests.post(url, data={'chat_id': target_id, 'text': msg})
        results.append(r.status_code)
    print(f'\n테스트 메시지 전송: {", ".join(map(str, results))}')

# 히스토리 저장
history = {
    'date': TODAY,
    'portfolio': [s['ticker'] for s in stock_analysis],
    'ticker_names': ticker_names
}
with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
    json.dump(history, f, ensure_ascii=False, indent=2)

print(f'\n히스토리 저장: {HISTORY_FILE}')
print(f'포트폴리오: {len(stock_analysis)}개 종목')
print('\n완료!')
