"""
일별 포트폴리오 모니터링 및 진입 타이밍 분석
- 실시간 밸류에이션 체크
- 기술적 지표 분석
- 진입 점수 산출
- 텔레그램 알림
- Git 자동 커밋/푸시
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

# 설정 로드 (config.py에서 가져오기)
try:
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GIT_AUTO_PUSH, SCORE_BUY, SCORE_WATCH
except ImportError:
    # config.py가 없으면 기본값 사용
    TELEGRAM_BOT_TOKEN = ""
    TELEGRAM_CHAT_ID = ""
    GIT_AUTO_PUSH = True
    SCORE_BUY = 0.6
    SCORE_WATCH = 0.3

# ============================================================================
# 포트폴리오 종목 로드
# ============================================================================

def load_portfolio_stocks():
    """전략 A, B에서 선정된 종목 로드"""

    stocks = {}

    # 전략 A 종목
    strategy_a_file = OUTPUT_DIR / 'portfolio_2026_01_strategy_a.csv'
    if strategy_a_file.exists():
        df_a = pd.read_csv(strategy_a_file, dtype={'종목코드': str})
        for _, row in df_a.head(20).iterrows():
            ticker = str(row['종목코드']).zfill(6)
            stocks[ticker] = {
                'name': row.get('종목명', ''),
                'strategy': 'A',
                'ey': row.get('이익수익률', 0),
                'roc': row.get('투하자본수익률', 0),
                'net_income': row.get('당기순이익', 0),
                'equity': row.get('자본', 0),
            }

    # 전략 B 종목
    strategy_b_file = OUTPUT_DIR / 'portfolio_2026_01_strategy_b.csv'
    if strategy_b_file.exists():
        df_b = pd.read_csv(strategy_b_file, dtype={'종목코드': str})
        for _, row in df_b.head(20).iterrows():
            ticker = str(row['종목코드']).zfill(6)
            if ticker in stocks:
                stocks[ticker]['strategy'] = 'A+B'  # 공통 종목
                stocks[ticker]['mf_score'] = row.get('멀티팩터_점수', 0)
            else:
                stocks[ticker] = {
                    'name': row.get('종목명', ''),
                    'strategy': 'B',
                    'mf_score': row.get('멀티팩터_점수', 0),
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

    # 최근 252 거래일 (약 1년)
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


# ============================================================================
# 실시간 밸류에이션
# ============================================================================

def calculate_realtime_valuation(ticker, current_price, stock_info):
    """실시간 PER, PBR 계산"""

    try:
        # 시가총액 = 현재가 × 발행주식수
        # pykrx에서 시가총액 조회
        today = datetime.now().strftime('%Y%m%d')

        # 최근 거래일 찾기
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

        # PER, PBR 계산
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
# 진입 점수 계산
# ============================================================================

def calculate_entry_score(indicators):
    """진입 점수 계산 (0~1, 높을수록 매수 적기)"""

    scores = {}

    # 1. RSI 점수 (30 이하면 만점, 70 이상이면 0점)
    rsi = indicators.get('rsi', 50)
    if rsi <= 30:
        scores['rsi'] = 1.0
    elif rsi >= 70:
        scores['rsi'] = 0.0
    else:
        scores['rsi'] = (70 - rsi) / 40

    # 2. 볼린저밴드 점수 (하단에 가까울수록 높음)
    bb_pos = indicators.get('bb_position', 0.5)
    scores['bollinger'] = 1 - bb_pos

    # 3. 52주 위치 점수 (저점에 가까울수록 높음)
    w52_pos = indicators.get('52w_position', 0.5)
    scores['52week'] = 1 - w52_pos

    # 4. 이동평균 이격도 점수 (음수면 저평가)
    ma_div = indicators.get('ma_divergence', 0)
    if ma_div <= -20:
        scores['ma'] = 1.0
    elif ma_div >= 20:
        scores['ma'] = 0.0
    else:
        scores['ma'] = (20 - ma_div) / 40

    # 5. 거래량 신호 (평균 이상이면 가점)
    vol_signal = indicators.get('volume_signal', 1.0)
    if vol_signal >= 2.0:
        scores['volume'] = 1.0
    elif vol_signal <= 0.5:
        scores['volume'] = 0.3
    else:
        scores['volume'] = 0.5 + (vol_signal - 1) * 0.5

    # 가중 평균
    weights = {
        'rsi': 0.25,
        'bollinger': 0.20,
        '52week': 0.25,
        'ma': 0.20,
        'volume': 0.10,
    }

    total_score = sum(scores[k] * weights[k] for k in scores)

    return total_score, scores


# ============================================================================
# 메인 분석 함수
# ============================================================================

def analyze_stocks():
    """전체 종목 분석"""

    print("=" * 70)
    print("📊 일별 포트폴리오 모니터링")
    print(f"📅 분석 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # 포트폴리오 종목 로드
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

    # 가격 데이터 수집 기간
    start_date = (datetime.strptime(latest_date, '%Y%m%d') - timedelta(days=400)).strftime('%Y%m%d')

    results = []

    print("\n⏳ 종목 분석 중...")

    for i, (ticker, info) in enumerate(stocks.items()):
        try:
            # 가격 데이터 조회
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

            # 실시간 밸류에이션
            valuation = calculate_realtime_valuation(ticker, current_price, info)

            # 지표 모음
            indicators = {
                'rsi': rsi,
                'bb_position': bb_pos,
                '52w_position': w52_pos,
                'ma_divergence': ma_div_60,
                'volume_signal': vol_signal,
            }

            # 진입 점수 계산
            entry_score, score_details = calculate_entry_score(indicators)

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
                'entry_score': entry_score,
                'score_details': score_details,
            }
            results.append(result)

            # 진행 상황
            if (i + 1) % 10 == 0:
                print(f"   {i + 1}/{len(stocks)} 완료...")

            time.sleep(0.05)  # API 부하 방지

        except Exception as e:
            print(f"   ⚠️ {ticker} 분석 실패: {e}")
            continue

    print(f"\n✅ 분석 완료: {len(results)}개 종목")

    return results, latest_date


def categorize_results(results):
    """결과를 카테고리별로 분류"""

    buy = []      # 매수 적기
    watch = []    # 관망
    wait = []     # 대기

    for r in results:
        score = r['entry_score']
        if score >= SCORE_BUY:
            buy.append(r)
        elif score >= SCORE_WATCH:
            watch.append(r)
        else:
            wait.append(r)

    # 점수순 정렬
    buy.sort(key=lambda x: x['entry_score'], reverse=True)
    watch.sort(key=lambda x: x['entry_score'], reverse=True)
    wait.sort(key=lambda x: x['entry_score'], reverse=True)

    return buy, watch, wait


# ============================================================================
# 출력 및 저장
# ============================================================================

def format_number(num):
    """숫자 포맷팅"""
    if num >= 1000000:
        return f"{num/1000000:.1f}M"
    elif num >= 1000:
        return f"{num/1000:.1f}K"
    else:
        return f"{num:.0f}"


def print_results(buy, watch, wait, latest_date):
    """결과 출력"""

    print("\n")
    print("╔" + "═" * 68 + "╗")
    print("║" + f"  🎯 진입 타이밍 분석 결과 ({latest_date})".ljust(67) + "║")
    print("╚" + "═" * 68 + "╝")

    # 매수 적기
    print("\n🟢 매수 적기 (진입점수 ≥ 0.6)")
    print("─" * 70)
    if buy:
        print(f"{'종목명':<12} {'현재가':>10} {'등락':>7} {'PER':>6} {'RSI':>5} {'52주고점':>8} {'점수':>6}")
        print("─" * 70)
        for r in buy:
            change_icon = "🔺" if r['daily_return'] > 0 else "🔻" if r['daily_return'] < 0 else "➖"
            print(f"{r['name']:<12} {r['current_price']:>10,} {change_icon}{abs(r['daily_return']):>5.1f}% "
                  f"{r['per']:>6.1f} {r['rsi']:>5.0f} {r['from_52w_high']:>7.1f}% {r['entry_score']:>5.2f}⭐")
    else:
        print("   해당 종목 없음")

    # 관망
    print("\n🟡 관망 (0.3 ≤ 진입점수 < 0.6)")
    print("─" * 70)
    if watch:
        print(f"{'종목명':<12} {'현재가':>10} {'등락':>7} {'PER':>6} {'RSI':>5} {'52주고점':>8} {'점수':>6}")
        print("─" * 70)
        for r in watch[:10]:  # 상위 10개만
            change_icon = "🔺" if r['daily_return'] > 0 else "🔻" if r['daily_return'] < 0 else "➖"
            print(f"{r['name']:<12} {r['current_price']:>10,} {change_icon}{abs(r['daily_return']):>5.1f}% "
                  f"{r['per']:>6.1f} {r['rsi']:>5.0f} {r['from_52w_high']:>7.1f}% {r['entry_score']:>5.2f}")
        if len(watch) > 10:
            print(f"   ... 외 {len(watch) - 10}개 종목")
    else:
        print("   해당 종목 없음")

    # 대기
    print("\n🔴 대기 (진입점수 < 0.3)")
    print("─" * 70)
    if wait:
        print(f"{'종목명':<12} {'현재가':>10} {'등락':>7} {'PER':>6} {'RSI':>5} {'52주고점':>8} {'점수':>6}")
        print("─" * 70)
        for r in wait[:5]:  # 상위 5개만
            change_icon = "🔺" if r['daily_return'] > 0 else "🔻" if r['daily_return'] < 0 else "➖"
            print(f"{r['name']:<12} {r['current_price']:>10,} {change_icon}{abs(r['daily_return']):>5.1f}% "
                  f"{r['per']:>6.1f} {r['rsi']:>5.0f} {r['from_52w_high']:>7.1f}% {r['entry_score']:>5.2f}")
        if len(wait) > 5:
            print(f"   ... 외 {len(wait) - 5}개 종목")
    else:
        print("   해당 종목 없음")

    print("\n" + "═" * 70)


def save_results(results, buy, watch, wait, latest_date):
    """결과 저장"""

    date_str = latest_date

    # 1. JSON 저장
    json_file = DAILY_DIR / f'daily_analysis_{date_str}.json'

    output_data = {
        'date': date_str,
        'generated_at': datetime.now().isoformat(),
        'summary': {
            'total_stocks': len(results),
            'buy_count': len(buy),
            'watch_count': len(watch),
            'wait_count': len(wait),
        },
        'buy': [
            {
                'ticker': r['ticker'],
                'name': r['name'],
                'strategy': r['strategy'],
                'price': r['current_price'],
                'daily_return': round(r['daily_return'], 2),
                'per': round(r['per'], 2),
                'pbr': round(r['pbr'], 2),
                'rsi': round(r['rsi'], 1),
                'from_52w_high': round(r['from_52w_high'], 1),
                'entry_score': round(r['entry_score'], 3),
            }
            for r in buy
        ],
        'watch': [
            {
                'ticker': r['ticker'],
                'name': r['name'],
                'strategy': r['strategy'],
                'price': r['current_price'],
                'entry_score': round(r['entry_score'], 3),
            }
            for r in watch
        ],
    }

    # numpy 타입을 Python 기본 타입으로 변환
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

    # 2. CSV 저장
    csv_file = DAILY_DIR / f'daily_analysis_{date_str}.csv'

    df = pd.DataFrame(results)
    df = df.sort_values('entry_score', ascending=False)
    df.to_csv(csv_file, index=False, encoding='utf-8-sig')

    # 3. 텍스트 리포트 저장
    txt_file = DAILY_DIR / f'daily_report_{date_str}.txt'

    with open(txt_file, 'w', encoding='utf-8') as f:
        f.write("=" * 70 + "\n")
        f.write(f"📊 일별 포트폴리오 모니터링 리포트\n")
        f.write(f"📅 기준일: {date_str}\n")
        f.write(f"⏰ 생성: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 70 + "\n\n")

        f.write("🟢 매수 적기 (진입점수 ≥ 0.6)\n")
        f.write("-" * 70 + "\n")
        if buy:
            for r in buy:
                f.write(f"  • {r['name']} ({r['ticker']}) - {r['current_price']:,}원\n")
                f.write(f"    PER: {r['per']:.1f} | RSI: {r['rsi']:.0f} | 52주고점: {r['from_52w_high']:.1f}% | 점수: {r['entry_score']:.2f}\n")
        else:
            f.write("  해당 종목 없음\n")

        f.write("\n🟡 관망 (0.3 ≤ 진입점수 < 0.6)\n")
        f.write("-" * 70 + "\n")
        if watch:
            for r in watch[:10]:
                f.write(f"  • {r['name']} ({r['ticker']}) - 점수: {r['entry_score']:.2f}\n")
        else:
            f.write("  해당 종목 없음\n")

        f.write("\n" + "=" * 70 + "\n")

    print(f"\n📁 결과 저장 완료:")
    print(f"   - {json_file}")
    print(f"   - {csv_file}")
    print(f"   - {txt_file}")

    return json_file, csv_file, txt_file


# ============================================================================
# 텔레그램 알림
# ============================================================================

def get_entry_reason(r):
    """진입 근거 생성"""
    reasons = []

    # RSI 분석
    if r['rsi'] <= 30:
        reasons.append(f"RSI {r['rsi']:.0f} (과매도)")
    elif r['rsi'] <= 40:
        reasons.append(f"RSI {r['rsi']:.0f} (저점)")
    elif r['rsi'] >= 70:
        reasons.append(f"RSI {r['rsi']:.0f} (과매수)")
    else:
        reasons.append(f"RSI {r['rsi']:.0f}")

    # 52주 고점 대비
    if r['from_52w_high'] <= -50:
        reasons.append(f"52주高 {r['from_52w_high']:.0f}% (급락)")
    elif r['from_52w_high'] <= -30:
        reasons.append(f"52주高 {r['from_52w_high']:.0f}% (조정)")
    elif r['from_52w_high'] <= -15:
        reasons.append(f"52주高 {r['from_52w_high']:.0f}%")

    # PER 분석
    if r['per'] < 5:
        reasons.append(f"PER {r['per']:.1f} (초저평가)")
    elif r['per'] < 10:
        reasons.append(f"PER {r['per']:.1f} (저평가)")
    elif r['per'] < 15:
        reasons.append(f"PER {r['per']:.1f} (적정)")

    # 볼린저밴드 위치
    if r['bb_position'] <= 0.2:
        reasons.append("BB 하단 근접")

    # 이격도
    if r['ma_div_60'] <= -15:
        reasons.append(f"60일선 {r['ma_div_60']:.0f}% (저평가)")

    return " | ".join(reasons[:4])  # 최대 4개


def send_telegram_message(buy, watch, latest_date):
    """텔레그램 메시지 발송"""

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("\n⚠️ 텔레그램 설정이 없어 알림을 건너뜁니다.")
        print("   TELEGRAM_BOT_TOKEN과 TELEGRAM_CHAT_ID를 설정하세요.")
        return False

    # 메시지 구성 (마크다운 이스케이프 제거, 더 깔끔하게)
    msg = "📊 일별 포트폴리오 모니터링\n"
    msg += f"📅 기준일: {latest_date}\n"
    msg += f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    msg += "━" * 25 + "\n\n"

    if buy:
        msg += "🟢 매수 적기 (진입점수 0.6 이상)\n\n"
        for r in buy[:5]:
            change_icon = "🔺" if r['daily_return'] > 0 else "🔻" if r['daily_return'] < 0 else "➖"

            # 종목명 + 코드 + 가격
            msg += f"▶ {r['name']} ({r['ticker']})\n"
            msg += f"   {r['current_price']:,}원 {change_icon}{abs(r['daily_return']):.1f}%\n"
            msg += f"   ⭐ 진입점수: {r['entry_score']:.2f}\n"

            # 상세 근거
            reason = get_entry_reason(r)
            msg += f"   📌 {reason}\n"
            msg += f"   전략: {r['strategy']}\n\n"

        if len(buy) > 5:
            msg += f"... 외 {len(buy) - 5}개 종목\n\n"
    else:
        msg += "🟢 매수 적기: 해당 종목 없음\n\n"

    msg += "━" * 25 + "\n"

    if watch:
        msg += f"🟡 관망 ({len(watch)}개 종목)\n"
        for r in watch[:5]:
            change_icon = "🔺" if r['daily_return'] > 0 else "🔻" if r['daily_return'] < 0 else "➖"
            msg += f"• {r['name']} ({r['ticker']}) - {r['current_price']:,}원 {change_icon}{abs(r['daily_return']):.1f}%\n"
            msg += f"  점수: {r['entry_score']:.2f} | {r['strategy']}\n"
        if len(watch) > 5:
            msg += f"... 외 {len(watch) - 5}개\n"
    else:
        msg += "🟡 관망: 해당 종목 없음\n"

    msg += "\n━" * 25 + "\n"
    msg += "📈 Generated by Quant Bot"

    # 텔레그램 API 호출
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': msg,
            'parse_mode': 'Markdown',
        }
        response = requests.post(url, data=data, timeout=10)

        if response.status_code == 200:
            print("\n✅ 텔레그램 알림 발송 완료")
            return True
        else:
            print(f"\n⚠️ 텔레그램 발송 실패: {response.status_code}")
            return False

    except Exception as e:
        print(f"\n⚠️ 텔레그램 발송 오류: {e}")
        return False


# ============================================================================
# Git 커밋 & 푸시
# ============================================================================

def git_commit_and_push(latest_date):
    """Git 자동 커밋 및 푸시"""

    if not GIT_AUTO_PUSH:
        print("\n⚠️ Git 자동 푸시가 비활성화되어 있습니다.")
        return False

    try:
        # Git 저장소 루트로 이동
        repo_root = BASE_DIR.parent.parent  # quant_py-main 상위

        # 파일 추가
        subprocess.run(
            ['git', 'add', 'claude code/quant_py-main/daily_reports/'],
            cwd=str(repo_root),
            capture_output=True,
            encoding='utf-8',
            errors='replace'
        )

        # 커밋
        commit_msg = f"chore: daily monitoring report ({latest_date})"
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

        # 푸시
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

        # 2. 결과 분류
        buy, watch, wait = categorize_results(results)

        # 3. 결과 출력
        print_results(buy, watch, wait, latest_date)

        # 4. 결과 저장
        save_results(results, buy, watch, wait, latest_date)

        # 5. 텔레그램 알림
        send_telegram_message(buy, watch, latest_date)

        # 6. Git 커밋 & 푸시
        git_commit_and_push(latest_date)

        print("\n" + "=" * 70)
        print("✅ 일별 모니터링 완료!")
        print("=" * 70)

    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
