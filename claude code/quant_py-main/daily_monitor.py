"""
일별 포트폴리오 모니터링 및 진입 타이밍 분석 v6.4
- Quality(품질) + Price(타이밍) 2축 점수 체계
- 4분류: 모멘텀/눌림목/관망/금지
- TOP 3 + 한줄 결론
- 텔레그램 v6.4 포맷
"""

import pandas as pd
import numpy as np
from pykrx import stock
from datetime import datetime, timedelta
from pathlib import Path
import json
import subprocess
import requests
import warnings
import time
import sys
import io

# Windows 콘솔 UTF-8 설정
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

warnings.filterwarnings('ignore')

# ============================================================================
# 설정
# ============================================================================

BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / 'output'
DAILY_DIR = BASE_DIR / 'daily_reports'
DAILY_DIR.mkdir(exist_ok=True)

# 설정 로드
try:
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GIT_AUTO_PUSH
except ImportError:
    TELEGRAM_BOT_TOKEN = ""
    TELEGRAM_CHAT_ID = ""
    GIT_AUTO_PUSH = True

# v6.4 점수 기준
QUALITY_EXCELLENT = 75  # 품질 우수
QUALITY_GOOD = 50       # 품질 양호
PRICE_EXCELLENT = 75    # 타이밍 우수
PRICE_GOOD = 50         # 타이밍 양호

# ============================================================================
# 포트폴리오 종목 로드
# ============================================================================

def load_portfolio_stocks():
    """전략 A, B, C에서 선정된 종목 로드"""

    stocks = {}

    # 전략 A 종목 (30개)
    strategy_a_file = OUTPUT_DIR / 'portfolio_2026_01_strategy_a.csv'
    if strategy_a_file.exists():
        df_a = pd.read_csv(strategy_a_file, dtype={'종목코드': str})
        for _, row in df_a.head(30).iterrows():
            ticker = str(row['종목코드']).zfill(6)
            stocks[ticker] = {
                'name': row.get('종목명', ''),
                'strategy': 'A',
                'ey': row.get('이익수익률', 0),
                'roc': row.get('투하자본수익률', 0),
                'net_income': row.get('당기순이익', 0),
                'equity': row.get('자본', 0),
            }

    # 전략 B 종목 (30개)
    strategy_b_file = OUTPUT_DIR / 'portfolio_2026_01_strategy_b.csv'
    if strategy_b_file.exists():
        df_b = pd.read_csv(strategy_b_file, dtype={'종목코드': str})
        for _, row in df_b.head(30).iterrows():
            ticker = str(row['종목코드']).zfill(6)
            if ticker in stocks:
                stocks[ticker]['strategy'] = 'A+B'
                stocks[ticker]['mf_score'] = row.get('멀티팩터_점수', 0)
            else:
                stocks[ticker] = {
                    'name': row.get('종목명', ''),
                    'strategy': 'B',
                    'mf_score': row.get('멀티팩터_점수', 0),
                    'net_income': row.get('당기순이익', 0),
                    'equity': row.get('자본', 0),
                }

    # 전략 C 종목 (Forward EPS Hybrid)
    strategy_c_file = OUTPUT_DIR / 'portfolio_2026_01_strategy_c.csv'
    if strategy_c_file.exists():
        df_c = pd.read_csv(strategy_c_file, dtype={'종목코드': str})
        for _, row in df_c.head(30).iterrows():
            ticker = str(row['종목코드']).zfill(6)
            if ticker in stocks:
                stocks[ticker]['strategy'] += '+C'
                stocks[ticker]['forward_eps'] = row.get('forward_eps', 0)
                stocks[ticker]['forward_per'] = row.get('forward_per', 0)
            else:
                stocks[ticker] = {
                    'name': row.get('종목명', ''),
                    'strategy': 'C',
                    'forward_eps': row.get('forward_eps', 0),
                    'forward_per': row.get('forward_per', 0),
                    'net_income': row.get('당기순이익', 0),
                    'equity': row.get('자본', 0),
                }

    return stocks


# ============================================================================
# 기술적 지표 계산
# ============================================================================

def calculate_rsi(prices, period=14):
    """RSI 계산"""
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1] if len(rsi) > 0 else 50


def calculate_bollinger_position(prices, period=20):
    """볼린저밴드 위치 (0=하단, 0.5=중앙, 1=상단)"""
    if len(prices) < period:
        return 0.5

    sma = prices.rolling(window=period).mean()
    std = prices.rolling(window=period).std()
    upper = sma + 2 * std
    lower = sma - 2 * std

    current = prices.iloc[-1]
    upper_val = upper.iloc[-1]
    lower_val = lower.iloc[-1]

    if upper_val == lower_val:
        return 0.5

    position = (current - lower_val) / (upper_val - lower_val)
    return max(0, min(1, position))


def calculate_ma_divergence(prices, period=60):
    """이동평균 이격도 (%)"""
    if len(prices) < period:
        return 0

    ma = prices.rolling(window=period).mean().iloc[-1]
    current = prices.iloc[-1]

    return ((current - ma) / ma) * 100


def get_52week_position(prices):
    """52주 대비 위치"""
    if len(prices) < 20:
        return 0.5, 0, 0

    year_prices = prices.tail(252)

    high_52w = year_prices.max()
    low_52w = year_prices.min()
    current = prices.iloc[-1]

    if high_52w == low_52w:
        return 0.5, 0, 0

    position = (current - low_52w) / (high_52w - low_52w)
    from_high = ((current - high_52w) / high_52w) * 100
    from_low = ((current - low_52w) / low_52w) * 100

    return position, from_high, from_low


def calculate_volume_signal(volumes, period=20):
    """거래량 신호 (평균 대비)"""
    if len(volumes) < period:
        return 1.0

    avg_volume = volumes.tail(period).mean()
    current_volume = volumes.iloc[-1]

    return current_volume / avg_volume if avg_volume > 0 else 1.0


def check_ma_alignment(prices):
    """이동평균 정배열 체크 (5 > 20 > 60 > 120)"""
    if len(prices) < 120:
        return False, 0

    ma5 = prices.tail(5).mean()
    ma20 = prices.tail(20).mean()
    ma60 = prices.tail(60).mean()
    ma120 = prices.tail(120).mean()

    # 정배열: 단기 > 장기
    is_aligned = ma5 > ma20 > ma60 > ma120

    # 정배열 점수 (0~100)
    alignment_score = 0
    if ma5 > ma20:
        alignment_score += 25
    if ma20 > ma60:
        alignment_score += 25
    if ma60 > ma120:
        alignment_score += 25
    if is_aligned:
        alignment_score += 25  # 완전 정배열 보너스

    return is_aligned, alignment_score


def is_near_52w_high(from_high, threshold=-10):
    """52주 신고가 근처 여부"""
    return from_high >= threshold


def is_volume_breakout(volume_signal, threshold=1.5):
    """거래량 돌파 여부"""
    return volume_signal >= threshold


# ============================================================================
# 실시간 밸류에이션
# ============================================================================

def calculate_realtime_valuation(ticker, current_price, stock_info):
    """실시간 PER, PBR 계산"""

    try:
        today = datetime.now().strftime('%Y%m%d')

        for i in range(10):
            check_date = (datetime.now() - timedelta(days=i)).strftime('%Y%m%d')
            try:
                mcap_df = stock.get_market_cap(check_date, check_date, ticker)
                if not mcap_df.empty:
                    shares = mcap_df['상장주식수'].iloc[0]
                    break
            except:
                continue
        else:
            shares = 0

        if shares > 0:
            market_cap = current_price * shares / 100_000_000  # 억원
        else:
            market_cap = 0

        net_income = stock_info.get('net_income', 0)
        equity = stock_info.get('equity', 0)

        per = market_cap / net_income if net_income > 0 else 999
        pbr = market_cap / equity if equity > 0 else 999

        return {
            'market_cap': market_cap,
            'per': per,
            'pbr': pbr,
        }

    except Exception as e:
        return {'market_cap': 0, 'per': 999, 'pbr': 999}


# ============================================================================
# v6.4 점수 계산 - Quality(품질) + Price(타이밍) 2축 체계
# ============================================================================

def calculate_quality_score(stock_info, indicators):
    """
    Quality Score (품질) - 펀더멘털 매력도 (0~100)

    구성:
    - 전략 등급 (25%): A+B > A or B
    - PER 점수 (25%): 낮을수록 높음
    - ROE 점수 (20%): 높을수록 높음
    - 52주 회복 여력 (15%): 고점 대비 하락폭
    - 정배열 점수 (15%): 추세 건강도
    """
    scores = {}

    # 1. 전략 등급 점수 (25%)
    strategy = stock_info.get('strategy', '')
    if 'A+B' in strategy or '+C' in strategy:
        scores['strategy'] = 100  # 복수 전략 선정
    elif strategy in ['A', 'B', 'C']:
        scores['strategy'] = 70
    else:
        scores['strategy'] = 50

    # 2. PER 점수 (25%) - 낮을수록 좋음
    per = indicators.get('per', 999)
    if per <= 5:
        scores['per'] = 100
    elif per <= 8:
        scores['per'] = 90
    elif per <= 12:
        scores['per'] = 75
    elif per <= 15:
        scores['per'] = 60
    elif per <= 20:
        scores['per'] = 40
    elif per <= 30:
        scores['per'] = 20
    else:
        scores['per'] = 10

    # 3. ROE 점수 (20%)
    roc = stock_info.get('roc', 0)
    ey = stock_info.get('ey', 0)
    roe_proxy = max(roc, ey * 100) if roc or ey else 0

    if roe_proxy >= 30:
        scores['roe'] = 100
    elif roe_proxy >= 20:
        scores['roe'] = 85
    elif roe_proxy >= 15:
        scores['roe'] = 70
    elif roe_proxy >= 10:
        scores['roe'] = 55
    elif roe_proxy >= 5:
        scores['roe'] = 40
    else:
        scores['roe'] = 25

    # 4. 52주 회복 여력 (15%)
    from_high = indicators.get('from_52w_high', 0)
    if from_high <= -50:
        scores['recovery'] = 100  # 급락 = 반등 여력 큼
    elif from_high <= -30:
        scores['recovery'] = 80
    elif from_high <= -15:
        scores['recovery'] = 60
    elif from_high <= -5:
        scores['recovery'] = 40
    else:
        scores['recovery'] = 30  # 이미 고점 근처

    # 5. 정배열 점수 (15%)
    alignment_score = indicators.get('alignment_score', 50)
    scores['alignment'] = alignment_score

    # 가중 평균
    weights = {
        'strategy': 0.25,
        'per': 0.25,
        'roe': 0.20,
        'recovery': 0.15,
        'alignment': 0.15,
    }

    total = sum(scores.get(k, 0) * weights[k] for k in weights)
    return int(round(total)), scores


def calculate_price_score(indicators):
    """
    Price Score (타이밍) - 진입 적정성 점수 (0~100)

    핵심 변경: RSI 70~80은 "좋은 과열"로 인정 (모멘텀 플레이)

    구성:
    - RSI 점수 (30%): 30-45(저점) 또는 70-80(모멘텀)이 고득점
    - BB 위치 (20%): 하단=저점매수, 상단+거래량=돌파매수
    - 거래량 신호 (20%): 2배 이상 = 관심 신호
    - 이격도 (15%): -20% = 저평가, +30% = 위험
    - 52주 위치 (15%): 저점 or 신고가+거래량
    """
    scores = {}

    rsi = indicators.get('rsi', 50)
    bb_pos = indicators.get('bb_position', 0.5)
    volume_signal = indicators.get('volume_signal', 1.0)
    ma_div = indicators.get('ma_div_60', 0)
    from_high = indicators.get('from_52w_high', 0)

    # 1. RSI 점수 (30%) - 모멘텀 플레이 인정
    if 30 <= rsi <= 45:
        scores['rsi'] = 100  # 저점 매수 최적
    elif rsi < 30:
        scores['rsi'] = 70   # 극과매도 (바닥 확인 필요)
    elif 70 <= rsi <= 80:
        scores['rsi'] = 85   # "좋은 과열" - 모멘텀 플레이
    elif 45 < rsi < 60:
        scores['rsi'] = 60   # 중립
    elif 60 <= rsi < 70:
        scores['rsi'] = 50   # 약간 과열
    else:  # rsi > 80
        scores['rsi'] = 20   # 극과열 위험

    # 2. 볼린저밴드 점수 (20%)
    if bb_pos <= 0.2:
        scores['bb'] = 100  # 하단 = 저점 매수
    elif bb_pos <= 0.4:
        scores['bb'] = 80
    elif bb_pos >= 0.8 and volume_signal >= 1.5:
        scores['bb'] = 75   # 상단 돌파 + 거래량 = 모멘텀
    elif bb_pos >= 0.8:
        scores['bb'] = 30   # 상단 without 거래량 = 위험
    else:
        scores['bb'] = 50   # 중립

    # 3. 거래량 신호 점수 (20%)
    if volume_signal >= 3.0:
        scores['volume'] = 100  # 폭발
    elif volume_signal >= 2.0:
        scores['volume'] = 85
    elif volume_signal >= 1.5:
        scores['volume'] = 70
    elif volume_signal >= 1.0:
        scores['volume'] = 50
    else:
        scores['volume'] = 30  # 거래량 부족

    # 4. 이격도 점수 (15%)
    if ma_div <= -20:
        scores['divergence'] = 100  # 심한 저평가
    elif ma_div <= -10:
        scores['divergence'] = 80
    elif ma_div <= 0:
        scores['divergence'] = 60
    elif ma_div <= 15:
        scores['divergence'] = 40
    elif ma_div <= 30:
        scores['divergence'] = 20
    else:
        scores['divergence'] = 0  # +30% 이상 = 버블 위험

    # 5. 52주 위치 점수 (15%)
    if from_high >= -5 and volume_signal >= 1.5:
        scores['52w'] = 90   # 신고가 + 거래량 = 돌파
    elif from_high <= -50:
        scores['52w'] = 100  # 급락 = 반등 기대
    elif from_high <= -30:
        scores['52w'] = 85
    elif from_high <= -15:
        scores['52w'] = 65
    elif from_high >= -5:
        scores['52w'] = 40   # 고점 but 거래량 부족
    else:
        scores['52w'] = 50

    # 가중 평균
    weights = {
        'rsi': 0.30,
        'bb': 0.20,
        'volume': 0.20,
        'divergence': 0.15,
        '52w': 0.15,
    }

    total = sum(scores.get(k, 0) * weights[k] for k in weights)
    return int(round(total)), scores


# ============================================================================
# v6.4 4분류 시스템
# ============================================================================

def classify_stock_v64(quality_score, price_score, indicators):
    """
    4분류 시스템

    1. STRONG_MOMENTUM (🚀): 신고가 + 거래량 + RSI 70-80
    2. DIP_BUYING (🛡️): 급락 + 지지선 + RSI 30-50
    3. WAIT_OBSERVE (🟡): 양호하나 타이밍 대기
    4. NO_ENTRY (🚫): 버블/과열/저품질
    """

    rsi = indicators.get('rsi', 50)
    from_high = indicators.get('from_52w_high', 0)
    volume_signal = indicators.get('volume_signal', 1.0)
    ma_div = indicators.get('ma_div_60', 0)
    is_aligned = indicators.get('is_aligned', False)

    # 1. NO_ENTRY 조건 (먼저 체크)
    if ma_div >= 30:
        return 'NO_ENTRY', '🚫', '이격도 과대 (+30%)'
    if rsi >= 85:
        return 'NO_ENTRY', '🚫', 'RSI 극과열'
    if quality_score < 35:
        return 'NO_ENTRY', '🚫', '펀더멘털 부족'

    # 2. STRONG_MOMENTUM 조건
    momentum_conditions = [
        from_high >= -10,           # 52주 고점 근처
        volume_signal >= 1.5,       # 거래량 증가
        70 <= rsi <= 85,            # "좋은 과열"
        quality_score >= 55,        # 기본 펀더멘털
    ]
    if sum(momentum_conditions) >= 3:
        return 'STRONG_MOMENTUM', '🚀', '강세 돌파'

    # 신고가 + 정배열 + 거래량 (대체 조건)
    if from_high >= -5 and is_aligned and volume_signal >= 2.0:
        return 'STRONG_MOMENTUM', '🚀', '신고가 돌파'

    # 3. DIP_BUYING 조건
    dip_conditions = [
        from_high <= -25,           # 의미있는 하락
        rsi <= 50,                  # 과매도~중립
        quality_score >= 50,        # 괜찮은 펀더멘털
        ma_div <= 10,               # 과열 아님
    ]
    if sum(dip_conditions) >= 3:
        return 'DIP_BUYING', '🛡️', '저점 매수'

    # RSI 과매도 + 퀄리티 OK
    if rsi <= 35 and quality_score >= 50:
        return 'DIP_BUYING', '🛡️', 'RSI 과매도'

    # PER 초저평가 + 하락
    per = indicators.get('per', 999)
    if per <= 8 and from_high <= -20:
        return 'DIP_BUYING', '🛡️', 'PER 저평가'

    # 4. WAIT_OBSERVE (기본)
    if quality_score >= 60 and price_score >= 40:
        return 'WAIT_OBSERVE', '🟡', '추가 조정 대기'
    elif quality_score >= 50:
        return 'WAIT_OBSERVE', '🟡', '타이밍 관망'
    else:
        return 'WAIT_OBSERVE', '🟡', '관망'


# ============================================================================
# TOP 3 결론 생성
# ============================================================================

def generate_reasoning(r):
    """
    종목별 한줄 결론 생성

    예시:
    - "52주 신고가 돌파 + 거래량 2.5배"
    - "PER 10 저평가 + RSI 35 반등 기대"
    """

    reasons = []
    category = r.get('category', '')

    # 모멘텀 종목
    if category == 'STRONG_MOMENTUM':
        if r['from_52w_high'] >= -5:
            reasons.append("52주 신고가 돌파")
        elif r['from_52w_high'] >= -10:
            reasons.append("52주 고점 근접")

        if r['volume_signal'] >= 2.5:
            reasons.append(f"거래량 {r['volume_signal']:.1f}배 폭발")
        elif r['volume_signal'] >= 1.5:
            reasons.append(f"거래량 {r['volume_signal']:.1f}배")

        if r.get('is_aligned'):
            reasons.append("정배열 확산")

        if 70 <= r['rsi'] <= 80:
            reasons.append("강한 추세 지속")

    # 눌림목 종목
    elif category == 'DIP_BUYING':
        if r['per'] <= 8:
            reasons.append(f"PER {r['per']:.1f} 초저평가")
        elif r['per'] <= 12:
            reasons.append(f"PER {r['per']:.1f} 저평가")

        if r['rsi'] <= 30:
            reasons.append(f"RSI {r['rsi']:.0f} 극과매도")
        elif r['rsi'] <= 40:
            reasons.append(f"RSI {r['rsi']:.0f} 과매도")

        if r['from_52w_high'] <= -50:
            reasons.append(f"고점 대비 {abs(r['from_52w_high']):.0f}% 급락")
        elif r['from_52w_high'] <= -30:
            reasons.append(f"고점 대비 {abs(r['from_52w_high']):.0f}% 조정")

        if r.get('bb_position', 0.5) <= 0.2:
            reasons.append("볼린저 하단")

    # 관망 종목
    elif category == 'WAIT_OBSERVE':
        if r['rsi'] >= 60:
            reasons.append(f"RSI {r['rsi']:.0f} 중립~과열")
        if r['from_52w_high'] > -15:
            reasons.append("고점권 부담")
        if r.get('ma_div_60', 0) >= 15:
            reasons.append("단기 과열 해소 대기")

    # 금지 종목
    elif category == 'NO_ENTRY':
        if r.get('ma_div_60', 0) >= 30:
            reasons.append(f"60일선 +{r['ma_div_60']:.0f}% 괴리")
        if r['rsi'] >= 85:
            reasons.append(f"RSI {r['rsi']:.0f} 극과열")
        if r.get('quality_score', 100) < 35:
            reasons.append("펀더멘털 취약")

    # 기본값
    if not reasons:
        if category == 'STRONG_MOMENTUM':
            reasons.append("추세 추종 매매")
        elif category == 'DIP_BUYING':
            reasons.append("기술적 저점 매수")
        else:
            reasons.append("추가 분석 필요")

    return " + ".join(reasons[:2])


def generate_conclusion(r):
    """
    투자 결론 한줄 생성 (예: "잃기 힘든 자리", "가는 말이 더 간다")
    """

    category = r.get('category', '')
    quality = r.get('quality_score', 50)
    price = r.get('price_score', 50)
    per = r.get('per', 999)
    rsi = r.get('rsi', 50)
    from_high = r.get('from_52w_high', 0)

    if category == 'STRONG_MOMENTUM':
        if from_high >= -5 and r.get('volume_signal', 1) >= 2:
            return "가는 말이 더 간다. 눌림 없는 강력한 모멘텀"
        elif quality >= 70:
            return "펀더멘털과 기술적 흐름 모두 양호"
        else:
            return "추세 매매 관점에서 유효한 진입 구간"

    elif category == 'DIP_BUYING':
        if per <= 8 and from_high <= -40:
            return "잃기 힘든 자리. 가격 메리트 극대화 구간"
        elif rsi <= 35:
            return "악재 해소 국면, 기술적 반등 기대"
        elif quality >= 70:
            return "우량주 저점 매수 기회"
        else:
            return "분할 매수로 평균단가 낮추기 유리"

    elif category == 'NO_ENTRY':
        return "리스크가 기대수익보다 큼. 진입 금지"

    else:  # WAIT_OBSERVE
        if quality >= 70:
            return "좋은 회사지만 지금 사기엔 애매함"
        else:
            return "추가 조정 또는 실적 확인 후 진입"


# ============================================================================
# 메인 분석 함수
# ============================================================================

def analyze_stocks():
    """전체 종목 분석"""

    print("=" * 70)
    print("📊 일별 포트폴리오 모니터링 v6.4")
    print(f"📅 분석 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    stocks = load_portfolio_stocks()
    print(f"\n📋 분석 대상: {len(stocks)}개 종목")

    # 최근 거래일 찾기
    today = datetime.now()
    for i in range(10):
        check_date = (today - timedelta(days=i)).strftime('%Y%m%d')
        try:
            test_df = stock.get_market_ohlcv(check_date, check_date, "005930")
            if not test_df.empty:
                latest_date = check_date
                break
        except:
            continue
    else:
        latest_date = today.strftime('%Y%m%d')

    print(f"📆 기준일: {latest_date}")

    start_date = (datetime.strptime(latest_date, '%Y%m%d') - timedelta(days=400)).strftime('%Y%m%d')

    results = []

    print("\n⏳ 종목 분석 중...")

    for i, (ticker, info) in enumerate(stocks.items()):
        try:
            ohlcv = stock.get_market_ohlcv(start_date, latest_date, ticker)

            if ohlcv.empty:
                continue

            prices = ohlcv['종가']
            volumes = ohlcv['거래량']
            current_price = prices.iloc[-1]
            prev_price = prices.iloc[-2] if len(prices) > 1 else current_price

            # 기술적 지표 계산
            rsi = calculate_rsi(prices)
            bb_pos = calculate_bollinger_position(prices)
            ma_div_20 = calculate_ma_divergence(prices, 20)
            ma_div_60 = calculate_ma_divergence(prices, 60)
            w52_pos, from_high, from_low = get_52week_position(prices)
            vol_signal = calculate_volume_signal(volumes)
            is_aligned, alignment_score = check_ma_alignment(prices)

            # 실시간 밸류에이션
            valuation = calculate_realtime_valuation(ticker, current_price, info)

            # 지표 모음
            indicators = {
                'rsi': rsi,
                'bb_position': bb_pos,
                '52w_position': w52_pos,
                'from_52w_high': from_high,
                'from_52w_low': from_low,
                'ma_div_20': ma_div_20,
                'ma_div_60': ma_div_60,
                'volume_signal': vol_signal,
                'is_aligned': is_aligned,
                'alignment_score': alignment_score,
                'per': valuation['per'],
                'pbr': valuation['pbr'],
            }

            # v6.4 점수 계산
            quality_score, quality_details = calculate_quality_score(info, indicators)
            price_score, price_details = calculate_price_score(indicators)

            # 4분류
            category, emoji, category_reason = classify_stock_v64(quality_score, price_score, indicators)

            # 일간 수익률
            daily_return = ((current_price - prev_price) / prev_price) * 100

            # 결과 저장
            result = {
                'ticker': ticker,
                'name': info.get('name', ''),
                'strategy': info.get('strategy', ''),
                'current_price': current_price,
                'daily_return': daily_return,
                'per': valuation['per'],
                'pbr': valuation['pbr'],
                'market_cap': valuation['market_cap'],
                'rsi': rsi,
                'bb_position': bb_pos,
                'ma_div_20': ma_div_20,
                'ma_div_60': ma_div_60,
                '52w_position': w52_pos,
                'from_52w_high': from_high,
                'from_52w_low': from_low,
                'volume_signal': vol_signal,
                'is_aligned': is_aligned,
                'alignment_score': alignment_score,
                # v6.4 신규 필드
                'quality_score': quality_score,
                'price_score': price_score,
                'quality_details': quality_details,
                'price_details': price_details,
                'category': category,
                'emoji': emoji,
                'category_reason': category_reason,
                # Forward EPS 컨센서스 (추가 정보)
                'forward_eps': info.get('forward_eps'),
                'forward_per': info.get('forward_per'),
            }

            # 결론 생성
            result['reasoning'] = generate_reasoning(result)
            result['conclusion'] = generate_conclusion(result)

            results.append(result)

            if (i + 1) % 10 == 0:
                print(f"   {i + 1}/{len(stocks)} 완료...")

            time.sleep(0.05)

        except Exception as e:
            print(f"   ⚠️ {ticker} 분석 실패: {e}")
            continue

    print(f"\n✅ 분석 완료: {len(results)}개 종목")

    return results, latest_date


def categorize_results_v64(results):
    """v6.4 4분류로 결과 분류"""

    momentum = []    # 🚀 강세 돌파
    dip_buy = []     # 🛡️ 저점 매수
    watch = []       # 🟡 관망
    no_entry = []    # 🚫 진입 금지

    for r in results:
        cat = r.get('category', 'WAIT_OBSERVE')
        if cat == 'STRONG_MOMENTUM':
            momentum.append(r)
        elif cat == 'DIP_BUYING':
            dip_buy.append(r)
        elif cat == 'NO_ENTRY':
            no_entry.append(r)
        else:
            watch.append(r)

    # 점수순 정렬 (quality + price 합산)
    def sort_key(x):
        return x.get('quality_score', 0) + x.get('price_score', 0)

    momentum.sort(key=sort_key, reverse=True)
    dip_buy.sort(key=sort_key, reverse=True)
    watch.sort(key=sort_key, reverse=True)
    no_entry.sort(key=sort_key, reverse=True)

    return momentum, dip_buy, watch, no_entry


def get_top3(results):
    """TOP 3 종목 선정 (모멘텀 + 눌림목 혼합)"""

    # 모멘텀과 눌림목만 대상
    candidates = [r for r in results if r['category'] in ['STRONG_MOMENTUM', 'DIP_BUYING']]

    if not candidates:
        # 후보 없으면 전체에서 상위 선정
        candidates = results

    # 합산 점수 정렬
    candidates.sort(key=lambda x: x.get('quality_score', 0) + x.get('price_score', 0), reverse=True)

    return candidates[:3]


# ============================================================================
# 출력 및 저장
# ============================================================================

def print_results_v64(momentum, dip_buy, watch, no_entry, latest_date, top3):
    """v6.4 결과 출력"""

    print("\n")
    print("╔" + "═" * 68 + "╗")
    print("║" + f"  📊 퀀트 포트폴리오 v6.4 ({latest_date})".ljust(67) + "║")
    print("╚" + "═" * 68 + "╝")

    # TOP 3
    print("\n🏆 TODAY'S TOP 3")
    print("─" * 70)
    for i, r in enumerate(top3, 1):
        emoji = r.get('emoji', '📊')
        print(f"\n{i}️⃣ {emoji} {r['name']} ({r['ticker']}) [{r['strategy']}]")
        print(f"   현재가: {r['current_price']:,}원 | 품질: {r['quality_score']}점 | 타이밍: {r['price_score']}점")
        print(f"   → {r['reasoning']}")
        print(f"   💡 {r['conclusion']}")

    # 강세 돌파
    print(f"\n\n🚀 강세 돌파 ({len(momentum)}개)")
    print("신고가 + 거래량 = 추세 매수")
    print("─" * 70)
    if momentum:
        for r in momentum[:5]:
            change = "🔺" if r['daily_return'] > 0 else "🔻" if r['daily_return'] < 0 else "➖"
            print(f"  • {r['name']}: 품질{r['quality_score']} 타이밍{r['price_score']} | "
                  f"{r['current_price']:,}원 {change}{abs(r['daily_return']):.1f}%")
        if len(momentum) > 5:
            print(f"  ... 외 {len(momentum) - 5}개")
    else:
        print("  해당 종목 없음")

    # 저점 매수
    print(f"\n🛡️ 저점 매수 ({len(dip_buy)}개)")
    print("급락 + 지지선 = 분할 매수")
    print("─" * 70)
    if dip_buy:
        for r in dip_buy[:7]:
            change = "🔺" if r['daily_return'] > 0 else "🔻" if r['daily_return'] < 0 else "➖"
            print(f"  • {r['name']}: 품질{r['quality_score']} 타이밍{r['price_score']} | "
                  f"PER {r['per']:.1f} | RSI {r['rsi']:.0f}")
        if len(dip_buy) > 7:
            print(f"  ... 외 {len(dip_buy) - 7}개")
    else:
        print("  해당 종목 없음")

    # 관망
    print(f"\n🟡 관망 ({len(watch)}개)")
    print("─" * 70)
    if watch:
        for r in watch[:5]:
            print(f"  • {r['name']}: 품질{r['quality_score']} 타이밍{r['price_score']} | {r['category_reason']}")
        if len(watch) > 5:
            print(f"  ... 외 {len(watch) - 5}개")
    else:
        print("  해당 종목 없음")

    # 진입 금지
    print(f"\n🚫 진입 금지 ({len(no_entry)}개)")
    print("─" * 70)
    if no_entry:
        for r in no_entry[:5]:
            print(f"  • {r['name']}: {r['category_reason']}")
        if len(no_entry) > 5:
            print(f"  ... 외 {len(no_entry) - 5}개")
    else:
        print("  해당 종목 없음")

    print("\n" + "═" * 70)
    print("💡 품질 = 펀더멘털 매력도 | 타이밍 = 진입 적정성")
    print("═" * 70)


def save_results_v64(results, momentum, dip_buy, watch, no_entry, latest_date, top3):
    """v6.4 결과 저장"""

    date_str = latest_date

    # JSON 저장
    json_file = DAILY_DIR / f'daily_analysis_{date_str}.json'

    output_data = {
        'version': '6.4',
        'date': date_str,
        'generated_at': datetime.now().isoformat(),
        'summary': {
            'total_stocks': len(results),
            'momentum_count': len(momentum),
            'dip_buy_count': len(dip_buy),
            'watch_count': len(watch),
            'no_entry_count': len(no_entry),
        },
        'top3': [
            {
                'ticker': r['ticker'],
                'name': r['name'],
                'strategy': r['strategy'],
                'category': r['category'],
                'quality_score': r['quality_score'],
                'price_score': r['price_score'],
                'reasoning': r['reasoning'],
                'conclusion': r['conclusion'],
            }
            for r in top3
        ],
        'momentum': [
            {
                'ticker': r['ticker'],
                'name': r['name'],
                'strategy': r['strategy'],
                'price': int(r['current_price']),
                'quality_score': r['quality_score'],
                'price_score': r['price_score'],
                'rsi': round(r['rsi'], 1),
                'reasoning': r['reasoning'],
            }
            for r in momentum
        ],
        'dip_buy': [
            {
                'ticker': r['ticker'],
                'name': r['name'],
                'strategy': r['strategy'],
                'price': int(r['current_price']),
                'quality_score': r['quality_score'],
                'price_score': r['price_score'],
                'per': round(r['per'], 1),
                'rsi': round(r['rsi'], 1),
                'from_52w_high': round(r['from_52w_high'], 1),
                'reasoning': r['reasoning'],
            }
            for r in dip_buy
        ],
    }

    def convert_types(obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, dict):
            return {k: convert_types(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_types(v) for v in obj]
        return obj

    output_data = convert_types(output_data)

    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    # CSV 저장
    csv_file = DAILY_DIR / f'daily_analysis_{date_str}.csv'

    df = pd.DataFrame(results)
    df = df.sort_values(['category', 'quality_score'], ascending=[True, False])

    # 저장용 컬럼 선택
    save_cols = ['ticker', 'name', 'strategy', 'current_price', 'daily_return',
                 'per', 'rsi', 'from_52w_high', 'volume_signal',
                 'quality_score', 'price_score', 'category', 'reasoning']
    df_save = df[[c for c in save_cols if c in df.columns]]
    df_save.to_csv(csv_file, index=False, encoding='utf-8-sig')

    print(f"\n📁 결과 저장 완료:")
    print(f"   - {json_file}")
    print(f"   - {csv_file}")

    return json_file, csv_file


# ============================================================================
# 텔레그램 알림 v6.4
# ============================================================================

def get_market_status():
    """시장 현황 조회"""
    try:
        today = datetime.now()
        for i in range(10):
            check_date = (today - timedelta(days=i)).strftime('%Y%m%d')
            try:
                kospi = stock.get_index_ohlcv(check_date, check_date, "1001")
                kosdaq = stock.get_index_ohlcv(check_date, check_date, "2001")
                if not kospi.empty and not kosdaq.empty:
                    kospi_close = kospi['종가'].iloc[-1]
                    kosdaq_close = kosdaq['종가'].iloc[-1]

                    # 전일 대비
                    prev_date = (datetime.strptime(check_date, '%Y%m%d') - timedelta(days=7)).strftime('%Y%m%d')
                    kospi_prev = stock.get_index_ohlcv(prev_date, check_date, "1001")
                    kosdaq_prev = stock.get_index_ohlcv(prev_date, check_date, "2001")

                    if len(kospi_prev) >= 2:
                        kospi_change = ((kospi_close - kospi_prev['종가'].iloc[-2]) / kospi_prev['종가'].iloc[-2]) * 100
                    else:
                        kospi_change = 0

                    if len(kosdaq_prev) >= 2:
                        kosdaq_change = ((kosdaq_close - kosdaq_prev['종가'].iloc[-2]) / kosdaq_prev['종가'].iloc[-2]) * 100
                    else:
                        kosdaq_change = 0

                    return {
                        'kospi': kospi_close,
                        'kospi_change': kospi_change,
                        'kosdaq': kosdaq_close,
                        'kosdaq_change': kosdaq_change,
                    }
            except:
                continue
    except:
        pass

    return {'kospi': 0, 'kosdaq': 0, 'kospi_change': 0, 'kosdaq_change': 0}


def send_single_telegram(msg):
    """단일 텔레그램 메시지 발송"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {'chat_id': TELEGRAM_CHAT_ID, 'text': msg}
        response = requests.post(url, data=data, timeout=10)
        return response.status_code == 200
    except:
        return False


def send_telegram_v64(momentum, dip_buy, watch, no_entry, latest_date, top3):
    """텔레그램 v6.4 포맷 발송 (3개 메시지)"""

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("\n⚠️ 텔레그램 설정이 없어 알림을 건너뜁니다.")
        return False

    market = get_market_status()

    total = len(momentum) + len(dip_buy) + len(watch) + len(no_entry)
    date_fmt = f"{latest_date[:4]}.{latest_date[4:6]}.{latest_date[6:]}"

    # ===== 메시지 1: 개요 + TOP 3 =====
    msg1 = f"📊 퀀트 포트폴리오 v6.4\n"
    msg1 += f"📅 {date_fmt}\n"
    msg1 += "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    # 시장 현황
    if market['kospi'] > 0:
        k_icon = "🔺" if market['kospi_change'] > 0 else "🔻" if market['kospi_change'] < 0 else "➖"
        d_icon = "🔺" if market['kosdaq_change'] > 0 else "🔻" if market['kosdaq_change'] < 0 else "➖"
        msg1 += f"📈 시장 현황\n"
        msg1 += f"• KOSPI: {market['kospi']:,.0f} {k_icon}{abs(market['kospi_change']):.1f}%\n"
        msg1 += f"• KOSDAQ: {market['kosdaq']:,.0f} {d_icon}{abs(market['kosdaq_change']):.1f}%\n\n"

    msg1 += f"📋 전략: 🛡️눌림목(A) + 🚀모멘텀(B) 듀얼 트랙\n"
    msg1 += f"📊 분석 종목: {total}개\n\n"

    msg1 += "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg1 += "🏆 TODAY'S TOP 3\n\n"

    for i, r in enumerate(top3, 1):
        emoji = r.get('emoji', '📊')
        msg1 += f"{i}️⃣ {emoji} {r['name']} ({r['ticker']})\n"
        msg1 += f"   품질: {r['quality_score']}점 | 타이밍: {r['price_score']}점\n"
        # Forward PER 추가 정보
        fwd_per = r.get('forward_per')
        if fwd_per and fwd_per > 0:
            msg1 += f"   [컨센서스] Forward PER: {fwd_per:.1f}x\n"
        msg1 += f"   → {r['reasoning']}\n"
        msg1 += f"   💡 {r['conclusion']}\n\n"

    send_single_telegram(msg1)
    time.sleep(0.5)

    # ===== 메시지 2: 모멘텀 + 눌림목 =====
    msg2 = f"🚀 강세 돌파 ({len(momentum)}개)\n"
    msg2 += "신고가 + 거래량 = 추세 매수\n"
    msg2 += "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    if momentum:
        for r in momentum[:5]:
            msg2 += f"• {r['name']}: 품질{r['quality_score']} 타이밍{r['price_score']}"
            fwd_per = r.get('forward_per')
            if fwd_per and fwd_per > 0:
                msg2 += f" [F.PER {fwd_per:.1f}]"
            msg2 += f"\n  {r['current_price']:,}원 | {r['reasoning']}\n\n"
        if len(momentum) > 5:
            msg2 += f"... 외 {len(momentum) - 5}개\n\n"
    else:
        msg2 += "해당 종목 없음\n\n"

    msg2 += f"🛡️ 저점 매수 ({len(dip_buy)}개)\n"
    msg2 += "급락 + 지지선 = 분할 매수\n"
    msg2 += "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    if dip_buy:
        for r in dip_buy[:7]:
            msg2 += f"• {r['name']}: 품질{r['quality_score']} 타이밍{r['price_score']}"
            fwd_per = r.get('forward_per')
            if fwd_per and fwd_per > 0:
                msg2 += f" [F.PER {fwd_per:.1f}]"
            msg2 += f"\n  PER {r['per']:.1f} | RSI {r['rsi']:.0f} | {r['reasoning']}\n\n"
        if len(dip_buy) > 7:
            msg2 += f"... 외 {len(dip_buy) - 7}개\n"
    else:
        msg2 += "해당 종목 없음\n"

    send_single_telegram(msg2)
    time.sleep(0.5)

    # ===== 메시지 3: 관망 + 금지 =====
    msg3 = f"🟡 관망 ({len(watch)}개)\n"
    msg3 += "타이밍 대기\n"
    msg3 += "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    if watch:
        for r in watch[:8]:
            msg3 += f"• {r['name']}: 품질{r['quality_score']} 타이밍{r['price_score']} ({r['category_reason']})\n"
        if len(watch) > 8:
            msg3 += f"... 외 {len(watch) - 8}개\n"
        msg3 += "\n"
    else:
        msg3 += "해당 종목 없음\n\n"

    msg3 += f"🚫 진입 금지 ({len(no_entry)}개)\n"
    msg3 += "버블/과열 경고\n"
    msg3 += "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    if no_entry:
        for r in no_entry[:5]:
            msg3 += f"• {r['name']}: {r['category_reason']}\n"
        if len(no_entry) > 5:
            msg3 += f"... 외 {len(no_entry) - 5}개\n"
    else:
        msg3 += "해당 종목 없음\n"

    msg3 += "\n━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg3 += "💡 품질=펀더멘털 | 타이밍=진입적정성\n"
    msg3 += "📊 F.PER=Forward PER (애널리스트 컨센서스)\n"
    msg3 += "📈 Quant Bot v6.4 by Volume"

    send_single_telegram(msg3)

    print("\n✅ 텔레그램 알림 발송 완료 (3개 메시지)")
    return True


# ============================================================================
# Git 커밋 & 푸시
# ============================================================================

def git_commit_and_push(latest_date):
    """Git 자동 커밋 및 푸시"""

    if not GIT_AUTO_PUSH:
        print("\n⚠️ Git 자동 푸시가 비활성화되어 있습니다.")
        return False

    try:
        repo_root = BASE_DIR.parent.parent

        subprocess.run(
            ['git', 'add', 'claude code/quant_py-main/daily_reports/'],
            cwd=str(repo_root),
            capture_output=True,
            encoding='utf-8',
            errors='replace'
        )

        commit_msg = f"chore: daily monitoring report v6.4 ({latest_date})"
        result = subprocess.run(
            ['git', 'commit', '-m', commit_msg],
            cwd=str(repo_root),
            capture_output=True,
            encoding='utf-8',
            errors='replace'
        )

        stdout = result.stdout or ''
        stderr = result.stderr or ''

        if 'nothing to commit' in stdout or 'nothing to commit' in stderr:
            print("\n⚠️ 커밋할 변경사항이 없습니다.")
            return False

        result = subprocess.run(
            ['git', 'push'],
            cwd=str(repo_root),
            capture_output=True,
            encoding='utf-8',
            errors='replace',
            timeout=60
        )

        if result.returncode == 0:
            print("\n✅ Git 커밋 & 푸시 완료")
            return True
        else:
            print(f"\n⚠️ Git 푸시 실패: {result.stderr}")
            return False

    except Exception as e:
        print(f"\n⚠️ Git 오류: {e}")
        return False


# ============================================================================
# 메인 실행
# ============================================================================

def main():
    """메인 실행 함수"""

    try:
        # 1. 종목 분석
        results, latest_date = analyze_stocks()

        if not results:
            print("\n❌ 분석 결과가 없습니다.")
            return

        # 2. v6.4 분류
        momentum, dip_buy, watch, no_entry = categorize_results_v64(results)

        # 3. TOP 3 선정
        top3 = get_top3(results)

        # 4. 결과 출력
        print_results_v64(momentum, dip_buy, watch, no_entry, latest_date, top3)

        # 5. 결과 저장
        save_results_v64(results, momentum, dip_buy, watch, no_entry, latest_date, top3)

        # 6. 텔레그램 알림
        send_telegram_v64(momentum, dip_buy, watch, no_entry, latest_date, top3)

        # 7. Git 커밋 & 푸시
        git_commit_and_push(latest_date)

        print("\n" + "=" * 70)
        print("✅ 일별 모니터링 v6.4 완료!")
        print("=" * 70)

    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
