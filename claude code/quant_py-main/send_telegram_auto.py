"""
한국주식 퀀트 포트폴리오 텔레그램 메시지 v3.1
통합 포트폴리오 CSV 기반 1~2개 메시지 전송

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
import glob
import os
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from zoneinfo import ZoneInfo
from gemini_analysis import compute_risk_flags

# ============================================================
# 상수/설정
# ============================================================
KST = ZoneInfo('Asia/Seoul')
CACHE_DIR = Path('data_cache')
OUTPUT_DIR = Path('output')
HISTORY_FILE = CACHE_DIR / 'portfolio_history.json'

# 섹터 데이터베이스
SECTOR_DB = {
    '000270': '자동차',
    '000660': 'AI반도체/메모리',
    '001060': '바이오/제약',
    '002380': '건자재/도료',
    '002900': '농기계/중장비',
    '005180': '식품',
    '005850': '자동차부품/조명',
    '006910': '원전/발전설비',
    '008770': '면세점/호텔',
    '009540': '조선/해양',
    '015760': '전력/유틸리티',
    '017800': '승강기/기계',
    '018290': 'K-뷰티',
    '019180': '자동차부품/와이어링',
    '030000': '광고/마케팅',
    '030200': '통신',
    '033100': '변압기/전력',
    '033500': 'LNG단열재',
    '033530': '건설/플랜트',
    '035900': '엔터/K-POP',
    '036620': '아웃도어패션',
    '037460': '전자부품/커넥터',
    '039130': '여행',
    '041510': '엔터/K-POP',
    '043260': '전자부품',
    '052400': '디지털화폐/핀테크',
    '067160': '스트리밍',
    '067290': '바이오/제약',
    '078930': '에너지/정유',
    '083450': '반도체장비',
    '084670': '자동차부품',
    '086280': '물류/운송',
    '088130': '디스플레이장비',
    '095610': '2차전지장비',
    '098120': '반도체/패키징',
    '100840': '방산/에너지',
    '102710': '반도체소재',
    '111770': '섬유/의류',
    '112610': '풍력/에너지',
    '119850': '에너지/발전설비',
    '123330': 'K-뷰티/화장품',
    '123410': '자동차부품',
    '124500': 'IT/금거래',
    '183300': '반도체소재',
    '190510': '로봇/센서',
    '192080': '게임',
    '200670': '의료기기/필러',
    '204620': '택스리펀드/면세',
    '206650': '바이오/백신',
    '223250': 'IT서비스',
    '250060': 'AI/핵융합',
    '259630': '2차전지장비',
    '259960': '게임',
    '278470': '뷰티디바이스',
    '282330': '편의점/유통',
    '336570': '의료기기',
    '383220': '패션/브랜드',
    '402340': '투자지주/AI반도체',
    '419530': '애니/캐릭터',
    '462870': '게임',
}


# ============================================================
# 유틸리티 함수
# ============================================================
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
        except Exception:
            continue
    return None


def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50


def get_stock_technical(ticker, base_date):
    """종목 기술적 지표 계산"""
    ticker_str = str(ticker).zfill(6)
    try:
        start = (datetime.strptime(base_date, '%Y%m%d') - timedelta(days=365)).strftime('%Y%m%d')
        ohlcv = stock.get_market_ohlcv(start, base_date, ticker_str)

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
        per_str = f"PER {s['per']:.1f}"
        # Forward PER 있으면 병기 (예: PER 29.2→5.3)
        if s.get('fwd_per') and not pd.isna(s['fwd_per']):
            per_str += f"→{s['fwd_per']:.1f}"
        factor_parts.append(per_str)
    if s.get('pbr') and not pd.isna(s['pbr']):
        factor_parts.append(f"PBR {s['pbr']:.1f}")
    if s.get('roe') and not pd.isna(s['roe']):
        factor_parts.append(f"ROE {s['roe']:.1f}%")
    factor_str = ' | '.join(factor_parts) if factor_parts else ''

    block = f"""{medal} {rank}위 {s['name']} ({s['ticker']}) {s['sector']}
💰 {s['price']:,.0f}원 ({s['daily_chg']:+.2f}%)
📊 {factor_str}
📈 RSI {s['rsi']:.0f} | 52주 {s['w52_pct']:+.0f}%
━━━━━━━━━━━━━━━━━━━
"""
    return block


# ============================================================
# 퀀트 TOP 5 추천
# ============================================================
def get_broad_sector(sector):
    """대분류 섹터 (중복 방지용)"""
    if '반도체' in sector:
        return '반도체'
    if '자동차' in sector:
        return '자동차'
    if '바이오' in sector or '의료' in sector or '백신' in sector:
        return '바이오'
    if '게임' in sector:
        return '게임'
    if '엔터' in sector or 'K-POP' in sector:
        return '엔터'
    return sector


def select_top5(stock_analysis, n=10):
    """위험 플래그 없는 종목 중 섹터 중복 없이 TOP N 선정"""
    selected = []
    used_sectors = set()

    for s in stock_analysis:
        if len(selected) >= n:
            break
        flags = compute_risk_flags(s)
        if flags:
            continue
        broad = get_broad_sector(s['sector'])
        if broad in used_sectors:
            continue
        selected.append(s)
        used_sectors.add(broad)

    return selected


def format_recommendation(selected):
    """퀀트 TOP N 추천 메시지 포맷"""
    n = len(selected)
    # 비중: 균등 배분 (나머지는 앞에서부터 +1%)
    base = 100 // n
    remainder = 100 - base * n
    weights = [base + (1 if i < remainder else 0) for i in range(n)]
    medal_icons = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    medals = medal_icons[:n] if n <= 10 else medal_icons + [f"({i+1})" for i in range(10, n)]
    now = datetime.now(KST)

    def get_entry(rsi):
        if rsi < 40:
            return "즉시 진입 (과매도)"
        elif rsi < 60:
            return "즉시 진입"
        elif rsi < 70:
            return "분할 매수"
        else:
            return f"⚠️대기 (RSI {rsi:.0f} 과열)"

    def get_highlight(s):
        parts = []
        per, roe = s.get('per'), s.get('roe')
        if per and per == per and per < 10:
            parts.append(f"PER {per:.1f} 저평가")
        if roe and roe == roe and roe > 20:
            parts.append(f"ROE {roe:.1f}%")
        if s.get('w52_pct', 0) < -25:
            parts.append(f"52주 대비 {s['w52_pct']:.0f}% 할인")
        if s.get('rsi', 50) < 40:
            parts.append("과매도 반등 기대")
        return ', '.join(parts) if parts else f"퀀트 {int(s['rank'])}위"

    lines = [
        "━━━━━━━━━━━━━━━━━━━",
        f"   🎯 퀀트 TOP {n} 추천",
        "━━━━━━━━━━━━━━━━━━━",
        f"📅 {now.strftime('%Y년 %m월 %d일')}",
        "",
        f"퀀트 TOP 30에서 위험 플래그 제거 + 섹터 분산",
        f"기반 {n}종목을 자동 선정했어요.",
        "",
    ]

    for i, s in enumerate(selected):
        lines.append(f"{medals[i]} {s['name']} · {s['sector']}")
        lines.append(f"   퀀트 {int(s['rank'])}위 | 비중 {weights[i]}%")
        lines.append(f"   {s['price']:,.0f}원 | RSI {s['rsi']:.0f} | 52주 {s['w52_pct']:+.0f}%")
        lines.append(f"   📋 {get_entry(s['rsi'])}")
        lines.append(f"   💡 {get_highlight(s)}")
        if i < len(selected) - 1:
            lines.append("─────────")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━")
    lines.append("⚠️ 참고용이며 투자 판단은 본인 책임입니다.")

    return '\n'.join(lines)


# ============================================================
# 메인 함수
# ============================================================
def main():
    # 날짜 계산
    TODAY = get_korea_now().strftime('%Y%m%d')
    BASE_DATE = get_previous_trading_date(TODAY)

    print(f"오늘: {TODAY}, 분석기준일: {BASE_DATE}")

    if BASE_DATE is None:
        print("거래일을 찾을 수 없습니다.")
        sys.exit(1)

    # ============================================================
    # 시장 지수
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
    except Exception:
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
    portfolio_files = sorted(glob.glob(str(OUTPUT_DIR / 'portfolio_*.csv')), reverse=True)
    portfolio_files = [f for f in portfolio_files if 'strategy_' not in f and 'report' not in f]

    if not portfolio_files:
        print("통합 포트폴리오 파일을 찾을 수 없습니다. create_current_portfolio.py를 먼저 실행하세요.")
        sys.exit(1)

    print(f"포트폴리오 파일: {Path(portfolio_files[0]).name}")

    portfolio = pd.read_csv(portfolio_files[0], encoding='utf-8-sig')
    portfolio['종목코드'] = portfolio['종목코드'].astype(str).str.zfill(6)

    ticker_names = dict(zip(portfolio['종목코드'], portfolio['종목명']))

    if '통합순위' in portfolio.columns:
        portfolio_ranks = dict(zip(portfolio['종목코드'], portfolio['통합순위']))
        rank_label = '통합순위'
    elif '멀티팩터_순위' in portfolio.columns:
        portfolio_ranks = dict(zip(portfolio['종목코드'], portfolio['멀티팩터_순위']))
        rank_label = '멀티팩터_순위'
    else:
        portfolio_ranks = {t: i+1 for i, t in enumerate(portfolio['종목코드'])}
        rank_label = '순위'

    portfolio_per = dict(zip(portfolio['종목코드'], portfolio.get('PER', pd.Series()))) if 'PER' in portfolio.columns else {}
    portfolio_pbr = dict(zip(portfolio['종목코드'], portfolio.get('PBR', pd.Series()))) if 'PBR' in portfolio.columns else {}
    portfolio_roe = dict(zip(portfolio['종목코드'], portfolio.get('ROE', pd.Series()))) if 'ROE' in portfolio.columns else {}
    portfolio_fwd_per = dict(zip(portfolio['종목코드'], portfolio.get('forward_per', pd.Series()))) if 'forward_per' in portfolio.columns else {}

    print(f"포트폴리오: {len(portfolio)}개 종목 ({rank_label} 기준)")

    # ============================================================
    # 전 종목 기술지표 분석
    # ============================================================
    print("\n포트폴리오 기술지표 계산 중...")
    stock_analysis = []

    for _, row in portfolio.iterrows():
        ticker = row['종목코드']
        name = row['종목명']
        tech = get_stock_technical(ticker, BASE_DATE)

        if tech is None:
            print(f"  {name}({ticker}): 데이터 없음, 건너뜀")
            continue

        rank = portfolio_ranks.get(ticker, 31)

        stock_analysis.append({
            'ticker': ticker,
            'name': name,
            'rank': rank,
            'per': portfolio_per.get(ticker, None),
            'pbr': portfolio_pbr.get(ticker, None),
            'roe': portfolio_roe.get(ticker, None),
            'fwd_per': portfolio_fwd_per.get(ticker, None),
            'sector': SECTOR_DB.get(ticker, '기타'),
            **tech,
        })
        print(f"  {name}: {rank_label} {rank:.0f}위, RSI {tech['rsi']:.0f}, 52주 {tech['w52_pct']:.0f}%")

    stock_analysis.sort(key=lambda x: x['rank'])

    # ============================================================
    # 메시지 구성
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

💡 전략 v3.2

• 유니버스: 시총3000억↑ 거래대금차등(대형50억/중소형20억) PER≤60 PBR≤10

[1단계] 마법공식 사전필터 → 상위 200개
• 이익수익률↑ + ROIC↑ = 근본 우량주 선별

[2단계] 멀티팩터 순위 → 최종 {n_total}개
• Value 50% + Quality 30% + Momentum 20%
• PER/PBR: pykrx 실시간 데이터

━━━━━━━━━━━━━━━━━━━
🏆 통합순위 TOP 20
━━━━━━━━━━━━━━━━━━━
"""

    top_n = min(20, len(stock_analysis))
    msg1b = None

    for i, s in enumerate(stock_analysis[:top_n]):
        block = format_stock_detail(s)
        if msg1b is None and len(msg1) + len(block) > 3800 and i > 0:
            msg1b = f"🏆 통합순위 TOP 20 (계속)\n━━━━━━━━━━━━━━━━━━━\n"
        if msg1b is not None:
            msg1b += block
        else:
            msg1 += block

    messages = [msg1]
    if msg1b:
        messages.append(msg1b)

    # ============================================================
    # 텔레그램 전송
    # ============================================================
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
        target_id = PRIVATE_CHAT_ID or TELEGRAM_CHAT_ID
        results = []
        for msg in messages:
            r = requests.post(url, data={'chat_id': target_id, 'text': msg})
            results.append(r.status_code)
        print(f'\n테스트 메시지 전송: {", ".join(map(str, results))}')

    # ============================================================
    # AI 브리핑 (Gemini) — 채널+개인봇 전송
    # ============================================================
    try:
        from gemini_analysis import run_ai_analysis
        ai_msg = run_ai_analysis(None, stock_analysis)

        if ai_msg:
            print(f"\n=== AI 브리핑 ({len(ai_msg)}자) ===")
            print(ai_msg[:500] + '...' if len(ai_msg) > 500 else ai_msg)

            if IS_GITHUB_ACTIONS:
                r = requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': ai_msg, 'parse_mode': 'HTML'})
                print(f'AI 브리핑 채널 전송: {r.status_code}')
                if PRIVATE_CHAT_ID:
                    r = requests.post(url, data={'chat_id': PRIVATE_CHAT_ID, 'text': ai_msg, 'parse_mode': 'HTML'})
                    print(f'AI 브리핑 개인 전송: {r.status_code}')
            else:
                target_id = PRIVATE_CHAT_ID or TELEGRAM_CHAT_ID
                r = requests.post(url, data={'chat_id': target_id, 'text': ai_msg, 'parse_mode': 'HTML'})
                print(f'AI 브리핑 전송: {r.status_code}')
        else:
            print("\nAI 브리핑 스킵 (결과 없음)")
    except Exception as e:
        print(f"\nAI 브리핑 실패 (계속 진행): {e}")

    # ============================================================
    # 퀀트 TOP 5 추천 — 채널+개인봇 전송
    # ============================================================
    try:
        selected = select_top5(stock_analysis)
        if len(selected) >= 5:
            pick_msg = format_recommendation(selected)
            print(f"\n=== 퀀트 TOP 5 ({len(pick_msg)}자) ===")
            print(pick_msg)

            if IS_GITHUB_ACTIONS:
                r = requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': pick_msg})
                print(f'TOP 5 채널 전송: {r.status_code}')
                if PRIVATE_CHAT_ID:
                    r = requests.post(url, data={'chat_id': PRIVATE_CHAT_ID, 'text': pick_msg})
                    print(f'TOP 5 개인 전송: {r.status_code}')
            else:
                target_id = PRIVATE_CHAT_ID or TELEGRAM_CHAT_ID
                r = requests.post(url, data={'chat_id': target_id, 'text': pick_msg})
                print(f'TOP 5 전송: {r.status_code}')
        else:
            print(f"\nTOP 5 스킵 (위험 플래그 없는 종목 부족: {len(selected)}개)")
    except Exception as e:
        print(f"\nTOP 5 추천 실패 (계속 진행): {e}")

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


if __name__ == '__main__':
    main()
