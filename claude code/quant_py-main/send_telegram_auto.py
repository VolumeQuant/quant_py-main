"""
한국주식 퀀트 텔레그램 v41 — Signal + AI Risk + Watchlist

메시지 구조 (v41):
  📊 Signal — 결론 (뭘 살까)
  🤖 AI Risk — 맥락 (시장 환경 + 리스크)
  📋 Watchlist — 데이터 (Top 30 모니터링)

실행: python send_telegram_auto.py
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import pandas as pd
import numpy as np

# KRX 인증 (2026-02-27~ 로그인 필수)
import krx_auth
krx_auth.login()

from pykrx import stock
from datetime import datetime, timedelta
from pathlib import Path
import requests
import json
import os
import time
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from zoneinfo import ZoneInfo
from ranking_manager import (
    load_ranking, load_recent_rankings, save_ranking,
    get_daily_changes,
    get_stock_status, cleanup_old_rankings, get_available_ranking_dates,
    compute_rank_driver, MIN_RANK_CHANGE,
    weighted_score_100, ENTRY_SCORE_100, EXIT_SCORE_100,
)
from credit_monitor import (
    get_credit_status, format_credit_section, format_credit_compact,
    get_market_pick_level,
)

# ============================================================
# 상수/설정
# ============================================================
KST = ZoneInfo('Asia/Seoul')
STATE_DIR = Path(__file__).parent / 'state'
CACHE_DIR = Path('data_cache')
OUTPUT_DIR = Path('output')
WEIGHT_PER_STOCK = 20  # 종목당 기본 비중 % (picks 없을 때 fallback)

WEEKDAY_KR = ['월', '화', '수', '목', '금', '토', '일']


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


def _get_buy_rationale(pick) -> str:
    """한 줄 투자 근거 — 실제 팩터 점수 기반"""
    # 팩터 점수: value_s, quality_s, growth_s, momentum_s
    factors = [
        ('V', pick.get('value_s')),
        ('Q', pick.get('quality_s')),
        ('G', pick.get('growth_s')),
        ('M', pick.get('momentum_s')),
    ]

    strong = []   # z > 1.0
    weak = []     # z < -1.0
    for label, z in factors:
        if z is None:
            continue
        if z >= 1.0:
            strong.append(label)
        elif z <= -1.0:
            weak.append(label)

    NAMES = {'V': '밸류', 'Q': '퀄리티', 'G': '성장', 'M': '모멘텀'}

    if not strong and not weak:
        return '멀티팩터 균형'

    parts = []
    if strong:
        parts.append('·'.join(NAMES[s] for s in strong) + ' 상위')
    if weak:
        parts.append('·'.join(NAMES[w] for w in weak) + ' 약세')

    return ' | '.join(parts)


# ============================================================
# 시장 이평선 경고
# ============================================================
def _calc_market_warnings(kospi_df, kosdaq_df):
    """KOSPI/KOSDAQ 이평선 돌파/이탈 이벤트만 반환 (매일 표시 X)"""
    warnings = []

    for name, df in [('코스피', kospi_df), ('코스닥', kosdaq_df)]:
        if df is None or len(df) < 6:
            continue

        close = df.iloc[:, 3]  # 종가 컬럼
        today = close.iloc[-1]
        yesterday = close.iloc[-2]

        events = []
        for period, label in [(5, '5일선'), (20, '20일선'), (60, '60일선')]:
            if len(close) < period + 1:
                continue
            ma = close.rolling(period).mean()
            ma_today = ma.iloc[-1]
            ma_yesterday = ma.iloc[-2]

            was_above = yesterday >= ma_yesterday
            is_above = today >= ma_today

            if was_above and not is_above:
                events.append(f"{label} 이탈")
            elif not was_above and is_above:
                events.append(f"{label} 돌파")

        for evt in events:
            if '이탈' in evt:
                warnings.append(f"📉 {name} {evt}")
            else:
                warnings.append(f"📈 {name} {evt}")

    return warnings


# ============================================================
# 텔레그램 전송 유틸리티
# ============================================================
def send_telegram_long(text, bot_token, chat_id):
    """긴 메시지 자동 분할 전송 (4000자 기준)"""
    MAX_LEN = 4000
    url = f'https://api.telegram.org/bot{bot_token}/sendMessage'

    if len(text) <= MAX_LEN:
        return [requests.post(url, data={'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'})]

    lines = text.split('\n')
    chunks = []
    current = []
    current_len = 0
    for line in lines:
        if current_len + len(line) + 1 > MAX_LEN and current:
            chunks.append('\n'.join(current))
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += len(line) + 1
    if current:
        chunks.append('\n'.join(current))

    results = []
    for chunk in chunks:
        r = requests.post(url, data={'chat_id': chat_id, 'text': chunk, 'parse_mode': 'HTML'})
        results.append(r)
        time.sleep(0.3)
    return results


# ============================================================
# v41 메시지 포맷터 — Signal / AI Risk / Watchlist
# ============================================================
def _build_top5_streak(top5_tickers):
    """Top 5 연속 유지 일수 계산.
    top5_tickers: 현재 실제 Top 5 ticker 리스트 (picks 기준).
    과거 날짜는 JSON rank <= 5 (가중순위 포지션)로 판단.
    Returns: {ticker: int(연속 일수, 최소 1)}"""
    import glob
    state_dir = Path(__file__).parent / 'state'
    files = sorted(glob.glob(str(state_dir / 'ranking_*.json')), reverse=True)
    if not files or not top5_tickers:
        return {}

    streak = {}
    for ticker in top5_tickers:
        # 오늘은 picks에 포함 = 1일째 확정
        count = 1
        # 과거 파일 (두 번째부터) 역순 탐색
        for fp in files[1:]:
            with open(fp, 'r', encoding='utf-8') as f:
                data = json.load(f)
            ranks = {r['ticker']: r.get('composite_rank', r.get('rank', 99)) for r in data.get('rankings', [])}
            if ranks.get(ticker, 99) <= 5:
                count += 1
            else:
                break
        streak[ticker] = count
    return streak


def create_signal_message(picks, pipeline, exited, biz_day, ai_narratives,
                          market_max_picks, stock_weight, rankings_t0,
                          rankings_t1, rankings_t2, cold_start,
                          final_action, pick_level):
    """Message 1: Signal — 결론 (뭘 살까)

    종목당 3줄: 이름·업종·가격 / 순위 / AI 내러티브
    """
    wd = WEEKDAY_KR[biz_day.weekday()]
    date_str = f"{biz_day.year}.{biz_day.month}.{biz_day.day}({wd})"

    lines = [
        f'📡 AI 종목 브리핑 KR · {date_str}',
        '국내 전 종목을 매일 자동 분석한',
        '종합 점수 상위 종목입니다.',
    ]

    # ── stop 모드 (시장 경고) ──
    if market_max_picks == 0 and pick_level and pick_level.get('warning'):
        lines.append('')
        lines.append('━━━━━━━━━━━━━━━')
        lines.append('🚫 시장 경고 — 스크리닝 일시 중단')
        lines.append('━━━━━━━━━━━━━━━')
        lines.append(pick_level['warning'])
        lines.append('')
        lines.append('━━━━━━━━━━━━━━━')
        lines.append('💡 분할매수 권장')
        lines.append('한 번에 전량 매수보다 2~3회 나눠서')
        lines.append('조정 시 진입이 유리합니다.')
        lines.append('')
        lines.append('⚖️ 멀티팩터 순위는 종목 선별 기준이며,')
        lines.append('포트폴리오 비중은 투자자의 판단입니다.')
        lines.append('투자 손실에 대한 책임은 투자자 본인에게 있습니다.')
        return '\n'.join(lines)

    # ── 결론 섹션 ──
    if not picks:
        lines.append('')
        lines.append('━━━━━━━━━━━━━━━')
        lines.append('3일 검증 종목 중 기준점수 이상이 없습니다.')
        lines.append('')
        lines.append('━━━━━━━━━━━━━━━')
        lines.append('💡 분할매수 권장')
        lines.append('한 번에 전량 매수보다 2~3회 나눠서')
        lines.append('조정 시 진입이 유리합니다.')
        lines.append('')
        lines.append('⚖️ 멀티팩터 순위는 종목 선별 기준이며,')
        lines.append('포트폴리오 비중은 투자자의 판단입니다.')
        lines.append('투자 손실에 대한 책임은 투자자 본인에게 있습니다.')
        return '\n'.join(lines)

    n = len(picks)
    lines.append('')
    lines.append('━━━━━━━━━━━━━━━')
    lines.append('🛒 <b>매수 후보 종목</b>')
    lines.append('━━━━━━━━━━━━━━━')
    for i, pick in enumerate(picks):
        sector = pick.get('sector', '기타')
        lines.append(f'<b>{i+1}. {pick["name"]}({pick["ticker"]}) · {sector}</b>')

    # ── Top 5 상관관계 경고 (corr > 0.7 → 동일 섹터 선택 가이드) ──
    meta = rankings_t0.get('metadata') or {}
    corr_pairs = meta.get('correlation_60d', {})
    if corr_pairs and len(picks) >= 2:
        corr_members = set()
        for i in range(len(picks)):
            for j in range(i + 1, len(picks)):
                key = '_'.join(sorted([picks[i]['ticker'], picks[j]['ticker']]))
                c = corr_pairs.get(key)
                if c is not None and c > 0.7:
                    corr_members.add(picks[i]['ticker'])
                    corr_members.add(picks[j]['ticker'])
        if corr_members:
            names = [p['name'] for p in picks if p['ticker'] in corr_members]
            n_corr = len(names)
            lines.append(f'⚠️ {"·".join(names)}')
            lines.append('주가 상관관계 높음 — 이 중 1~2개 선택 권장')

    # ── 선정 과정 (퍼널) ──
    universe_count = meta.get('total_universe', 0)
    prefilter_count = meta.get('prefilter_passed', 0)
    scored_count = meta.get('scored_count', 0)
    v_count = sum(1 for s in pipeline if s['status'] == '✅')
    lines.append('')
    lines.append('📋 선정 과정')
    if universe_count > 0:
        lines.append(f'시총 1000억 이상 · 거래대금 충족 {universe_count:,}종목')
    else:
        lines.append('국내 전 종목')
    lines.append('→ 가치·성장·모멘텀 종합 채점 → 상위 30종목')
    lines.append(f'→ 3일 연속 검증 → 기준점수 이상 {n}종목')

    # ── 종목별 근거 ──
    lines.append('')
    lines.append('━━━━━━━━━━━━━━━')
    lines.append('📌 <b>종목 선정 근거</b>')
    lines.append('━━━━━━━━━━━━━━━')

    t1_rank_map = {r['ticker']: r.get('composite_rank', r['rank']) for r in rankings_t1.get('rankings', [])} if rankings_t1 else {}
    t2_rank_map = {r['ticker']: r.get('composite_rank', r['rank']) for r in rankings_t2.get('rankings', [])} if rankings_t2 else {}

    for i, pick in enumerate(picks):
        ticker = pick['ticker']
        name = pick['name']
        sector = pick.get('sector', '기타')
        price = (pick.get('_tech') or {}).get('price', 0)

        # L0: 이름·업종·가격 (볼드)
        price_str = f'₩{price:,.0f}' if price else ''
        lines.append(f'<b>{i+1}. {name}({ticker}) {sector} · {price_str}</b>')

        # L1: 순위 궤적 + 점수
        r0 = pick.get('rank_t0', pick.get('composite_rank', pick.get('rank', '?')))
        r1 = t1_rank_map.get(ticker, '-')
        r2 = t2_rank_map.get(ticker, '-')
        score_100 = weighted_score_100(ticker, rankings_t0, rankings_t1, rankings_t2)
        lines.append(f'순위 {r2}→{r1}→{r0}위 · {score_100:.1f}점')

        # L2: AI 내러티브 (fallback: _get_buy_rationale)
        narrative = ''
        if ai_narratives and ticker in ai_narratives:
            narrative = ai_narratives[ticker]
        if not narrative:
            narrative = _get_buy_rationale(pick)
        lines.append(f'💬 {narrative}')

        if i < n - 1:
            lines.append('─ ─ ─ ─ ─ ─ ─ ─')

    # ── 이탈 알림 (사유별 묶기) ──
    if exited:
        from collections import defaultdict
        reason_groups = defaultdict(list)
        for e in exited:
            reason = e.get('exit_reason', '순위밀림') or '순위밀림'
            reason_groups[reason].append(e['name'])
        lines.append('')
        parts = []
        for reason, names in reason_groups.items():
            names_str = '·'.join(names[:4])
            if len(names) > 4:
                names_str += f' 외 {len(names)-4}'
            parts.append(f'{names_str}({reason})')
        lines.append(f'📉 순위 이탈: {" ".join(parts)}')

    # ── 범례 + 면책 (Signal) ──
    lines.append('')
    lines.append('━━━━━━━━━━━━━━━')
    lines.append('순위: 3일 가중순위 (2일전→1일전→오늘)')
    lines.append('기준점수 이상 종목만 매수 후보에 선정')
    lines.append('Watchlist 매도 검토선 아래 종목은 매도 검토')
    lines.append('')
    lines.append('종목 선별 기준이며,')
    lines.append('포트폴리오 비중은 투자자의 판단입니다.')
    lines.append('투자 손실에 대한 책임은 투자자 본인에게 있습니다.')

    return '\n'.join(lines)


def create_ai_risk_message(credit, kospi_data, kosdaq_data, market_warnings,
                           ai_msg, biz_day, picks, final_action):
    """Message 2: AI Risk — 맥락 (시장 환경 + 리스크)

    시장 데이터(코스피/코스닥/HY/BBB-/VIX) + AI 해석 + 매수 주의
    """
    kospi_close, kospi_chg, kospi_color = kospi_data
    kosdaq_close, kosdaq_chg, kosdaq_color = kosdaq_data

    lines = [
        '━━━━━━━━━━━━━━━━━━━',
        '  🤖 AI 리스크 필터',
        '━━━━━━━━━━━━━━━━━━━',
        '상위 종목의 리스크 요소를 AI가 분석했어요.',
        '',
        '📊 시장 지수',
        f'{kospi_color} 코스피 {kospi_close:,.0f}({kospi_chg:+.2f}%)',
        f'{kosdaq_color} 코스닥 {kosdaq_close:,.0f}({kosdaq_chg:+.2f}%)',
        '',
        '📉 <b>신용·변동성</b>',
    ]

    # 신용시장 종합 판정 + 개별 근거
    credit_lines = format_credit_compact(credit)
    for cl in credit_lines:
        lines.append(cl)

    # 이평선 경고 (있을 때만)
    if market_warnings:
        lines.append('')
        for w in market_warnings:
            lines.append(w)

    # AI 해석 (통째 삽입)
    if ai_msg:
        lines.append('')
        lines.append(ai_msg)

    return '\n'.join(lines)


def create_watchlist_message(pipeline, exited, rankings_t0, rankings_t1,
                             rankings_t2, cold_start=False, credit=None,
                             score_100_map=None):
    """Message 3: Watchlist — 데이터 (Top 30 모니터링)

    종목당 1줄: 상태+순위+이름(업종)+순위궤적
    rank 순 정렬 (✅/⏳/🆕 인라인 마커)
    """
    WATCHLIST_N = 20
    lines = [
        '📋 <b>Top 20 종목 현황</b>',
        '상위 20종목과 순위 변동 현황입니다.',
        '✅ 3일 검증 ⏳ 2일 관찰 🆕 신규 진입',
    ]

    if not pipeline:
        lines.append('━━━━━━━━━━━━━━━')
        lines.append('데이터 없음')
        return '\n'.join(lines)

    # T-1, T-2 composite_rank 맵 (각 날의 순수 점수 순위)
    t1_full = {r['ticker']: r for r in rankings_t1.get('rankings', [])} if rankings_t1 else {}
    t2_full = {r['ticker']: r for r in rankings_t2.get('rankings', [])} if rankings_t2 else {}

    for s in pipeline:
        t1_item = t1_full.get(s['ticker'])
        t2_item = t2_full.get(s['ticker'])
        s['_r1'] = t1_item.get('composite_rank', t1_item['rank']) if t1_item else '-'
        s['_r2'] = t2_item.get('composite_rank', t2_item['rank']) if t2_item else '-'

    # 점수 기준 정렬 (격차 반영, 역전 방지)
    if score_100_map:
        sorted_pipeline = sorted(pipeline, key=lambda x: score_100_map.get(x['ticker'], 0), reverse=True)
    else:
        sorted_pipeline = sorted(pipeline, key=lambda x: x.get('weighted_rank', x['rank']))

    # 상위 WATCHLIST_N개만 표시
    display_pipeline = sorted_pipeline[:WATCHLIST_N]

    # 섹터 분포 (표시 대상만)
    from collections import Counter
    sec_counter = Counter(s.get('sector', '기타') for s in display_pipeline)
    sec_parts = [f'{sec} {cnt}' for sec, cnt in sec_counter.most_common(4)]
    others = sum(cnt for sec, cnt in sec_counter.most_common() if sec not in dict(sec_counter.most_common(4)))
    if others > 0:
        sec_parts.append(f'기타 {others}')
    lines.append(' | '.join(sec_parts))
    lines.append('━━━━━━━━━━━━━━━')

    _SECTOR_SHORT = {
        '전기전자': '전자', '바이오/제약': '바이오', 'IT서비스': 'IT',
        '섬유/의류': '의류', '소프트웨어': 'SW', '의료기기': '의료',
    }

    exit_line_shown = False
    for idx, s in enumerate(display_pipeline, 1):
        name = s['name']
        sector = _SECTOR_SHORT.get(s.get('sector', '기타'), s.get('sector', '기타'))
        status = s['status']
        r0 = s.get('composite_rank', s['rank'])  # T-0 순수 점수 순위
        r1 = s.get('_r1', '-')
        r2 = s.get('_r2', '-')
        score_100 = weighted_score_100(s['ticker'], rankings_t0, rankings_t1, rankings_t2)
        score_disp = f'{score_100:.1f}'

        # 퇴출선 구분선 (점수 내림차순 정렬 → 처음으로 EXIT_SCORE_100 미만인 종목 앞에 삽입)
        if not exit_line_shown and score_100 < EXIT_SCORE_100:
            lines.append('── 매도 검토선 ──')
            exit_line_shown = True

        if status == '✅':
            lines.append(f'{status} {idx}. {name}({sector}) {r2}→{r1}→{r0}위 · {score_disp}점')
        elif status == '⏳':
            lines.append(f'{status} {idx}. {name}({sector}) -→{r1}→{r0}위 · {score_disp}점')
        else:
            lines.append(f'{status} {idx}. {name}({sector}) -→-→{r0}위 · {score_disp}점')

    # ── 이탈 섹션 (사유별 묶기) ──
    if exited:
        lines.append('')
        lines.append('━━━━━━━━━━━━━━━')
        lines.append('📉 <b>순위 이탈</b>')
        from collections import defaultdict
        reason_groups = defaultdict(list)
        for e in exited:
            reason = e.get('exit_reason', '순위밀림') or '순위밀림'
            reason_groups[reason].append(e['name'])
        for reason, names in reason_groups.items():
            names_str = '·'.join(names[:4])
            if len(names) > 4:
                names_str += f' 외 {len(names)-4}'
            lines.append(f'{names_str}({reason})')

    # ── cold start ──
    if cold_start:
        lines.append('')
        lines.append('━━━━━━━━━━━━━━━')
        lines.append('📊 데이터 축적 중 — 3일 완료 시 상위 종목이 표시됩니다.')

    # ── 범례 (Watchlist — 면책은 Signal에만) ──
    lines.append('')
    lines.append('━━━━━━━━━━━━━━━')
    lines.append('순위: 3일 가중순위 (2일전→1일전→오늘)')
    lines.append('매도 검토선 위 종목은 유지해도 좋습니다.')

    return '\n'.join(lines)


# ============================================================
# 메인 함수
# ============================================================
def main():
    # ============================================================
    # TEST_MODE / --dates 인수 처리
    # ============================================================
    TEST_MODE = os.environ.get('TEST_MODE') == '1' or '--private-only' in sys.argv
    if TEST_MODE:
        print("⚠️  TEST_MODE — 개인봇으로만 전송합니다.")

    # --dates 20260310 20260309 20260306 또는 --dates=20260310,20260309,20260306
    manual_dates = None
    for i, arg in enumerate(sys.argv):
        if arg == '--dates':
            # 공백 구분: --dates 20260310 20260309 20260306
            remaining = []
            for a in sys.argv[i + 1:]:
                if a.startswith('--'):
                    break
                remaining.append(a)
            if remaining:
                # 콤마 구분도 지원: --dates 20260310,20260309,20260306
                if len(remaining) == 1 and ',' in remaining[0]:
                    manual_dates = remaining[0].split(',')
                else:
                    manual_dates = remaining
            break
        elif arg.startswith('--dates='):
            manual_dates = arg.split('=', 1)[1].split(',')
            break

    # ============================================================
    # 날짜 계산 (최근 3거래일)
    # ============================================================
    TODAY = get_korea_now().strftime('%Y%m%d')

    if manual_dates:
        trading_dates = [d.strip() for d in manual_dates if d.strip()]
        print(f"--dates 지정: {trading_dates}")
    else:
        trading_dates = get_recent_trading_dates(3)

    if not trading_dates:
        print("거래일을 찾을 수 없습니다.")
        sys.exit(1)

    BASE_DATE = trading_dates[0]  # T-0
    biz_day = datetime.strptime(BASE_DATE, '%Y%m%d')
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

    # 이평선 경고 계산
    market_warnings = _calc_market_warnings(kospi_idx, kosdaq_idx)
    print(f"\n[시장 이평선 경고]")
    if market_warnings:
        for w in market_warnings:
            print(f"  {w}")
    else:
        print("  경고 없음 — 시장 양호")

    # ============================================================
    # 시장 위험 지표 모니터링 (US HY Spread + 한국 BBB- + VIX)
    # ============================================================
    ecos_key = getattr(__import__('config'), 'ECOS_API_KEY', None)
    credit = get_credit_status(ecos_api_key=ecos_key)

    pick_level = get_market_pick_level(credit)
    market_max_picks = pick_level['max_picks']  # _synthesize_action 기반 (0이면 전종목 중단)
    stock_weight = WEIGHT_PER_STOCK
    final_action = credit.get('final_action', '')
    print(f"\n[매수 추천 설정] 행동: {final_action} · 레벨: {pick_level['label']} · 진입: {ENTRY_SCORE_100}점↑ · 퇴출: {EXIT_SCORE_100}점↓")

    # ============================================================
    # 순위 데이터 로드 (3일)
    # ============================================================
    print("\n[순위 데이터 로드]")
    ranking_data = load_recent_rankings(trading_dates)

    rankings_t0 = ranking_data.get(trading_dates[0])
    rankings_t1 = ranking_data.get(trading_dates[1]) if len(trading_dates) >= 2 else None
    rankings_t2 = ranking_data.get(trading_dates[2]) if len(trading_dates) >= 3 else None

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
    # 일일 변동 (콜드 스타트 시 생략)
    # ============================================================
    print("\n[일일 변동]")
    entered, exited = [], []
    if cold_start:
        print("  콜드 스타트 → 일일 변동 생략")
    elif rankings_t1:
        entered, exited = get_daily_changes(pipeline, rankings_t0, rankings_t1, threshold=WATCHLIST_N)
        print(f"  진입: {len(entered)}개, 이탈: {len(exited)}개")
        for e in entered:
            print(f"    ↑ {e['name']} ({e['rank']}위)")
        for e in exited:
            print(f"    ↓ {e['name']} ({e['rank']}위)")

    # ============================================================
    # 100점 환산 점수 맵 (정렬 + 표시에 사용)
    # ============================================================
    score_100_pre = {}
    for s in pipeline:
        score_100_pre[s['ticker']] = weighted_score_100(
            s['ticker'], rankings_t0, rankings_t1, rankings_t2)

    # ============================================================
    # ✅ 검증 종목에서 Top 추천 (점수 순)
    # ============================================================
    print("\n[✅ 검증 종목 매수 추천]")
    all_candidates = []
    drop_info = []
    if not cold_start:
        verified_picks = [s for s in pipeline if s['status'] == '✅']
        verified_picks.sort(key=lambda x: score_100_pre.get(x['ticker'], 0), reverse=True)
        print(f"  ✅ 검증 종목: {len(verified_picks)}개")

        t1_rank_map = {r['ticker']: r.get('composite_rank', r['rank']) for r in rankings_t1.get('rankings', [])} if rankings_t1 else {}
        t2_rank_map = {r['ticker']: r.get('composite_rank', r['rank']) for r in rankings_t2.get('rankings', [])} if rankings_t2 else {}

        for candidate in verified_picks:
            tech = get_stock_technical(candidate['ticker'], BASE_DATE)
            candidate['_tech'] = tech
            candidate['rank_t0'] = candidate.get('composite_rank', candidate['rank'])
            candidate['rank_t1'] = t1_rank_map.get(candidate['ticker'], candidate.get('composite_rank', candidate['rank']))
            candidate['rank_t2'] = t2_rank_map.get(candidate['ticker'], candidate.get('composite_rank', candidate['rank']))
            daily_chg = (tech or {}).get('daily_chg', 0)

            if daily_chg <= -5:
                drop_info.append((candidate, daily_chg))

            all_candidates.append(candidate)
            if tech:
                print(f"    {candidate['name']}: rank {candidate['rank']}, RSI {tech['rsi']:.0f}, 52주 {tech['w52_pct']:.0f}%")
            else:
                print(f"    {candidate['name']}: rank {candidate['rank']} (기술지표 실패)")
    else:
        print("  콜드 스타트 → 추천 없음 (관망)")

    print(f"  추천 후보: {len(all_candidates)}개 종목")

    # ============================================================
    # AI 리스크 필터 생성 (Gemini) — 전체 후보 대상
    # ============================================================
    market_ctx = None
    hy_data = credit.get('hy')
    if hy_data:
        market_ctx = {
            'action': credit.get('final_action', ''),
        }

    ai_msg = None
    ai_msg_raw = None  # AI 원본 (create_ai_risk_message에 전달)
    risk_flagged_tickers = set()
    if all_candidates:
        try:
            from gemini_analysis import run_ai_analysis, compute_risk_flags
            # 시장 평균 등락률 (KOSPI/KOSDAQ 평균) — 초과 수익률 계산용
            stock_list = []
            for pick in all_candidates:
                tech = pick.get('_tech', {}) or {}
                tech_missing = not pick.get('_tech')
                stock_data = {
                    'ticker': pick['ticker'],
                    'name': pick['name'],
                    'rank': pick['rank'],
                    'per': pick.get('per'),
                    'pbr': pick.get('pbr'),
                    'roe': pick.get('roe'),
                    'fwd_per': pick.get('fwd_per'),
                    'sector': pick.get('sector', '기타'),
                    'rsi': tech.get('rsi', 50),
                    'w52_pct': tech.get('w52_pct', 0),
                    'daily_chg': tech.get('daily_chg', 0),
                    'price': tech.get('price', 0),
                    'tech_missing': tech_missing,
                }
                stock_list.append(stock_data)
                if compute_risk_flags(stock_data):
                    risk_flagged_tickers.add(pick['ticker'])
            print(f"\n  AI 리스크 대상: {len(stock_list)}개 (위험 플래그: {len(risk_flagged_tickers)}개)")
            ai_msg_raw = run_ai_analysis(None, stock_list, base_date=BASE_DATE, market_context=market_ctx)
            if ai_msg_raw:
                print(f"\n=== AI 리스크 필터 ({len(ai_msg_raw)}자) ===")
                print(ai_msg_raw[:500] + '...' if len(ai_msg_raw) > 500 else ai_msg_raw)
            else:
                print("\nAI 리스크 필터 스킵 (결과 없음)")
        except Exception as e:
            print(f"\nAI 리스크 필터 실패 (계속 진행): {e}")
    else:
        print("\nAI 리스크 필터 스킵 (추천 종목 없음)")

    # Score-based picks: score_100 ≥ ENTRY_SCORE_100 (v61)
    if market_max_picks == 0:
        picks = []
    else:
        picks = [c for c in all_candidates
                 if score_100_pre.get(c['ticker'], 0) >= ENTRY_SCORE_100]
    if picks:
        stock_weight = round(100 / len(picks))
    print(f"\n  최종 picks: {len(picks)}개 (진입기준: {ENTRY_SCORE_100}점↑, 퇴출기준: {EXIT_SCORE_100}점)")

    # ============================================================
    # AI 종목별 내러티브 (Signal 💬 줄용)
    # ============================================================
    ai_narratives = {}
    ai_picks_text = None
    if picks and ai_msg_raw:
        try:
            from gemini_analysis import run_final_picks_analysis, parse_narratives
            final_stock_list = []
            for pick in picks:
                tech = pick.get('_tech', {}) or {}
                final_stock_list.append({
                    'ticker': pick['ticker'],
                    'name': pick['name'],
                    'sector': pick.get('sector', '기타'),
                    'rank_t0': pick.get('rank_t0'),
                    'rank_t1': pick.get('rank_t1'),
                    'rank_t2': pick.get('rank_t2'),
                    'driver': pick.get('_driver', ''),
                    'per': pick.get('per'),
                    'fwd_per': pick.get('fwd_per'),
                    'roe': pick.get('roe'),
                    'rsi': tech.get('rsi', 50),
                    'w52_pct': tech.get('w52_pct', 0),
                })
            ai_picks_text = run_final_picks_analysis(final_stock_list, stock_weight, BASE_DATE, market_context=market_ctx)
            if ai_picks_text:
                ai_narratives = parse_narratives(ai_picks_text)
                print(f"  AI 내러티브: {len(ai_narratives)}종목 추출")
        except Exception as e:
            print(f"최종 추천 AI 설명 실패 (fallback 사용): {e}")

    # ============================================================
    # v41 메시지 구성 — Signal + AI Risk + Watchlist
    # ============================================================
    # AI Risk에서 사용할 AI 원본 텍스트: 헤더/포맷은 run_ai_analysis가 이미 생성
    # create_ai_risk_message에는 시장 데이터만 별도 전달하고 AI 텍스트는 통째 삽입

    # AI Risk용 AI 텍스트 추출 (run_ai_analysis 반환값에서 헤더 제거)
    ai_risk_ai_text = None
    if ai_msg_raw:
        # run_ai_analysis는 이미 ━━━ 🤖 AI 리스크 필터 ━━━ 헤더 포함
        # create_ai_risk_message에서 자체 헤더를 만드므로, AI 텍스트만 추출
        # AI 텍스트는 '후보 종목 중 주의할 점을' 이후부터
        raw_lines = ai_msg_raw.split('\n')
        ai_text_start = 0
        for idx, line in enumerate(raw_lines):
            if '📰' in line or '시장 동향' in line or '⚠️' in line:
                ai_text_start = idx
                break
        if ai_text_start > 0:
            ai_risk_ai_text = '\n'.join(raw_lines[ai_text_start:])
        else:
            # 헤더 4줄(━━━, 🤖, ━━━, 빈줄, 소개문, 빈줄) 건너뛰기
            for idx, line in enumerate(raw_lines):
                if idx > 3 and line.strip() and '━━━' not in line and '🤖' not in line and '후보' not in line:
                    ai_text_start = idx
                    break
            ai_risk_ai_text = '\n'.join(raw_lines[ai_text_start:]) if ai_text_start > 0 else ai_msg_raw

    msg_signal = create_signal_message(
        picks, pipeline, exited, biz_day, ai_narratives,
        market_max_picks, stock_weight, rankings_t0,
        rankings_t1, rankings_t2, cold_start,
        final_action, pick_level,
    )

    msg_ai_risk = create_ai_risk_message(
        credit,
        (kospi_close, kospi_chg, kospi_color),
        (kosdaq_close, kosdaq_chg, kosdaq_color),
        market_warnings,
        ai_risk_ai_text,
        biz_day, picks, final_action,
    )

    msg_watchlist = create_watchlist_message(
        pipeline, exited, rankings_t0, rankings_t1, rankings_t2,
        cold_start=cold_start, credit=credit,
        score_100_map=score_100_pre,
    )

    messages = [msg_signal, msg_ai_risk, msg_watchlist]

    # ============================================================
    # 웹 대시보드용 데이터 캐시 저장
    # ============================================================
    try:
        import json as _json
        web_data = {
            'date': BASE_DATE,
            'generated_at': get_korea_now().isoformat(),
            'market': {
                'kospi': {'close': float(kospi_close), 'change_pct': round(float(kospi_chg), 2)},
                'kosdaq': {'close': float(kosdaq_close), 'change_pct': round(float(kosdaq_chg), 2)},
                'warnings': market_warnings,
            },
            'credit': {
                'hy': credit.get('hy'),
                'kr': credit.get('kr'),
                'vix': credit.get('vix'),
                'concordance': credit.get('concordance'),
                'final_action': credit.get('final_action'),
                'formatted': format_credit_section(credit),
            },
            'pipeline': {
                'verified': [s for s in pipeline if s['status'] == '✅'],
                'pending': [s for s in pipeline if s['status'] == '⏳'],
                'new_entry': [s for s in pipeline if s['status'] == '🆕'],
            },
            'picks': [{
                'ticker': p['ticker'], 'name': p['name'], 'sector': p.get('sector', ''),
                'rank': p.get('rank'), 'rank_t0': p.get('rank_t0'),
                'rank_t1': p.get('rank_t1'), 'rank_t2': p.get('rank_t2'),
                'per': p.get('per'), 'pbr': p.get('pbr'), 'roe': p.get('roe'), 'fwd_per': p.get('fwd_per'),
                'score': p.get('score'), 'weight': stock_weight,
                'tech': {k: v for k, v in (p.get('_tech') or {}).items() if k != 'ohlcv'},
            } for p in picks],
            'drop_info': [{'name': d[0]['name'], 'ticker': d[0]['ticker'], 'daily_chg': d[1]} for d in drop_info],
            'exited': [{'ticker': e['ticker'], 'name': e['name'],
                        'rank': e['rank'], 't0_rank': e.get('t0_rank'),
                        'exit_reason': e.get('exit_reason', '')}
                       for e in exited],
            'sectors': {},
            'ai': {
                'risk_filter': ai_msg_raw,
                'picks_text': ai_picks_text,
                'flagged_tickers': list(risk_flagged_tickers),
                'narratives': ai_narratives,
            },
        }
        for s in pipeline:
            sec = s.get('sector', '기타')
            web_data['sectors'][sec] = web_data['sectors'].get(sec, 0) + 1

        web_path = STATE_DIR / f'web_data_{BASE_DATE}.json'
        with open(web_path, 'w', encoding='utf-8') as _f:
            _json.dump(web_data, _f, ensure_ascii=False, indent=2, default=str)
        print(f'\n[웹 캐시] {web_path.name} 저장 완료')
    except Exception as _e:
        print(f'\n[웹 캐시] 저장 실패 (무시): {_e}')

    # ============================================================
    # 텔레그램 전송
    # ============================================================
    PRIVATE_CHAT_ID = getattr(__import__('config'), 'TELEGRAM_PRIVATE_ID', None)
    IS_GITHUB_ACTIONS = os.environ.get('GITHUB_ACTIONS') == 'true'

    print("\n=== 메시지 미리보기 ===")
    msg_labels = ['Signal', 'AI Risk', 'Watchlist']
    for i, msg in enumerate(messages):
        label = msg_labels[i] if i < len(msg_labels) else f'#{i+1}'
        print(f"\n--- {label} ({len(msg)}자) ---")
        print(msg[:500])
    msg_sizes = ', '.join(f'{len(m)}자' for m in messages)
    print(f"\n메시지 수: {len(messages)}개 ({msg_sizes})")

    # TEST_MODE: 개인봇으로만 전송 (채널 절대 안 건드림)
    if TEST_MODE:
        target = PRIVATE_CHAT_ID or TELEGRAM_CHAT_ID
        print(f'\n🧪 TEST_MODE — 개인봇으로만 전송 ({target[:6]}...)')
        for i, msg in enumerate(messages):
            results = send_telegram_long(msg, TELEGRAM_BOT_TOKEN, target)
            codes = [str(r.status_code) for r in results]
            print(f'  {msg_labels[i]}: {", ".join(codes)}')
    elif IS_GITHUB_ACTIONS:
        if cold_start:
            target = PRIVATE_CHAT_ID or TELEGRAM_CHAT_ID
            print(f'\n콜드 스타트 — 채널 전송 스킵, 개인봇으로 전송 ({target[:6]}...)')
            for i, msg in enumerate(messages):
                results = send_telegram_long(msg, TELEGRAM_BOT_TOKEN, target)
                codes = [str(r.status_code) for r in results]
                print(f'  {msg_labels[i]}: {", ".join(codes)}')
        else:
            print(f'\n채널 전송...')
            for i, msg in enumerate(messages):
                results = send_telegram_long(msg, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
                codes = [str(r.status_code) for r in results]
                print(f'  {msg_labels[i]}: {", ".join(codes)}')

            if PRIVATE_CHAT_ID and PRIVATE_CHAT_ID != TELEGRAM_CHAT_ID:
                print(f'개인봇 전송...')
                for i, msg in enumerate(messages):
                    results = send_telegram_long(msg, TELEGRAM_BOT_TOKEN, PRIVATE_CHAT_ID)
                    codes = [str(r.status_code) for r in results]
                    print(f'  {msg_labels[i]}: {", ".join(codes)}')
    else:
        if cold_start:
            target = PRIVATE_CHAT_ID or TELEGRAM_CHAT_ID
            print(f'\n콜드 스타트 — 채널 전송 스킵, 개인봇으로 전송')
            for i, msg in enumerate(messages):
                results = send_telegram_long(msg, TELEGRAM_BOT_TOKEN, target)
                codes = [str(r.status_code) for r in results]
                print(f'  {msg_labels[i]}: {", ".join(codes)}')
        else:
            print(f'\n채널 전송 ({TELEGRAM_CHAT_ID})...')
            for i, msg in enumerate(messages):
                results = send_telegram_long(msg, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
                codes = [str(r.status_code) for r in results]
                print(f'  {msg_labels[i]}: {", ".join(codes)}')

            if PRIVATE_CHAT_ID and PRIVATE_CHAT_ID != TELEGRAM_CHAT_ID:
                print(f'개인봇 전송...')
                for i, msg in enumerate(messages):
                    results = send_telegram_long(msg, TELEGRAM_BOT_TOKEN, PRIVATE_CHAT_ID)
                    codes = [str(r.status_code) for r in results]
                    print(f'  {msg_labels[i]}: {", ".join(codes)}')

    # ============================================================
    # 정리
    # ============================================================
    cleanup_old_rankings(keep_days=30)

    print(f'\n매수 추천: {len(picks)}개 ({"관망" if not picks else f"종목 {len(picks)*stock_weight}%"})')
    print(f'파이프라인: ✅ {v_count} · ⏳ {d_count} · 🆕 {n_count}')
    print(f'일일 변동: 진입 {len(entered)}개 · 이탈 {len(exited)}개')
    print('\n완료!')


if __name__ == '__main__':
    main()
