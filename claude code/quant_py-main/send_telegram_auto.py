"""
한국주식 퀀트 텔레그램 v5.1 — Slow In, Fast Out

4개 메시지 구조:
  1. 개요 — 분석 흐름 + 활용 가이드
  2. 본문 — 시장 지수 + 탈락 종목 + 매수 후보
  3. 생존 리스트 — Top 50 보유 확인
  4. AI 브리핑 — 매수 후보 대상 AI 분석 (0개면 스킵)

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
WEIGHT_PER_STOCK = 20  # 종목당 비중 % (5종목 × 20% = 100%)

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
def format_overview():
    """전략 개요 메시지 (첫 번째 메시지로 전송)"""
    return """<b>📊 퀀트 포트폴리오 — 활용 가이드</b>

매일 새벽, 국내 전 종목을 자동 분석합니다.

<b>▸ 종목은 이렇게 선정됩니다</b>
  ① 전 종목에서 시가총액·재무 건전성 스크리닝
  ② 가치 + 수익성 + 모멘텀 멀티팩터 점수 산출
  ③ 60일 이동평균선 위 종목만 통과
  ④ 3거래일 연속 상위 30위 유지 종목만 최종 선정

<b>▸ 매수·보유·매도 기준</b>
  매수 — '매수 후보'에 오른 종목을 각 15%씩 분산
  보유 — '생존 리스트'에 있는 동안 계속 보유
  매도 — '탈락 종목'에 이름이 뜨면 매도 검토

매일 이 리포트를 확인하시면 됩니다.
3일간 검증된 종목만 진입하고,
이탈 신호 발생 시 즉시 알려드립니다."""


def format_death_list(death_list: list) -> str:
    """탈락 종목 메시지 포맷"""
    if not death_list:
        return ""

    lines = [
        "─────────────────",
        "<b>⛔ 탈락 종목 — 매도 검토</b>",
        "─────────────────",
        "",
    ]

    for i, item in enumerate(death_list, 1):
        name = item['name']
        y_rank = item['yesterday_rank']
        t_rank = item.get('today_rank')
        sector = SECTOR_DB.get(item['ticker'], '기타')

        reasons = item.get('reasons')
        reason_str = f" [{' '.join(reasons)}]" if reasons else ""

        lines.append(f"{i}. <b>{name}</b> · {sector}{reason_str}")
        if t_rank is not None:
            lines.append(f"   어제 {y_rank}위 → 오늘 {t_rank}위")
        else:
            lines.append(f"   어제 {y_rank}위 → 유니버스 이탈")

    lines.append("")
    lines.append("이 종목을 보유 중이라면 매도를 검토하세요.")
    lines.append("")

    return '\n'.join(lines)


def _get_buy_rationale(pick) -> str:
    """한 줄 투자 근거 생성"""
    reasons = []

    fwd = pick.get('fwd_per')
    per = pick.get('per')
    roe = pick.get('roe')
    tech = pick.get('_tech') or {}

    if fwd and per and fwd < per and per > 0:
        reasons.append(f"실적 개선 (PER {per:.0f}→{fwd:.0f})")
    elif per and per < 10:
        reasons.append(f"저평가 PER {per:.1f}")

    if roe and roe > 15:
        reasons.append(f"ROE {roe:.0f}%")

    rsi = tech.get('rsi')
    if rsi and rsi < 35:
        reasons.append("과매도 구간")

    w52 = tech.get('w52_pct')
    if w52 and w52 < -30:
        reasons.append("52주 저점 부근")

    if not reasons:
        reasons.append("멀티팩터 상위")

    return ' · '.join(reasons[:2])


def format_buy_recommendations(picks: list, base_date_str: str) -> str:
    """매수 후보 메시지 포맷"""
    if not picks:
        lines = [
            "─────────────────",
            "<b>📋 매수 후보</b>",
            "─────────────────",
            "",
            "3일 연속 상위권을 유지한 종목이 없습니다.",
            "무리한 진입보다 관망도 전략입니다.",
            "",
        ]
        return '\n'.join(lines)

    n = len(picks)
    total_weight = n * WEIGHT_PER_STOCK
    cash_weight = 100 - total_weight

    lines = [
        "─────────────────",
        f"<b>💎 매수 후보 — {n}종목 (투자비중 {total_weight}%)</b>",
        "─────────────────",
        "3거래일 연속 Top 30 유지 종목",
        "",
    ]

    for i, pick in enumerate(picks):
        ticker = pick['ticker']
        name = pick['name']
        sector = SECTOR_DB.get(ticker, '기타')
        w_rank = pick['weighted_rank']

        # 기술지표
        tech = pick.get('_tech')
        if tech:
            price_str = f"{tech['price']:,.0f}원 ({tech['daily_chg']:+.2f}%)"
            rsi_val = tech['rsi']
            w52_val = tech['w52_pct']
        else:
            price_str = ""
            rsi_val = None
            w52_val = None

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
        factor_str = ' · '.join(factor_parts)

        # 3일 순위 안정성
        rank_str = f"{pick['rank_t0']}→{pick['rank_t1']}→{pick['rank_t2']}위"

        rationale = _get_buy_rationale(pick)
        lines.append(f"{i+1}. ✅ <b>{name}</b> ({ticker}) · {sector}")
        lines.append(f"   → {rationale}")
        lines.append(f"   비중 {WEIGHT_PER_STOCK}% · 가중순위 {w_rank}")
        if price_str:
            lines.append(f"   {price_str}")
        if factor_str:
            lines.append(f"   {factor_str}")
        if rsi_val is not None:
            lines.append(f"   RSI {rsi_val:.0f} · 52주대비 {w52_val:+.0f}% · 3일순위 {rank_str}")
        if i < len(picks) - 1:
            lines.append("")

    lines.append("")
    if cash_weight > 0:
        lines.append(f"잔여 현금 {cash_weight}%")
    lines.append("")
    lines.append("※ 참고용이며 투자 판단은 본인 책임입니다.")
    lines.append("")

    return '\n'.join(lines)


def format_survivors(survivors: list) -> str:
    """생존 리스트 (Top 50) 메시지 포맷"""
    if not survivors:
        return ""

    lines = [
        "─────────────────",
        "<b>✅ 생존 리스트 — 보유 유지</b>",
        "─────────────────",
        "아래 종목을 보유 중이라면 계속 보유하세요.",
        "목록에 없다면 '탈락 종목'을 확인하세요.",
        "",
    ]

    names = [f"{s['name']}({s['rank']})" for s in survivors]
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

    def _idx_color(chg):
        if chg > 1: return "🟢"
        elif chg < -1: return "🔴"
        else: return "🟡"

    kospi_color = _idx_color(kospi_chg)
    kosdaq_color = _idx_color(kosdaq_chg)

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

    # 경고 블록
    warning_block = ""
    if market_warnings:
        warning_block = "\n" + "\n".join(market_warnings)
        warning_block += "\n신규 매수 시 유의하세요.\n"

    # 헤더
    header = f"<b>📅 {base_date_str} 기준</b>\n"
    header += "─────────────────\n"
    header += f"{kospi_color} 코스피  {kospi_close:,.0f} ({kospi_chg:+.2f}%)\n"
    header += f"{kosdaq_color} 코스닥  {kosdaq_close:,.0f} ({kosdaq_chg:+.2f}%)\n"
    if warning_block:
        header += warning_block
    header += "\n"

    # 각 섹션 생성
    death_section = format_death_list(death_list) if death_list else ""
    buy_section = format_buy_recommendations(picks, base_date_str)
    survivor_section = format_survivors(survivors)

    # 개요 (첫 번째 메시지)
    msg_overview = format_overview()

    # 본문 (헤더 + Death List + 매수 후보)
    msg_main = header
    if death_section:
        msg_main += death_section
    msg_main += buy_section

    # 생존 리스트 (별도 메시지)
    msg_survivors = survivor_section if survivor_section else None

    messages = [msg_overview, msg_main]
    if msg_survivors:
        messages.append(msg_survivors)

    # ============================================================
    # 텔레그램 전송
    # ============================================================
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'

    PRIVATE_CHAT_ID = getattr(__import__('config'), 'TELEGRAM_PRIVATE_ID', None)
    IS_GITHUB_ACTIONS = os.environ.get('GITHUB_ACTIONS') == 'true'

    print("\n=== 메시지 미리보기 ===")
    print("--- 개요 ---")
    print(msg_overview[:500])
    print("\n--- 본문 ---")
    print(msg_main[:2000])
    if msg_survivors:
        print("\n--- 생존 리스트 ---")
        print(msg_survivors[:500])
    msg_sizes = ', '.join(f'{len(m)}자' for m in messages)
    print(f"\n메시지 수: {len(messages)}개 ({msg_sizes})")

    if IS_GITHUB_ACTIONS:
        # 콜드 스타트 시 채널 전송 스킵 (개인봇에만 전송)
        if cold_start:
            print('\n콜드 스타트 — 채널 전송 스킵 (아직 3일 데이터 미확보)')
        else:
            results = []
            for msg in messages:
                r = requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'})
                results.append(r.status_code)
            print(f'\n채널 메시지 전송: {", ".join(map(str, results))}')

        if PRIVATE_CHAT_ID:
            results_p = []
            for msg in messages:
                r = requests.post(url, data={'chat_id': PRIVATE_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'})
                results_p.append(r.status_code)
            print(f'개인 메시지 전송: {", ".join(map(str, results_p))}')
    else:
        target_id = PRIVATE_CHAT_ID or TELEGRAM_CHAT_ID
        results = []
        for msg in messages:
            r = requests.post(url, data={'chat_id': target_id, 'text': msg, 'parse_mode': 'HTML'})
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

            ai_msg = run_ai_analysis(None, stock_list, base_date=BASE_DATE)

            if ai_msg:
                print(f"\n=== AI 브리핑 ({len(ai_msg)}자) ===")
                print(ai_msg[:500] + '...' if len(ai_msg) > 500 else ai_msg)

                if IS_GITHUB_ACTIONS:
                    if not cold_start:
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
