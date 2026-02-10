"""
한국주식 퀀트 텔레그램 v5.0 — Slow In, Fast Out

3섹션 구조:
  1. Death List (50위 이탈 종목)
  2. 매수 추천 (3일 교집합 Top 30, 종목당 15%)
  3. Survivors (1~50위 생존 리스트)

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
from ranking_manager import (
    load_ranking, load_recent_rankings, save_ranking,
    compute_3day_intersection, compute_death_list, get_survivors,
    cleanup_old_rankings, get_available_ranking_dates,
)

# ============================================================
# 상수/설정
# ============================================================
KST = ZoneInfo('Asia/Seoul')
CACHE_DIR = Path('data_cache')
OUTPUT_DIR = Path('output')
WEIGHT_PER_STOCK = 15  # 종목당 비중 %

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


def get_recent_trading_dates(n=3):
    """최근 N개 거래일 찾기 (휴장일 자동 대응)"""
    today = get_korea_now()
    dates = []
    for i in range(1, 30):
        date = (today - timedelta(days=i)).strftime('%Y%m%d')
        try:
            df = stock.get_market_cap(date, market='KOSPI')
            if not df.empty and df.iloc[:, 0].sum() > 0:
                dates.append(date)
                if len(dates) >= n:
                    break
        except Exception:
            continue
    return dates


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

        return {
            'price': price, 'daily_chg': daily_chg,
            'rsi': rsi, 'w52_pct': w52_pct,
        }
    except Exception as e:
        print(f"  기술지표 실패 {ticker_str}: {e}")
        return None


# ============================================================
# 시장 이평선 경고
# ============================================================
def _calc_market_warnings(kospi_df, kosdaq_df):
    """KOSPI/KOSDAQ 이평선 상태를 진단하여 경고 메시지 리스트 반환"""
    warnings = []

    for name, df in [('코스피', kospi_df), ('코스닥', kosdaq_df)]:
        if df is None or len(df) < 5:
            continue

        close = df.iloc[:, 3]  # 종가 컬럼
        current = close.iloc[-1]

        ma5 = close.rolling(5).mean().iloc[-1] if len(close) >= 5 else None
        ma20 = close.rolling(20).mean().iloc[-1] if len(close) >= 20 else None
        ma60 = close.rolling(60).mean().iloc[-1] if len(close) >= 60 else None

        signals = []

        # 1) 5일선 이탈/위
        if ma5 is not None:
            if current < ma5:
                signals.append("5일선↓")
            else:
                signals.append("5일선↑")

        # 2) 20일선 이탈/위
        if ma20 is not None:
            if current < ma20:
                signals.append("20일선↓")

        # 3) 60일선 이탈/위
        if ma60 is not None:
            if current < ma60:
                signals.append("60일선↓")

        # 4) 데드크로스 (MA5 < MA20)
        if ma5 is not None and ma20 is not None:
            if ma5 < ma20:
                signals.append("단기DC")

        # 경고 수준 판단
        down_count = sum(1 for s in signals if '↓' in s or 'DC' in s)

        if down_count == 0:
            continue  # 양호 → 경고 안 함
        elif down_count <= 1:
            icon = "⚡"
        elif down_count <= 2:
            icon = "⚠️"
        else:
            icon = "🚨"

        warnings.append(f"{icon} {name}: {' '.join(signals)}")

    return warnings


# ============================================================
# 메시지 포맷터
# ============================================================
def format_death_list(death_list: list) -> str:
    """Section 1: Death List 메시지 포맷"""
    if not death_list:
        return ""

    lines = [
        "🚨 오늘의 탈락자 (Death List)",
        "━━━━━━━━━━━━━━━━━━━",
        "어제 Top 50 → 오늘 51위 밖으로 이탈한 종목",
        "",
    ]

    for i, item in enumerate(death_list, 1):
        name = item['name']
        y_rank = item['yesterday_rank']
        sector = SECTOR_DB.get(item['ticker'], '기타')
        lines.append(f"{i}. {name} ({y_rank}위 📉 이탈) · {sector}")

    lines.append("")
    lines.append("⚠️ 보유 중이라면 매도를 검토하세요.")
    lines.append("")

    return '\n'.join(lines)


def format_buy_recommendations(picks: list, base_date_str: str) -> str:
    """Section 2: 매수 추천 메시지 포맷"""
    now = get_korea_now()

    if not picks:
        lines = [
            "━━━━━━━━━━━━━━━━━━━",
            "💎 매수 추천",
            "━━━━━━━━━━━━━━━━━━━",
            f"📅 {base_date_str} 기준",
            "",
            "오늘은 3일 연속 검증을 통과한 종목이 없습니다.",
            "📋 관망 — 무리하게 진입하지 않는 것도 전략입니다.",
            "",
        ]
        return '\n'.join(lines)

    n = len(picks)
    total_weight = n * WEIGHT_PER_STOCK
    cash_weight = 100 - total_weight

    medal_icons = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    medals = medal_icons[:n] if n <= 10 else medal_icons + [f"({i+1})" for i in range(10, n)]

    lines = [
        "━━━━━━━━━━━━━━━━━━━",
        f"💎 매수 추천 ({n}종목, 총 {total_weight}%)",
        "━━━━━━━━━━━━━━━━━━━",
        f"📅 {base_date_str} 기준",
        f"3일 연속 Top 30 교집합 검증 완료",
        "",
    ]

    for i, pick in enumerate(picks):
        ticker = pick['ticker']
        name = pick['name']
        sector = SECTOR_DB.get(ticker, '기타')
        w_rank = pick['weighted_rank']

        # 기술지표 수집
        tech = pick.get('_tech')
        if tech:
            price_str = f"{tech['price']:,.0f}원 ({tech['daily_chg']:+.2f}%)"
            rsi_str = f"RSI {tech['rsi']:.0f}"
            w52_str = f"52주 {tech['w52_pct']:+.0f}%"
        else:
            price_str = ""
            rsi_str = ""
            w52_str = ""

        # PER/PBR/ROE
        factor_parts = []
        per = pick.get('per')
        if per:
            per_str = f"PER {per:.1f}"
            fwd = pick.get('fwd_per')
            if fwd:
                per_str += f"→{fwd:.1f}"
            factor_parts.append(per_str)
        pbr = pick.get('pbr')
        if pbr:
            factor_parts.append(f"PBR {pbr:.1f}")
        roe = pick.get('roe')
        if roe:
            factor_parts.append(f"ROE {roe:.1f}%")
        factor_str = ' | '.join(factor_parts)

        # 3일 순위 변동
        rank_history = f"T0:{pick['rank_t0']} T1:{pick['rank_t1']} T2:{pick['rank_t2']}"

        lines.append(f"{medals[i]} {name} ({ticker}) · {sector}")
        lines.append(f"   비중 {WEIGHT_PER_STOCK}% | 가중순위 {w_rank}")
        if price_str:
            lines.append(f"   💰 {price_str}")
        if factor_str:
            lines.append(f"   📊 {factor_str}")
        if rsi_str:
            lines.append(f"   📈 {rsi_str} | {w52_str} | {rank_history}")
        if i < len(picks) - 1:
            lines.append("─────────")

    lines.append("")
    if cash_weight > 0:
        lines.append(f"💰 현금 {cash_weight}%")
    lines.append("")
    lines.append("⚠️ 참고용이며 투자 판단은 본인 책임입니다.")
    lines.append("")

    return '\n'.join(lines)


def format_survivors(survivors: list) -> str:
    """Section 3: Survivors (1~50위) 메시지 포맷"""
    if not survivors:
        return ""

    lines = [
        "━━━━━━━━━━━━━━━━━━━",
        "✅ 생존 리스트 (Top 50)",
        "━━━━━━━━━━━━━━━━━━━",
        "보유 종목이 아래에 있으면 안전합니다.",
        "없으면 Death List를 확인하세요.",
        "",
    ]

    # 쉼표 구분 나열
    names = [f"{s['name']}" for s in survivors]
    lines.append(', '.join(names))
    lines.append("")

    return '\n'.join(lines)


# ============================================================
# 메인 함수
# ============================================================
def main():
    # ============================================================
    # 날짜 계산 (최근 3거래일)
    # ============================================================
    TODAY = get_korea_now().strftime('%Y%m%d')
    trading_dates = get_recent_trading_dates(3)

    if not trading_dates:
        print("거래일을 찾을 수 없습니다.")
        sys.exit(1)

    BASE_DATE = trading_dates[0]  # T-0
    print(f"오늘: {TODAY}")
    print(f"최근 3거래일: T-0={trading_dates[0]}, ", end="")
    if len(trading_dates) >= 2:
        print(f"T-1={trading_dates[1]}, ", end="")
    if len(trading_dates) >= 3:
        print(f"T-2={trading_dates[2]}")
    else:
        print()

    # ============================================================
    # 시장 지수 + 이평선 경고
    # ============================================================
    idx_start = (datetime.strptime(BASE_DATE, '%Y%m%d') - timedelta(days=120)).strftime('%Y%m%d')
    kospi_idx = stock.get_index_ohlcv(idx_start, BASE_DATE, '1001')
    kosdaq_idx = stock.get_index_ohlcv(idx_start, BASE_DATE, '2001')

    kospi_close = kospi_idx.iloc[-1, 3]
    kospi_prev = kospi_idx.iloc[-2, 3] if len(kospi_idx) > 1 else kospi_close
    kospi_chg = ((kospi_close / kospi_prev) - 1) * 100

    kosdaq_close = kosdaq_idx.iloc[-1, 3]
    kosdaq_prev = kosdaq_idx.iloc[-2, 3] if len(kosdaq_idx) > 1 else kosdaq_close
    kosdaq_chg = ((kosdaq_close / kosdaq_prev) - 1) * 100

    if kospi_chg > 1:
        market_color = "🟢"
    elif kospi_chg < -1:
        market_color = "🔴"
    else:
        market_color = "🟡"

    base_date_str = f"{BASE_DATE[:4]}년 {BASE_DATE[4:6]}월 {BASE_DATE[6:]}일"

    # 이평선 경고 계산
    market_warnings = _calc_market_warnings(kospi_idx, kosdaq_idx)
    print(f"\n[시장 이평선 경고]")
    if market_warnings:
        for w in market_warnings:
            print(f"  {w}")
    else:
        print("  경고 없음 — 시장 양호")

    # ============================================================
    # 순위 데이터 로드 (3일)
    # ============================================================
    print("\n[순위 데이터 로드]")
    ranking_data = load_recent_rankings(trading_dates)

    rankings_t0 = ranking_data.get(trading_dates[0])
    rankings_t1 = ranking_data.get(trading_dates[1]) if len(trading_dates) >= 2 else None
    rankings_t2 = ranking_data.get(trading_dates[2]) if len(trading_dates) >= 3 else None

    # T-0 필수
    if rankings_t0 is None:
        print(f"T-0 ({trading_dates[0]}) 순위 없음! create_current_portfolio.py를 먼저 실행하세요.")
        sys.exit(1)

    print(f"  T-0 ({trading_dates[0]}): {len(rankings_t0.get('rankings', []))}개 종목")

    cold_start = False
    if rankings_t1 is None or rankings_t2 is None:
        cold_start = True
        missing = []
        if rankings_t1 is None and len(trading_dates) >= 2:
            missing.append(f"T-1 ({trading_dates[1]})")
        if rankings_t2 is None and len(trading_dates) >= 3:
            missing.append(f"T-2 ({trading_dates[2]})")
        print(f"  콜드 스타트: {', '.join(missing)} 순위 없음")
        print(f"  → 3일 교집합 불가, 관망 메시지 전송")
    else:
        print(f"  T-1 ({trading_dates[1]}): {len(rankings_t1.get('rankings', []))}개 종목")
        print(f"  T-2 ({trading_dates[2]}): {len(rankings_t2.get('rankings', []))}개 종목")

    # ============================================================
    # Section 1: Death List
    # ============================================================
    print("\n[Death List 계산]")
    death_list = []
    if rankings_t1 is not None:
        death_list = compute_death_list(rankings_t0, rankings_t1)
        print(f"  탈락 종목: {len(death_list)}개")
        for d in death_list:
            print(f"    {d['name']}: {d['yesterday_rank']}위 → 이탈")
    else:
        print("  T-1 순위 없음 → Death List 생략")

    # ============================================================
    # Section 2: 3일 교집합 매수 추천
    # ============================================================
    print("\n[3일 교집합 매수 추천]")
    picks = []
    if not cold_start:
        picks = compute_3day_intersection(rankings_t0, rankings_t1, rankings_t2)
        print(f"  3일 교집합 통과: {len(picks)}개 종목")

        # 기술지표 보강 (매수 추천 종목만)
        for pick in picks:
            tech = get_stock_technical(pick['ticker'], BASE_DATE)
            pick['_tech'] = tech
            if tech:
                print(f"    {pick['name']}: 가중순위 {pick['weighted_rank']}, RSI {tech['rsi']:.0f}, 52주 {tech['w52_pct']:.0f}%")
            else:
                print(f"    {pick['name']}: 가중순위 {pick['weighted_rank']} (기술지표 실패)")
    else:
        print("  콜드 스타트 → 추천 없음 (관망)")

    # ============================================================
    # Section 3: Survivors
    # ============================================================
    survivors = get_survivors(rankings_t0)
    print(f"\n[Survivors] Top 50: {len(survivors)}개 종목")

    # ============================================================
    # 메시지 구성
    # ============================================================
    today_str = f"{TODAY[4:6]}월{TODAY[6:]}일"

    # 헤더
    warning_lines = ""
    if market_warnings:
        warning_lines = "\n".join(market_warnings)
        warning_lines = f"\n{warning_lines}\n📋 이평선 하회 시 신규 진입을 자제하세요.\n"

    header = f"""📊 퀀트 포트폴리오 v5.0
━━━━━━━━━━━━━━━━━━━
📅 {base_date_str} 기준
{market_color} 코스피 {kospi_close:,.0f} ({kospi_chg:+.2f}%) | 코스닥 {kosdaq_close:,.0f} ({kosdaq_chg:+.2f}%)
━━━━━━━━━━━━━━━━━━━
{warning_lines}
💡 Slow In, Fast Out 전략
• 3일 연속 Top 30 교집합 검증
• MA60 하회 종목 원천 차단
• 50위 이탈 시 즉시 Death List 경보

"""

    # 각 섹션 생성
    death_section = format_death_list(death_list) if death_list else ""
    buy_section = format_buy_recommendations(picks, base_date_str)
    survivor_section = format_survivors(survivors)

    # 메시지 조합
    msg1 = header
    if death_section:
        msg1 += death_section
    msg1 += buy_section

    # Survivors는 별도 메시지 (길이 제한)
    msg2 = survivor_section if survivor_section else None

    messages = [msg1]
    if msg2:
        messages.append(msg2)

    # ============================================================
    # 텔레그램 전송
    # ============================================================
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'

    PRIVATE_CHAT_ID = getattr(__import__('config'), 'TELEGRAM_PRIVATE_ID', None)
    IS_GITHUB_ACTIONS = os.environ.get('GITHUB_ACTIONS') == 'true'

    print("\n=== 메시지 미리보기 ===")
    print(msg1[:2000])
    if msg2:
        print("\n--- Survivors ---")
        print(msg2[:500])
    print(f"\n메시지 수: {len(messages)}개 (msg1: {len(msg1)}자{f', msg2: {len(msg2)}자' if msg2 else ''})")

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
    # AI 브리핑 (Gemini) — 매수 추천 종목 대상
    # ============================================================
    if picks:
        try:
            from gemini_analysis import run_ai_analysis
            # picks를 stock_analysis 형식으로 변환
            stock_list = []
            for pick in picks:
                tech = pick.get('_tech', {}) or {}
                stock_list.append({
                    'ticker': pick['ticker'],
                    'name': pick['name'],
                    'rank': pick['rank_t0'],
                    'per': pick.get('per'),
                    'pbr': pick.get('pbr'),
                    'roe': pick.get('roe'),
                    'fwd_per': pick.get('fwd_per'),
                    'sector': SECTOR_DB.get(pick['ticker'], '기타'),
                    'rsi': tech.get('rsi', 50),
                    'w52_pct': tech.get('w52_pct', 0),
                    'daily_chg': tech.get('daily_chg', 0),
                    'vol_ratio': 1,
                    'price': tech.get('price', 0),
                })

            ai_msg = run_ai_analysis(None, stock_list)

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
    else:
        print("\nAI 브리핑 스킵 (추천 종목 없음)")

    # ============================================================
    # 정리
    # ============================================================
    cleanup_old_rankings(keep_days=30)

    print(f'\nDeath List: {len(death_list)}개')
    print(f'매수 추천: {len(picks)}개 ({"관망" if not picks else f"총 {len(picks)*WEIGHT_PER_STOCK}%"})')
    print(f'Survivors: {len(survivors)}개')
    print('\n완료!')


if __name__ == '__main__':
    main()
