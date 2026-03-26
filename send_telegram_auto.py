"""
한국주식 퀀트 텔레그램 v41 — Signal + AI Risk + Watchlist

메시지 구조 (v41):
  📊 Signal — 결론 (뭘 살까)
  🤖 AI Risk — 맥락 (시장 환경 + 리스크)
  📋 Watchlist — 데이터 (Top 20 모니터링)

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
    weighted_score_100, ENTRY_SCORE_100, EXIT_SCORE_100, ENTRY_RANK, EXIT_RANK, MAX_SLOTS,
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
WATCHLIST_N = 20       # Watchlist 표시 종목 수

WEEKDAY_KR = ['월', '화', '수', '목', '금', '토', '일']


# ============================================================
# 시스템 수익률 추적
# ============================================================
def calc_system_returns():
    """프로덕션 ranking 히스토리로 시스템 누적 수익률 계산.

    Returns:
        dict: {system_pct, kospi_pct, start_date, days, holdings} or None
    """
    import glob as _glob
    files = sorted(_glob.glob(str(STATE_DIR / 'ranking_*.json')))
    if len(files) < 3:
        return None

    # 날짜순 ranking 로드 (당일 제외 — 전일 기준)
    today_str = get_korea_now().strftime('%Y%m%d')
    all_data = {}
    for fp in files:
        d = os.path.basename(fp).replace('ranking_', '').replace('.json', '')
        if d >= today_str:
            continue  # 당일 이후 제외
        with open(fp, 'r', encoding='utf-8') as fh:
            all_data[d] = json.load(fh)
    dates = sorted(all_data.keys())

    # 가격: OHLCV 기반 (모든 파일 합쳐서 최대 커버리지)
    import glob as _glob2
    _ohlcv_files = sorted(_glob2.glob(str(Path(__file__).parent / 'data_cache' / 'all_ohlcv_*.parquet')))
    if _ohlcv_files:
        _ohlcv_parts = [pd.read_parquet(f).replace(0, np.nan) for f in _ohlcv_files]
        _ohlcv = pd.concat(_ohlcv_parts).groupby(level=0).first()  # 날짜 중복 시 첫 번째 유지
    else:
        _ohlcv = pd.DataFrame()

    def _get_price(ticker, date_str):
        ts = pd.Timestamp(date_str)
        if not _ohlcv.empty and ts in _ohlcv.index and ticker in _ohlcv.columns:
            v = _ohlcv.loc[ts, ticker]
            if pd.notna(v) and v > 0:
                return v
        return 0

    # 포트폴리오 시뮬레이션 — 일간 수익률 기반 + 손절
    portfolio = {}  # ticker → entry_price
    equity = 1.0
    start_date = None

    for i in range(len(dates)):
        d0 = dates[i]
        d1 = dates[i - 1] if i >= 1 else None
        d2 = dates[i - 2] if i >= 2 else None

        # 일간 수익률: 어제 보유 → 오늘 가격 변화 (OHLCV 기반)
        if i >= 1 and portfolio:
            daily_rets = []
            for tk in portfolio:
                pp = _get_price(tk, dates[i - 1])
                cp = _get_price(tk, d0)
                if pp > 0 and cp > 0:
                    daily_rets.append(cp / pp - 1)
            if daily_rets:
                avg_ret = sum(daily_rets) / len(daily_rets)
                equity *= (1 + avg_ret)

        if i < 2:
            continue  # 3일 데이터 필요

        # 손절 체크: 진입가 대비 -10% (OHLCV 기반)
        for tk in list(portfolio.keys()):
            cp = _get_price(tk, d0)
            ep = portfolio[tk]
            if cp > 0 and ep > 0 and (cp / ep - 1) <= -0.10:
                del portfolio[tk]

        # pipeline 계산 (3일 교집합)
        r0 = all_data[d0].get('rankings', [])
        r1 = all_data[d1].get('rankings', [])
        r2 = all_data[d2].get('rankings', [])

        top20_t0 = {r['ticker']: r for r in r0 if r.get('composite_rank', r['rank']) <= 20}
        top20_t1 = {r['ticker']: r for r in r1 if r.get('composite_rank', r['rank']) <= 20}
        top20_t2 = {r['ticker']: r for r in r2 if r.get('composite_rank', r['rank']) <= 20}

        common = set(top20_t0) & set(top20_t1) & set(top20_t2)

        # 전체 ranking에서 가중순위 계산 (퇴출용)
        all_t0 = {r['ticker']: r for r in r0}
        all_t1 = {r['ticker']: r for r in r1}
        all_t2 = {r['ticker']: r for r in r2}

        def _wr(tk):
            if tk not in all_t0:
                return 999
            cr0 = all_t0[tk].get('composite_rank', all_t0[tk].get('rank', 999))
            cr1 = all_t1[tk].get('composite_rank', all_t1[tk].get('rank', 999)) if tk in all_t1 else 999
            cr2 = all_t2[tk].get('composite_rank', all_t2[tk].get('rank', 999)) if tk in all_t2 else 999
            return cr0 * 0.5 + cr1 * 0.3 + cr2 * 0.2

        # 이탈: 가중순위 > EXIT_RANK (전체 ranking 기준)
        for tk in list(portfolio.keys()):
            if _wr(tk) > EXIT_RANK:
                del portfolio[tk]

        # 진입용: 3일 교집합 + 가중순위 계산
        verified = []
        for tk in common:
            cr0 = top20_t0[tk].get('composite_rank', top20_t0[tk]['rank'])
            cr1 = top20_t1[tk].get('composite_rank', top20_t1[tk]['rank'])
            cr2 = top20_t2[tk].get('composite_rank', top20_t2[tk]['rank'])
            wr = cr0 * 0.5 + cr1 * 0.3 + cr2 * 0.2
            verified.append({'ticker': tk, 'weighted_rank': wr,
                             'price': top20_t0[tk].get('price', 0)})
        verified.sort(key=lambda x: x['weighted_rank'])

        # 진입: weighted_rank ≤ ENTRY_RANK, ✅ verified (OHLCV 가격)
        for v in verified:
            if v['ticker'] in portfolio:
                continue
            if len(portfolio) >= MAX_SLOTS:
                break
            if v['weighted_rank'] <= ENTRY_RANK:
                entry_price = _get_price(v['ticker'], d0)
                if entry_price > 0:
                    portfolio[v['ticker']] = entry_price
                    if start_date is None:
                        start_date = d0

    if start_date is None:
        return None

    system_pct = (equity - 1) * 100

    # KOSPI 수익률 (start_date ~ 최신)
    kospi_pct = 0
    try:
        kospi_start = stock.get_index_ohlcv(start_date, dates[-1], '1001')
        if not kospi_start.empty and len(kospi_start) >= 2:
            k_first = kospi_start.iloc[0, 3]  # 종가
            k_last = kospi_start.iloc[-1, 3]
            if k_first > 0:
                kospi_pct = (k_last / k_first - 1) * 100
    except:
        pass

    return {
        'system_pct': round(system_pct, 1),
        'kospi_pct': round(kospi_pct, 1),
        'start_date': start_date,
        'days': len(dates) - 2,
        'holdings': len(portfolio),
    }


# ============================================================
# 유틸리티 함수
# ============================================================
def get_korea_now():
    return datetime.now(KST)


def get_recent_trading_dates(n=3):
    """최근 N개 거래일 찾기 — 캐시 우선, KRX API 폴백"""
    today = get_korea_now()
    today_str = today.strftime('%Y%m%d')
    # 1차: market_cap 캐시 파일에서 거래일 목록 구축 (당일 제외 — 전일 기준)
    cache_dir = Path(__file__).parent / 'data_cache'
    mc_dates = set()
    for f in cache_dir.glob('market_cap_ALL_*.parquet'):
        d = f.stem.split('_')[-1]
        if len(d) == 8 and d.isdigit() and d < today_str:
            mc_dates.add(d)
    if mc_dates:
        sorted_dates = sorted(mc_dates, reverse=True)[:n]
        if len(sorted_dates) >= n:
            return sorted_dates
    # 2차: KRX API 폴백
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
    """KOSPI/KOSDAQ 이평선 돌파/이탈 이벤트만 반환 (매일 표시 X)

    Returns:
        dict: {'코스피': ['5일선 돌파', ...], '코스닥': ['5일선 이탈', ...]}
    """
    warnings = {'코스피': [], '코스닥': []}

    for name, df in [('코스피', kospi_df), ('코스닥', kosdaq_df)]:
        if df is None or len(df) < 6:
            continue

        close = df.iloc[:, 3]  # 종가 컬럼
        today = close.iloc[-1]
        yesterday = close.iloc[-2]

        for period, label in [(5, '5일선'), (20, '20일선'), (60, '60일선')]:
            if len(close) < period + 1:
                continue
            ma = close.rolling(period).mean()
            ma_today = ma.iloc[-1]
            ma_yesterday = ma.iloc[-2]

            was_above = yesterday >= ma_yesterday
            is_above = today >= ma_today

            if was_above and not is_above:
                warnings[name].append(f"{label} 이탈")
            elif not was_above and is_above:
                warnings[name].append(f"{label} 돌파")

    return warnings


# ============================================================
# 텔레그램 전송 유틸리티
# ============================================================
def send_telegram_long(text, bot_token, chat_id):
    """긴 메시지 자동 분할 전송 (4000자 기준)"""
    MAX_LEN = 4000
    url = f'https://api.telegram.org/bot{bot_token}/sendMessage'

    if len(text) <= MAX_LEN:
        return [requests.post(url, data={'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}, timeout=30)]

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
        r = requests.post(url, data={'chat_id': chat_id, 'text': chunk, 'parse_mode': 'HTML'}, timeout=30)
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
                          final_action, pick_level, system_returns=None):
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
        lines.append('오늘은 기준점수를 충족하는 종목이 없습니다.')
        lines.append('시장이 안정되면 다시 안내드리겠습니다.')
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

    # ── 시스템 수익률 (US 프로젝트 포맷) ──
    if system_returns and system_returns.get('days', 0) >= 5:
        sr = system_returns
        lines.append('')
        lines.append(f'📈 <b>시스템 누적 수익률 {sr["system_pct"]:+.1f}% ({sr["days"]}거래일)</b>')
        lines.append(f'    같은 기간 KOSPI는 {sr["kospi_pct"]:+.1f}%')

    n = len(picks)
    lines.append('')
    lines.append('━━━━━━━━━━━━━━━')
    lines.append('🛒 <b>매수 후보 종목</b>')
    lines.append('━━━━━━━━━━━━━━━')
    for i, pick in enumerate(picks):
        sector = pick.get('sector', '기타')
        lines.append(f'<b>{i+1}. {pick["name"]}({pick["ticker"]}) · {sector}</b>')

    # ── Top 5 상관관계 경고 (corr > 0.65 → 동일 섹터 선택 가이드) ──
    meta = rankings_t0.get('metadata') or {}
    corr_pairs = meta.get('correlation_60d', {})
    if corr_pairs and len(picks) >= 2:
        # 상관관계 그래프 → 연결 성분(그룹) 자동 묶기
        from collections import defaultdict
        adj = defaultdict(set)
        for i in range(len(picks)):
            for j in range(i + 1, len(picks)):
                key = '_'.join(sorted([picks[i]['ticker'], picks[j]['ticker']]))
                c = corr_pairs.get(key)
                if c is not None and c > 0.65:
                    adj[picks[i]['ticker']].add(picks[j]['ticker'])
                    adj[picks[j]['ticker']].add(picks[i]['ticker'])
        # BFS로 연결 성분 추출
        visited = set()
        groups = []
        for pick in picks:
            tk = pick['ticker']
            if tk not in adj or tk in visited:
                continue
            group = []
            queue = [tk]
            while queue:
                cur = queue.pop(0)
                if cur in visited:
                    continue
                visited.add(cur)
                group.append(cur)
                for nb in adj[cur]:
                    if nb not in visited:
                        queue.append(nb)
            if len(group) >= 2:
                groups.append(group)
        # 그룹별 경고 (1줄씩)
        tk_name = {p['ticker']: p['name'] for p in picks}
        for group in groups:
            names = [tk_name[tk] for tk in group if tk in tk_name]
            if len(names) == 2:
                lines.append(f'⚠️ {"·".join(names)} 유사 — 택1 권장')
            else:
                lines.append(f'⚠️ {"·".join(names)} 유사 — 택1~2 권장')

    # ── 선정 과정 (퍼널) ──
    universe_count = meta.get('total_universe', 0)
    prefilter_count = meta.get('prefilter_passed', 0)
    scored_count = meta.get('scored_count', 0)
    v_count = sum(1 for s in pipeline if s['status'] == '✅')
    lines.append('')
    lines.append('📋 <b>선정 과정</b>')
    if universe_count > 0:
        lines.append(f'시총 1000억 이상 · 거래대금 충족 {universe_count:,}종목')
    else:
        lines.append('국내 전 종목')
    lines.append('→ 밸류·퀄리티·성장·모멘텀 종합 채점 → 상위 20종목')
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
        parts = []
        for reason, names in reason_groups.items():
            names_str = '·'.join(names[:4])
            if len(names) > 4:
                names_str += f' 외 {len(names)-4}'
            parts.append(f'{names_str}({reason})')
        lines.append('')
        lines.append('📉 순위 이탈: ' + parts[0])
        for p in parts[1:]:
            lines.append(p)

    # ── 범례 + 면책 (Signal) ──
    lines.append('')
    lines.append('━━━━━━━━━━━━━━━')
    lines.append('순위: 3일 가중순위 (2일전→1일전→오늘)')
    lines.append('종목 선별 기준이며, 비중은 투자자의 판단입니다.')
    lines.append('투자 손실의 책임은 본인에게 있습니다.')

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
        '상위 종목의 리스크 요소를 AI가 분석했습니다.',
        '',
        '📊 <b>시장 지수</b>',
    ]

    # 코스피/코스닥 + 이평선 이벤트 인라인
    def _fmt_warn(events):
        """['5일선 돌파', '20일선 돌파'] → '5일선, 20일선 돌파'"""
        if not events:
            return ''
        from collections import defaultdict
        by_action = defaultdict(list)
        for e in events:
            parts = e.split()  # '5일선', '돌파'
            by_action[parts[1]].append(parts[0])
        groups = [', '.join(labels) + ' ' + action for action, labels in by_action.items()]
        return ' · ' + ', '.join(groups)

    kospi_warn = market_warnings.get('코스피', []) if isinstance(market_warnings, dict) else []
    kosdaq_warn = market_warnings.get('코스닥', []) if isinstance(market_warnings, dict) else []
    kospi_suffix = _fmt_warn(kospi_warn)
    kosdaq_suffix = _fmt_warn(kosdaq_warn)
    lines.append(f'{kospi_color} 코스피 {kospi_close:,.0f}({kospi_chg:+.2f}%){kospi_suffix}')
    lines.append(f'{kosdaq_color} 코스닥 {kosdaq_close:,.0f}({kosdaq_chg:+.2f}%){kosdaq_suffix}')

    lines.append('')
    lines.append('🏦 <b>신용·변동성</b>')

    # 신용시장 종합 판정 + 개별 근거
    credit_lines = format_credit_compact(credit)
    for cl in credit_lines:
        lines.append(cl)

    # AI 해석 (통째 삽입 + 헤더 볼드 후처리)
    if ai_msg:
        processed = ai_msg
        # 📰/⚠️ 헤더 볼드 처리
        processed = processed.replace('📰 시장 동향', '📰 <b>시장 동향</b>')
        processed = processed.replace('⚠️ 매수 주의 종목', '⚠️ <b>매수 주의 종목</b>')
        # 헤더 직후 불필요한 빈줄 제거
        processed = processed.replace('📰 <b>시장 동향</b>\n\n', '📰 <b>시장 동향</b>\n')
        processed = processed.replace('⚠️ <b>매수 주의 종목</b>\n\n', '⚠️ <b>매수 주의 종목</b>\n')
        lines.append('')
        lines.append(processed)

    return '\n'.join(lines)


def create_watchlist_message(pipeline, exited, rankings_t0, rankings_t1,
                             rankings_t2, cold_start=False, credit=None,
                             score_100_map=None, system_returns=None):
    """Message 3: Watchlist — 데이터 (Top 20 모니터링)

    종목당 1줄: 상태+순위+이름(업종)+순위궤적
    rank 순 정렬 (✅/⏳/🆕 인라인 마커)
    """
    lines = [
        '📋 <b>Top 20 종목 현황</b>',
        '상위 20종목과 순위 변동 현황입니다.',
        '✅ 3일 검증 ⏳ 2일 관찰 🆕 신규 진입 | 손절 -10%',
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

    # v70: weighted_rank 순 정렬 (rank 기반 진입/이탈과 일관)
    sorted_pipeline = sorted(pipeline, key=lambda x: (x.get('weighted_rank', x['rank']), -(score_100_map or {}).get(x['ticker'], 0)))

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

        # 매도 검토선 (가중순위 값 기준 — WR > EXIT_RANK)
        w_rank = s.get('weighted_rank', 999)
        if not exit_line_shown and w_rank > EXIT_RANK:
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

    # ── 매매 조건 + 범례 ──
    lines.append('')
    lines.append('━━━━━━━━━━━━━━━')
    lines.append(f'매수: 3일 가중순위 ≤ {ENTRY_RANK}.0')
    lines.append(f'매도: 3일 가중순위 > {EXIT_RANK}.0 또는 -10% 손절')
    lines.append(f'최대 {MAX_SLOTS}종목 보유')

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
    try:
        kospi_idx = stock.get_index_ohlcv(idx_start, BASE_DATE, '1001')
        kosdaq_idx = stock.get_index_ohlcv(idx_start, BASE_DATE, '2001')
    except Exception as e:
        print(f"  지수 OHLCV 수집 실패 (KRX API 차단): {e}")
        kospi_idx = pd.DataFrame()
        kosdaq_idx = pd.DataFrame()

    if not kospi_idx.empty and len(kospi_idx) >= 2:
        kospi_close = kospi_idx.iloc[-1, 3]
        kospi_prev = kospi_idx.iloc[-2, 3]
    else:
        kospi_close = 0
        kospi_prev = 0
    kospi_chg = ((kospi_close / kospi_prev) - 1) * 100 if kospi_prev else 0

    if not kosdaq_idx.empty and len(kosdaq_idx) >= 2:
        kosdaq_close = kosdaq_idx.iloc[-1, 3]
        kosdaq_prev = kosdaq_idx.iloc[-2, 3]
    else:
        kosdaq_close = 0
        kosdaq_prev = 0
    kosdaq_chg = ((kosdaq_close / kosdaq_prev) - 1) * 100 if kosdaq_prev else 0

    def _idx_color(chg):
        if chg > 1: return "🟢"
        elif chg < -1: return "🔴"
        else: return "🟡"

    kospi_color = _idx_color(kospi_chg)
    kosdaq_color = _idx_color(kosdaq_chg)

    # 이평선 경고 계산
    market_warnings = _calc_market_warnings(kospi_idx, kosdaq_idx)
    print(f"\n[시장 이평선 경고]")
    has_any = any(market_warnings.get(k) for k in market_warnings)
    if has_any:
        for name, events in market_warnings.items():
            for evt in events:
                icon = '📉' if '이탈' in evt else '📈'
                print(f"  {icon} {name} {evt}")
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

    # ── 시스템 수익률 계산 ──
    print("\n[시스템 수익률]")
    system_returns = None
    try:
        system_returns = calc_system_returns()
        if system_returns:
            print(f"  시스템: {system_returns['system_pct']:+.1f}% vs KOSPI: {system_returns['kospi_pct']:+.1f}% "
                  f"(초과: {system_returns['system_pct']-system_returns['kospi_pct']:+.1f}%p, {system_returns['start_date']}~)")
        else:
            print("  데이터 부족 (3일 미만)")
    except Exception as e:
        print(f"  계산 실패 (무시): {e}")

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
            mkt_idx = {
                'kospi_close': kospi_close, 'kospi_chg': kospi_chg,
                'kosdaq_close': kosdaq_close, 'kosdaq_chg': kosdaq_chg,
            }
            ai_msg_raw = run_ai_analysis(None, stock_list, base_date=BASE_DATE, market_context=market_ctx, market_index=mkt_idx)
            if ai_msg_raw:
                print(f"\n=== AI 리스크 필터 ({len(ai_msg_raw)}자) ===")
                print(ai_msg_raw[:500] + '...' if len(ai_msg_raw) > 500 else ai_msg_raw)
            else:
                print("\nAI 리스크 필터 스킵 (결과 없음)")
        except Exception as e:
            print(f"\nAI 리스크 필터 실패 (계속 진행): {e}")
    else:
        print("\nAI 리스크 필터 스킵 (추천 종목 없음)")

    # v70: Rank-based picks: weighted_rank ≤ ENTRY_RANK + ✅ + 슬롯 제한
    from ranking_manager import ENTRY_RANK, EXIT_RANK, MAX_SLOTS
    if market_max_picks == 0:
        picks = []
    else:
        picks = [c for c in all_candidates
                 if c.get('weighted_rank', 999) <= ENTRY_RANK]
        picks = picks[:MAX_SLOTS]  # 슬롯 제한
    if picks:
        stock_weight = round(100 / len(picks))
    print(f"\n  최종 picks: {len(picks)}개 (진입: rank≤{ENTRY_RANK} · 이탈: rank>{EXIT_RANK} · 슬롯: {MAX_SLOTS} · 손절: -10%)")

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
        system_returns=system_returns,
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
        system_returns=system_returns,
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
    # cleanup_old_rankings(keep_days=30)  # v70: 과거 랭킹 보존 (로그용)

    print(f'\n매수 추천: {len(picks)}개 ({"관망" if not picks else f"종목 {len(picks)*stock_weight}%"})')
    print(f'파이프라인: ✅ {v_count} · ⏳ {d_count} · 🆕 {n_count}')
    print(f'일일 변동: 진입 {len(entered)}개 · 이탈 {len(exited)}개')
    print('\n완료!')


if __name__ == '__main__':
    main()
