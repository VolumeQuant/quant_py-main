"""
한국주식 퀀트 텔레그램 v8.1 — 후보 → AI → 최종

메시지 구조:
  📖 투자 가이드 — 시스템 소개 + 활용법
  [1/3] 📊 시장 + Top 30 — 보유 확인
  [2/3] 🛡️ AI 리스크 필터 — 위험 요소 점검
  [3/3] 🎯 최종 추천 — 최종 포트폴리오

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
    compute_3day_intersection, get_daily_changes,
    get_stock_status, cleanup_old_rankings, get_available_ranking_dates,
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
def format_overview(has_ai: bool = False):
    """📖 투자 가이드 — 시스템 개요, 선정 과정, 보유/매도 기준"""
    lines = [
        '━━━━━━━━━━━━━━━━━━━',
        '      📖 투자 가이드',
        '━━━━━━━━━━━━━━━━━━━',
        '',
        '🔎 <b>어떤 종목을 찾나요?</b>',
        '국내 전 종목을 매일 자동 분석해서',
        '"좋은 회사를 싸게 살 수 있는 타이밍"을 찾아요.',
        '',
        '📊 <b>어떻게 골라요?</b>',
        '매일 새벽 5단계로 걸러요.',
        '',
        '① 시가총액·재무 건전성으로 1차 스크리닝',
        '② 가치 + 수익성 + 모멘텀 멀티팩터 점수 산출',
        '③ 60일 이동평균선 위 종목만 통과',
        '④ 3거래일 연속 상위 30위 유지 → 검증 완료 ✅',
        '⑤ AI 위험 점검 후 최종 매수 후보 선정',
        '',
        '⏱️ <b>얼마나 보유하나요?</b>',
        'Top 30에 남아있는 동안은 계속 보유하세요.',
        '목록에서 빠지면 매도를 검토하면 돼요.',
        '',
        '📩 <b>오늘의 메시지</b>',
    ]
    if has_ai:
        lines.append('[1/3] 📊 시장 + Top 30')
        lines.append('[2/3] 🛡️ AI 리스크 필터')
        lines.append('[3/3] 🎯 최종 추천')
    else:
        lines.append('📊 시장 + Top 30')
    return '\n'.join(lines)


def format_top30(pipeline: list, exited: list, cold_start: bool = False, has_next: bool = False) -> str:
    """Top 30 목록 — 상태별 그룹핑"""
    if not pipeline:
        return ""

    lines = [
        "─────────────────",
        "<b>📋 Top 30 — 보유 확인</b>",
        "─────────────────",
        "목록에 있으면 보유, 없으면 매도 검토.",
        "",
    ]

    verified = [s for s in pipeline if s['status'] == '✅']
    two_day = [s for s in pipeline if s['status'] == '⏳']
    new_stocks = [s for s in pipeline if s['status'] == '🆕']

    groups_added = False
    if verified:
        names = ', '.join(f"{s['name']}({s['rank']})" for s in verified)
        lines.append(f"✅ 3일 검증: {names}")
        groups_added = True

    if two_day:
        if groups_added:
            lines.append("")
        names = ', '.join(f"{s['name']}({s['rank']})" for s in two_day)
        lines.append(f"⏳ 내일 검증: {names}")
        groups_added = True

    if new_stocks:
        if groups_added:
            lines.append("")
        names = ', '.join(f"{s['name']}({s['rank']})" for s in new_stocks)
        lines.append(f"🆕 신규 진입: {names}")

    if exited:
        lines.append("")
        exit_names = ', '.join(e['name'] for e in exited)
        lines.append(f"⛔ 이탈: {exit_names}")
        lines.append("보유 중이라면 매도를 검토하세요.")

    if cold_start:
        lines.append("")
        lines.append("📊 데이터 축적 중 — 3일 완료 시 매수 후보가 선정돼요.")

    lines.append("")
    if has_next:
        lines.append("👉 다음: AI 리스크 필터 [2/3]")
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


def format_buy_recommendations(picks: list, base_date_str: str, universe_count: int = 0, ai_picks_text: str = None) -> str:
    """최종 추천 메시지 — AI 멘트 + 구분선"""
    if not picks:
        lines = [
            "━━━━━━━━━━━━━━━━━━━",
            "    🎯 최종 추천",
            "━━━━━━━━━━━━━━━━━━━",
            "",
            "3일 연속 상위권을 유지한 종목이 없어요.",
            "무리한 진입보다 관망도 전략이에요.",
            "",
        ]
        return '\n'.join(lines)

    n = len(picks)
    cash_weight = 100 - n * WEIGHT_PER_STOCK

    if universe_count > 0:
        funnel = f"{universe_count:,}종목 → Top 30 → ✅ 검증 → 최종 {n}종목"
    else:
        funnel = f"Top 30 → ✅ 검증 → 최종 {n}종목"

    lines = [
        "━━━━━━━━━━━━━━━━━━━",
        " [3/3] 🎯 최종 추천",
        "━━━━━━━━━━━━━━━━━━━",
        f"📅 {base_date_str} 기준",
        funnel,
        "",
    ]

    # 비중 한눈에 보기
    weight_parts = [f"{p['name']} {WEIGHT_PER_STOCK}%" for p in picks]
    lines.append("📊 <b>비중 한눈에 보기</b>")
    lines.append(' · '.join(weight_parts))
    if cash_weight > 0:
        lines.append(f"현금 {cash_weight}%")
    lines.append("")

    # 종목별 설명
    if ai_picks_text:
        lines.append("─────────────────")
        lines.append(ai_picks_text)
        lines.append("─────────────────")
    else:
        # Fallback: AI 실패 시
        lines.append("─────────────────")
        for i, pick in enumerate(picks):
            name = pick['name']
            ticker = pick['ticker']
            sector = SECTOR_DB.get(ticker, '기타')
            rationale = _get_buy_rationale(pick)
            lines.append(f"<b>{i+1}. {name}({ticker}) · {WEIGHT_PER_STOCK}%</b>")
            lines.append(f"{sector} · {rationale}")
            if i < n - 1:
                lines.append("──────────────────")
        lines.append("─────────────────")

    lines.append("")
    lines.append("💡 <b>활용법</b>")
    lines.append("· 비중대로 분산 투자를 권장해요")
    lines.append("· Top 30에서 빠지면 매도 검토")
    lines.append("⚠️ 참고용이며, 투자 판단은 본인 책임이에요.")

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
    # 종목 파이프라인 상태 (✅/⏳/🆕)
    # ============================================================
    pipeline = get_stock_status(rankings_t0, rankings_t1, rankings_t2)
    available_days = sum(1 for r in [rankings_t0, rankings_t1, rankings_t2] if r is not None)
    v_count = sum(1 for s in pipeline if s['status'] == '✅')
    d_count = sum(1 for s in pipeline if s['status'] == '⏳')
    n_count = sum(1 for s in pipeline if s['status'] == '🆕')
    print(f"\n[파이프라인] ✅ {v_count}개, ⏳ {d_count}개, 🆕 {n_count}개 (데이터 {available_days}일)")

    # ============================================================
    # Section 1: 일일 변동 (콜드 스타트 시 생략)
    # ============================================================
    print("\n[일일 변동]")
    entered, exited = [], []
    if cold_start:
        print("  콜드 스타트 → 일일 변동 생략")
    elif rankings_t1:
        entered, exited = get_daily_changes(rankings_t0, rankings_t1)
        print(f"  진입: {len(entered)}개, 이탈: {len(exited)}개")
        for e in entered:
            print(f"    ↑ {e['name']} ({e['rank']}위)")
        for e in exited:
            print(f"    ↓ {e['name']} ({e['rank']}위)")

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
    # Section 3: Top 30 목록
    # ============================================================
    print(f"\n[Top 30] {len(pipeline)}개 종목")

    # ============================================================
    # AI 리스크 필터 생성 (Gemini) — 메시지 전송 전에 미리 생성
    # ============================================================
    ai_msg = None
    if picks:
        try:
            from gemini_analysis import run_ai_analysis
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
                print(f"\n=== AI 리스크 필터 ({len(ai_msg)}자) ===")
                print(ai_msg[:500] + '...' if len(ai_msg) > 500 else ai_msg)
            else:
                print("\nAI 리스크 필터 스킵 (결과 없음)")
        except Exception as e:
            print(f"\nAI 리스크 필터 실패 (계속 진행): {e}")
    else:
        print("\nAI 리스크 필터 스킵 (추천 종목 없음)")

    # ============================================================
    # 메시지 구성 — Guide → [1/3] 시장+Top30 → [2/3] AI → [3/3] 최종
    # ============================================================
    has_ai = ai_msg is not None

    # 경고 블록
    warning_block = ""
    if market_warnings:
        warning_block = "\n" + "\n".join(market_warnings)
        warning_block += "\n신규 매수 시 유의하세요.\n"

    # [1/2] 본문 헤더 (타이틀 + 시장 + 읽는 법)
    header_lines = []
    header_lines.append('━━━━━━━━━━━━━━━━━━━')
    if has_ai:
        header_lines.append(' [1/3] 📊 시장 + Top 30')
    else:
        header_lines.append('    📊 시장 + Top 30')
    header_lines.append('━━━━━━━━━━━━━━━━━━━')
    header_lines.append(f'📅 {base_date_str} 기준')
    header_lines.append('─────────────────')
    header_lines.append(f'{kospi_color} 코스피  {kospi_close:,.0f} ({kospi_chg:+.2f}%)')
    header_lines.append(f'{kosdaq_color} 코스닥  {kosdaq_close:,.0f} ({kosdaq_chg:+.2f}%)')
    if warning_block:
        header_lines.append(warning_block.rstrip())
    header_lines.append('')
    header_lines.append('💡 <b>읽는 법</b>')
    header_lines.append('✅ 3일 연속 Top 30 → 검증 완료')
    header_lines.append('⏳ 2일 연속 → 내일 검증 가능')
    header_lines.append('🆕 오늘 첫 진입 → 지켜보세요')
    header_lines.append('')
    header = '\n'.join(header_lines)

    # [1/2] 섹션: Top 30만 (상세 카드는 [2/2]에서)
    top30_section = format_top30(pipeline, exited, cold_start, has_next=has_ai)

    # 개요 (첫 번째 메시지)
    msg_overview = format_overview(has_ai)

    # [1/2] 본문 (시장 + Top 30)
    msg_main = header
    if top30_section:
        msg_main += top30_section

    # [2/3] AI 리스크 필터 (AI 있을 때만)
    msg_ai = None
    if ai_msg:
        msg_ai = ai_msg + '\n\n👉 다음: 최종 추천 [3/3]'

    # [3/3] 최종 추천 — AI 종목별 설명 (AI 있을 때만)
    msg_final = None
    if ai_msg:
        universe_count = (rankings_t0.get('metadata') or {}).get('total_universe', 0)
        ai_picks_text = None
        try:
            from gemini_analysis import run_final_picks_analysis
            final_stock_list = []
            for pick in picks:
                tech = pick.get('_tech', {}) or {}
                final_stock_list.append({
                    'ticker': pick['ticker'],
                    'name': pick['name'],
                    'sector': SECTOR_DB.get(pick['ticker'], '기타'),
                    'per': pick.get('per'),
                    'fwd_per': pick.get('fwd_per'),
                    'roe': pick.get('roe'),
                    'rsi': tech.get('rsi', 50),
                    'w52_pct': tech.get('w52_pct', 0),
                })
            ai_picks_text = run_final_picks_analysis(final_stock_list, WEIGHT_PER_STOCK, BASE_DATE)
        except Exception as e:
            print(f"최종 추천 AI 설명 실패 (fallback 사용): {e}")
        msg_final = format_buy_recommendations(picks, base_date_str, universe_count, ai_picks_text)

    # 메시지 리스트: Guide → [1/3] 시장+Top30 → [2/3] AI → [3/3] 최종
    messages = [msg_overview, msg_main]
    if msg_ai:
        messages.append(msg_ai)
    if msg_final:
        messages.append(msg_final)

    # ============================================================
    # 텔레그램 전송
    # ============================================================
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'

    PRIVATE_CHAT_ID = getattr(__import__('config'), 'TELEGRAM_PRIVATE_ID', None)
    IS_GITHUB_ACTIONS = os.environ.get('GITHUB_ACTIONS') == 'true'

    print("\n=== 메시지 미리보기 ===")
    for i, msg in enumerate(messages):
        print(f"\n--- 메시지 {i+1}/{len(messages)} ({len(msg)}자) ---")
        print(msg[:500])
    msg_sizes = ', '.join(f'{len(m)}자' for m in messages)
    print(f"\n메시지 수: {len(messages)}개 ({msg_sizes})")

    if IS_GITHUB_ACTIONS:
        if cold_start:
            target = PRIVATE_CHAT_ID or TELEGRAM_CHAT_ID
            print(f'\n콜드 스타트 — 채널 전송 스킵, 개인봇으로 전송 ({target[:6]}...)')
            results_cs = []
            for msg in messages:
                r = requests.post(url, data={'chat_id': target, 'text': msg, 'parse_mode': 'HTML'})
                results_cs.append(r.status_code)
            print(f'콜드 스타트 메시지 전송: {", ".join(map(str, results_cs))}')
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
    # 정리
    # ============================================================
    cleanup_old_rankings(keep_days=30)

    print(f'\n매수 추천: {len(picks)}개 ({"관망" if not picks else f"총 {len(picks)*WEIGHT_PER_STOCK}%"})')
    print(f'파이프라인: ✅ {v_count} · ⏳ {d_count} · 🆕 {n_count}')
    print(f'일일 변동: 진입 {len(entered)}개 · 이탈 {len(exited)}개')
    print('\n완료!')


if __name__ == '__main__':
    main()
