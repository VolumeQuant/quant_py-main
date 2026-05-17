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
    STATE_DIR as RM_STATE_DIR,
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

WEEKDAY_KR = ['월', '화', '수', '목', '금', '��', '일']


# ============================================================
# 국면(Regime) 상태 로드 + 국면별 랭킹 파일 로드
# ============================================================
def load_regime_state():
    """regime_state.json에서 현재 국면 정보 로드.

    Returns:
        dict: {mode, breadth, streak, rule, ...} or default defense
    """
    regime_path = STATE_DIR / 'regime_state.json'
    if regime_path.exists():
        try:
            with open(regime_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {'mode': 'defense', 'breadth': None, 'streak': 0, 'rule': ''}


def load_ranking_for_regime(date_str: str, regime_mode: str):
    """국면에 맞는 랭킹 파일 로드 (v79: boost=state/, defense=state/defense/).
    (v77.1의 cash 모드는 v79에서 제거됨)
    """
    if regime_mode == 'defense':
        def_path = STATE_DIR / 'defense' / f'ranking_{date_str}.json'
        if def_path.exists():
            with open(def_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    return load_ranking(date_str)


def get_available_regime_dates(regime_mode: str):
    """랭킹 파일의 날짜 목록 (최신순, v75: 단일 ranking 파일)."""
    files = sorted(STATE_DIR.glob('ranking_*.json'), reverse=True)
    dates = []
    for f in files:
        date_str = f.stem.replace('ranking_', '')
        if len(date_str) == 8 and date_str.isdigit():
            dates.append(date_str)
    return dates


def expand_single_date_to_3days(target_date: str, regime_mode: str):
    """단일 날짜가 주어졌을 때, 해당 날짜 이하 최근 3거래일 자동 확장.

    target_date 포함, 그 이전의 랭킹 파일이 있는 날짜 2개를 추가.
    """
    available = get_available_regime_dates(regime_mode)
    # target_date 이하만 필터
    candidates = [d for d in available if d <= target_date]
    return candidates[:3]


# ============================================================
# 시스템 수익률 추적
# ============================================================
def calc_system_returns(regime_info=None):
    """프로덕션 ranking 히스토리로 시스템 누적 수익률 계산 (국면 파라미터 반영).

    Returns:
        dict: {system_pct, kospi_pct, start_date, days, holdings} or None
    """
    import glob as _glob
    from regime_indicator import get_regime_params

    # 국면별 ranking 파일 + regime_state에서 국면 이력 추적
    regime_state_path = STATE_DIR / 'regime_state.json'
    regime_mode = 'defense'
    if regime_state_path.exists():
        with open(regime_state_path, 'r', encoding='utf-8') as f:
            rs = json.load(f)
            regime_mode = rs.get('mode', 'defense')

    # 국면별 파라미터
    rp_boost = get_regime_params('boost')
    rp_defense = get_regime_params('defense')

    # 양쪽 ranking 파일 모두 로드
    today_str = get_korea_now().strftime('%Y%m%d')
    boost_data = {}
    defense_data = {}
    for label, data_dict, ranking_dir in [
        ('boost', boost_data, STATE_DIR),
        ('defense', defense_data, STATE_DIR / 'defense'),
    ]:
        files = sorted(_glob.glob(str(ranking_dir / 'ranking_*.json')))
        files = [f for f in files if 'boost' not in os.path.basename(f).replace('ranking_','')
                 and 'core' not in f and 'backup' not in f]
        for fp in files:
            d = os.path.basename(fp).replace('ranking_', '').replace('.json', '')
            if d > today_str:
                continue
            with open(fp, 'r', encoding='utf-8') as fh:
                data_dict[d] = json.load(fh)

    # reranking 불필요 — ranking 파일이 이미 현재 버전 파라미터로 재계산됨
    # 버전 변경 시 전체 파일 재계산 필수 (feedback_full_rerank_on_version_change.md)

    # 날짜별 국면 판단 (v80.6: KP_MA250_8d)
    _kospi_file = Path(__file__).parent / 'data_cache' / 'kospi_yf.parquet'
    if _kospi_file.exists():
        _kdf = pd.read_parquet(_kospi_file)
        _kospi = _kdf.iloc[:, 0].copy()
        for _c in _kdf.columns[1:]:  # 옛 멀티컬럼 호환 (종가+kospi 보완)
            _kospi = _kospi.fillna(_kdf[_c])
        _kospi = _kospi.dropna()
    else:
        _kospi = pd.Series()
    from regime_indicator import MA_PERIOD, CONFIRM_DAYS
    _kma = _kospi.rolling(MA_PERIOD).mean() if len(_kospi) >= MA_PERIOD else pd.Series()

    all_boost_dates = sorted(boost_data.keys())
    regime_by_date = {}
    _md = False; _stk = 0; _ss = False
    for d in all_boost_dates:
        ts = pd.Timestamp(d)
        kv = _kospi.get(ts, None); mv = _kma.get(ts, None)
        s = (kv > mv) if kv is not None and mv is not None else _md
        if s == _ss: _stk += 1
        else: _stk = 1; _ss = s
        if _stk >= CONFIRM_DAYS and _md != s: _md = s  # v80.6: MA250 8d (regime_indicator에서 로드)
        regime_by_date[d] = _md  # True=공격, False=방어

    # 날짜별 국면에 맞는 ranking + 파라미터 선택
    all_data = {}
    dates = []
    for d in all_boost_dates:
        is_boost = regime_by_date.get(d, True)
        if is_boost and d in boost_data:
            all_data[d] = boost_data[d]
            dates.append(d)
        elif not is_boost and d in defense_data:
            all_data[d] = defense_data[d]
            dates.append(d)
        elif d in boost_data:  # 방어 파일 없으면 공격으로 대체
            all_data[d] = boost_data[d]
            dates.append(d)

    # 가격: OHLCV 기반 — _full 파일 우선 (전종목)
    import glob as _glob2
    _ohlcv_files = sorted(_glob2.glob(str(Path(__file__).parent / 'data_cache' / 'all_ohlcv_*.parquet')))
    _full_files = [f for f in _ohlcv_files if '_full' in f]
    if _full_files:
        _ohlcv_files = _full_files
    if _ohlcv_files:
        _ohlcv_parts = [pd.read_parquet(f).replace(0, np.nan) for f in _ohlcv_files]
        _ohlcv = pd.concat(_ohlcv_parts).groupby(level=0).first()
    else:
        _ohlcv = pd.DataFrame()

    def _get_price(ticker, date_str):
        ts = pd.Timestamp(date_str)
        if not _ohlcv.empty and ts in _ohlcv.index and ticker in _ohlcv.columns:
            v = _ohlcv.loc[ts, ticker]
            if pd.notna(v) and v > 0:
                return v
        return 0

    # 포트폴리오 시뮬레이션 — 일간 수익률 기반 + 손절 + 트레일링
    # (2026-05-16: TS cooldown 제거 — 사용자 명시 "TS/SL은 고객 판단" 정책 일치)
    portfolio = {}  # ticker → entry_price
    peak_prices = {}  # ticker → 보유 중 최고가 (트레일링용)
    equity = 1.0
    start_date = None
    equity_history = {}  # date → equity

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
        equity_history[d0] = equity

        if i < 2:
            continue  # 3일 데이터 필요

        # 국면별 파라미터 선택
        is_boost = regime_by_date.get(d0, True)
        rp = rp_boost if is_boost else rp_defense
        _entry_rank = rp['ENTRY_RANK']
        _exit_rank = rp['EXIT_RANK']
        _max_slots = rp['MAX_SLOTS']
        _stop_loss = rp.get('STOP_LOSS', -0.10)  # v80.6: SL -10% 유지

        # 국면 전환 시 포트폴리오 전량 청산
        if i >= 1:
            prev_boost = regime_by_date.get(dates[i-1], True)
            if is_boost != prev_boost:
                portfolio.clear()
                peak_prices.clear()

        # 손절 + 트레일링 체크 (시뮬용 알파 측정, production은 고객 판단)
        _trailing_stop = rp.get('TRAILING_STOP', -0.08)
        for tk in list(portfolio.keys()):
            cp = _get_price(tk, d0)
            ep = portfolio[tk]
            if tk in peak_prices:
                if cp > peak_prices[tk]:
                    peak_prices[tk] = cp
            else:
                peak_prices[tk] = max(cp, ep) if cp > 0 else ep
            # 손절: 진입가 대비
            if cp > 0 and ep > 0 and (cp / ep - 1) <= _stop_loss:
                del portfolio[tk]
                peak_prices.pop(tk, None)
            # 트레일링: 고점 대비
            elif cp > 0 and peak_prices.get(tk, 0) > 0 and (cp / peak_prices[tk] - 1) <= _trailing_stop:
                del portfolio[tk]
                peak_prices.pop(tk, None)

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

        # PENALTY=50 (production _postprocess_ranking과 일치, 누락 종목 매도 가속 X)
        _PEN = 50
        def _wr(tk):
            if tk not in all_t0:
                return _PEN
            cr0 = all_t0[tk].get('composite_rank', all_t0[tk].get('rank', _PEN))
            cr1 = all_t1[tk].get('composite_rank', all_t1[tk].get('rank', _PEN)) if tk in all_t1 else _PEN
            cr2 = all_t2[tk].get('composite_rank', all_t2[tk].get('rank', _PEN)) if tk in all_t2 else _PEN
            return cr0 * 0.5 + cr1 * 0.3 + cr2 * 0.2

        # 이탈: 가중순위 > exit_rank (국면별)
        for tk in list(portfolio.keys()):
            if _wr(tk) > _exit_rank:
                del portfolio[tk]

        # 진입용: 3일 교집합 + 가중순위 계산
        verified = []
        for tk in common:
            cr0 = top20_t0[tk].get('composite_rank', top20_t0[tk]['rank'])
            cr1 = top20_t1[tk].get('composite_rank', top20_t1[tk]['rank'])
            cr2 = top20_t2[tk].get('composite_rank', top20_t2[tk]['rank'])
            wr = cr0 * 0.5 + cr1 * 0.3 + cr2 * 0.2
            verified.append({'ticker': tk, 'weighted_rank': wr,
                             'composite_rank': cr0,
                             'price': top20_t0[tk].get('price', 0)})
        # 동점 tie-breaker: cr 작은 쪽(오늘 더 강한 종목) 우선 (v80)
        verified.sort(key=lambda x: (x['weighted_rank'], x['composite_rank']))

        # 진입: 상위 entry_rank개 (국면별)
        for v in verified[:_entry_rank]:
            if v['ticker'] in portfolio:
                continue
            if len(portfolio) >= _max_slots:
                break
            entry_price = _get_price(v['ticker'], d0)
            if entry_price > 0:
                portfolio[v['ticker']] = entry_price
                peak_prices[v['ticker']] = entry_price
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

    # YTD / 최근 1개월 수익률 (시스템 + 코스피)
    ytd_pct = month_pct = kospi_ytd = kospi_month = None
    year_start = dates[-1][:4] + '0101'
    month_ago = (pd.Timestamp(dates[-1]) - pd.Timedelta(days=30)).strftime('%Y%m%d')

    ytd_dates = [d for d in sorted(equity_history) if d >= year_start]
    if len(ytd_dates) >= 2:
        eq_s, eq_e = equity_history[ytd_dates[0]], equity_history[ytd_dates[-1]]
        if eq_s > 0:
            ytd_pct = round((eq_e / eq_s - 1) * 100, 1)

    month_dates = [d for d in sorted(equity_history) if d >= month_ago]
    if len(month_dates) >= 2:
        eq_s, eq_e = equity_history[month_dates[0]], equity_history[month_dates[-1]]
        if eq_s > 0:
            month_pct = round((eq_e / eq_s - 1) * 100, 1)

    # 코스피/코스닥 YTD/1개월
    kosdaq_ytd = kosdaq_month = None
    for idx_name, idx_code, ytd_key, month_key in [('kospi', '1001', 'kospi_ytd', 'kospi_month'),
                                                     ('kosdaq', '2001', 'kosdaq_ytd', 'kosdaq_month')]:
        try:
            idx_ohlcv = stock.get_index_ohlcv(year_start, dates[-1], idx_code)
            if not idx_ohlcv.empty and len(idx_ohlcv) >= 2:
                i_first = idx_ohlcv.iloc[0, 3]
                i_last = idx_ohlcv.iloc[-1, 3]
                if i_first > 0:
                    if idx_name == 'kospi':
                        kospi_ytd = round((i_last / i_first - 1) * 100, 1)
                    else:
                        kosdaq_ytd = round((i_last / i_first - 1) * 100, 1)
                i_month = idx_ohlcv[idx_ohlcv.index >= pd.Timestamp(month_ago)]
                if len(i_month) >= 2:
                    im_first = i_month.iloc[0, 3]
                    if im_first > 0:
                        if idx_name == 'kospi':
                            kospi_month = round((i_last / im_first - 1) * 100, 1)
                        else:
                            kosdaq_month = round((i_last / im_first - 1) * 100, 1)
        except Exception:
            pass

    return {
        'system_pct': round(system_pct, 1),
        'kospi_pct': round(kospi_pct, 1),
        'start_date': start_date,
        'days': len(dates) - 2,
        'holdings': len(portfolio),
        'ytd_pct': ytd_pct,
        'month_pct': month_pct,
        'kospi_ytd': kospi_ytd,
        'kospi_month': kospi_month,
        'kosdaq_ytd': kosdaq_ytd,
        'kosdaq_month': kosdaq_month,
    }


# ============================================================
# 유틸리티 함수
# ============================================================
def get_korea_now():
    return datetime.now(KST)


def get_recent_trading_dates(n=3):
    """최근 N개 거래일 찾기 — ranking 파일 우선 (postprocessing과 동일 기준)"""
    today = get_korea_now()
    today_str = today.strftime('%Y%m%d')
    # 1차: ranking 파일 기준 (postprocessing과 동일 날짜 사용 보장)
    state_dir = Path(__file__).parent / 'state'
    rk_dates = set()
    for f in state_dir.glob('ranking_*.json'):
        d = f.stem.replace('ranking_', '')
        if len(d) == 8 and d.isdigit() and d <= today_str:
            rk_dates.add(d)
    if len(rk_dates) >= n:
        sorted_dates = sorted(rk_dates, reverse=True)[:n]
        return sorted_dates
    # 2차: market_cap 캐시 폴백
    cache_dir = Path(__file__).parent / 'data_cache'
    mc_dates = set()
    for f in cache_dir.glob('market_cap_ALL_*.parquet'):
        d = f.stem.split('_')[-1]
        if len(d) == 8 and d.isdigit() and d <= today_str:
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


def _calc_jump_revcv(ticker, base_date):
    """fs_dart parquet에서 매출 jump + revcv 계산 (PIT, rcept_dt <= base_date).
    jump = 최근 분기 매출 / 직전 4분기 평균
    revcv = 직전 4분기 매출의 std/mean (변동계수)
    """
    import numpy as np
    fp = Path(__file__).parent / 'data_cache' / f'fs_dart_{str(ticker).zfill(6)}.parquet'
    if not fp.exists():
        return None, None
    try:
        df = pd.read_parquet(fp)
        if '공시구분' not in df.columns or 'rcept_dt' not in df.columns:
            return None, None
        base_ts = pd.Timestamp(datetime.strptime(base_date, '%Y%m%d'))
        q = df[(df['공시구분'] == 'q') & (df['계정'] == '매출액')].sort_values('기준일')
        q = q[q['rcept_dt'].notna() & (pd.to_datetime(q['rcept_dt']) <= base_ts)]
        if len(q) < 5:
            return None, None
        vals = q['값'].values
        prev4 = vals[-5:-1]
        cur = vals[-1]
        pm = float(np.mean(prev4))
        if pm <= 0:
            return None, None
        return cur / pm, float(np.std(prev4)) / pm
    except Exception:
        return None, None


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
        # 이격도20 (정보 표시용, v80.9 BT 결과 안전망 효과 X → 차단 X)
        sma20 = ohlcv['종가'].tail(20).mean() if len(ohlcv) >= 20 else None
        disparity20 = (price / sma20) if (sma20 and sma20 > 0) else None
        # 매출 jump + revcv (v80.9 안전망, 2026-05-16 BT 검증 Cal +0.274 / WF min 1.791)
        jump, revcv = _calc_jump_revcv(ticker_str, base_date)

        return {
            'price': price, 'daily_chg': daily_chg,
            'rsi': rsi, 'w52_pct': w52_pct,
            'sma20': sma20, 'disparity20': disparity20,
            'jump': jump, 'revcv': revcv,
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
def _post_telegram_retry(url, data, retries=4, timeout=30):
    """Telegram API POST with exponential backoff retry (for ConnectTimeout/network blips)."""
    for i in range(retries):
        try:
            return requests.post(url, data=data, timeout=timeout)
        except requests.exceptions.RequestException as e:
            wait = 5 * (2 ** i)  # 5, 10, 20, 40s
            if i < retries - 1:
                print(f"  [Telegram] 전송 실패 ({type(e).__name__}) — {wait}s 후 재시도 ({i+1}/{retries})")
                time.sleep(wait)
            else:
                print(f"  [Telegram] 전송 실패 — 재시도 소진 ({retries}회)")
                raise


def send_telegram_long(text, bot_token, chat_id):
    """긴 메시지 자동 분할 전송 (4000자 기준) + 네트워크 재시도"""
    MAX_LEN = 4000
    url = f'https://api.telegram.org/bot{bot_token}/sendMessage'

    if len(text) <= MAX_LEN:
        return [_post_telegram_retry(url, {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'})]

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
        r = _post_telegram_retry(url, {'chat_id': chat_id, 'text': chunk, 'parse_mode': 'HTML'})
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


def create_regime_switch_message(regime_mode, prev_mode=None):
    """국면 전환 시 별도 안내 메시지 — Signal 메시지 앞에 전송

    v79 (2026-04-15, 금융 고객 커뮤니케이션 컨설팅 반영):
      - 모드 2개: boost / defense (cash 모드 제거)
      - 톤: 증권사 공식 안내문 (담백, 볼드 최소)
      - CAGR/MDD/Calmar 등 내부 용어 전면 삭제, 일반 투자자 용어로 번역
      - 매매 기준 + 성과 2지표 명시
    """
    if regime_mode == 'boost':
        return '\n'.join([
            '[모드 전환] 상승 추세로 전환되었습니다',
            '',
            '■ 오늘의 판단',
            '',
            '  코스피가 250일 이동평균선 위에서',
            '  8거래일 연속 마감했습니다.',
            "  시장이 단기 반등이 아닌 '상승 추세'에 들어섰다고 봅니다.",
            '',
            '  이에 따라 전략을 방어 모드에서 공격 모드로 전환합니다.',
            '',
            '■ 구독자께서 하실 일',
            '',
            '  1. 현재 방어 모드로 보유 중인 종목은 전량 정리해주세요.',
            '  2. 오늘 브리핑에 ✅ 로 표시된 종목 중 상위부터',
            '     새로 진입하시면 됩니다.',
            '  3. 종목당 동일한 금액으로 최대 5종목까지 담는 것이',
            '     기본 운용 방식입니다.',
            '',
            '■ 공격 모드 매매 기준',
            '',
            '  · 매수: 3일 연속 ✅ 상위 3종목',
            '  · 매도 (셋 중 하나):',
            '     - 3일 가중순위 6위 밖',
            '     - 매수가 대비 -10% 손절',
            '     - 최고가 대비 -8% 고점매도',
            '  · 보유: 최대 5종목, 균등 비중',
            '  · 매수 방식: 분할매수 권장 (1차 50% + 다음날 추가)',
            '',
            '■ 공격 모드가 작동하는 방식',
            '',
            "  상승장에서는 '실적이 빠르게 성장하는 종목'이",
            '  가장 크게 오르는 경향이 있습니다.',
            '  매출·영업이익 성장세와 최근 12개월 주가 추세를 중심으로',
            '  상위 3종목에 신규 진입하고, 보유 중인 종목 포함',
            '  최대 5종목으로 분산합니다.',
            '',
            '■ 전략 성과 (지난 7.4년, 2019-01~2026-05)',
            '',
            '  · 연평균 수익률  +105%  (같은 기간 코스피 대비 압도)',
            '  · 최대 손실폭    -34%',
            '',
            '───────────────────────────',
            '본 서비스는 종목 선정을 돕는 참고 자료이며,',
            '매수·매도 실행과 비중 결정은 구독자 본인의 판단입니다.',
            '투자에는 원금 손실 가능성이 있으며,',
            '최종 책임은 투자자 본인에게 있습니다.',
        ])

    # defense
    return '\n'.join([
        '[모드 전환] 하락 추세로 전환되었습니다',
        '',
        '■ 오늘의 판단',
        '',
        '  코스피가 250일 이동평균선 아래에서',
        '  8거래일 연속 마감했습니다.',
        "  일시적 조정이 아닌 '하락 추세'에 들어섰다고 봅니다.",
        '',
        '  이에 따라 전략을 공격 모드에서 방어 모드로 전환합니다.',
        '',
        '■ 구독자께서 하실 일',
        '',
        '  1. 현재 공격 모드로 보유 중인 종목은 전량 정리해주세요.',
        '     (설령 수익 중인 종목이라도 원칙상 정리합니다.',
        '      하락장에서 성장주는 가장 크게 되밀리기 때문입니다.)',
        '  2. 오늘 브리핑에 ✅ 로 표시된 종목 중 상위부터',
        '     새로 진입하시면 됩니다.',
        '  3. 종목당 동일한 금액으로 최대 5종목까지',
        '     분산해 담는 것이 기본 운용 방식입니다.',
        '',
        '■ 방어 모드 매매 기준',
        '',
        '  · 매수: 3일 연속 ✅ 상위 5종목',
        '  · 매도 (셋 중 하나):',
        '     - 3일 가중순위 8위 밖',
        '     - 매수가 대비 -10% 손절',
        '     - 최고가 대비 -8% 고점매도',
        '  · 보유: 최대 5종목, 균등 비중',
        '  · 매수 방식: 분할매수 권장 (1차 50% + 다음날 추가)',
        '',
        '■ 방어 모드가 작동하는 방식',
        '',
        "  하락장에서는 '더 싸고, 덜 망가진 종목'이",
        '  상대적으로 잘 버티는 경향이 있습니다.',
        '  최근 6개월 주가 추세가 살아있으면서 밸류에이션 부담이 낮은',
        '  종목 중심으로 5개에 분산합니다.',
        '',
        '■ 전략 성과 (지난 7.4년, 2019-01~2026-05)',
        '',
        '  · 연평균 수익률  +105%  (같은 기간 코스피 대비 압도)',
        '  · 최대 손실폭    -34%  (이전 버전 대비 7%p 개선)',
        '',
        '───────────────────────────',
        '본 서비스는 종목 선정을 돕는 참고 자료이며,',
        '매수·매도 실행과 비중 결정은 구독자 본인의 판단입니다.',
        '투자에는 원금 손실 가능성이 있으며,',
        '최종 책임은 투자자 본인에게 있습니다.',
    ])


def create_signal_message(picks, pipeline, exited, biz_day, ai_narratives,
                          market_max_picks, stock_weight, rankings_t0,
                          rankings_t1, rankings_t2, cold_start,
                          final_action, pick_level, system_returns=None,
                          regime_info=None):
    """Message 1: Signal — 결론 (뭘 살까)

    종목당 3줄: 이름·업종·가격 / 순위 / AI 내러티브
    """
    wd = WEEKDAY_KR[biz_day.weekday()]
    date_str = f"{biz_day.year}.{biz_day.month}.{biz_day.day}({wd})"

    # 국면 모드 표시 — regime_state.json 기반 우선 (v79: cash 모드 제거)
    if regime_info:
        r_mode = regime_info.get('mode', 'defense')
        r_breadth = regime_info.get('breadth')
        if r_mode == 'boost':
            regime_icon = '⚔️'
            regime_text = '공격 모드 (Growth 중심)'
        else:
            regime_icon = '🛡️'
            regime_text = '방어 모드 (Momentum 중심)'
        breadth_str = f' · 브레스 {r_breadth:.1%}' if r_breadth is not None else ''
        regime_label = f'{regime_icon} <b>{regime_text}</b>{breadth_str}'
    else:
        regime_mode = os.environ.get('REGIME_MODE', 'defense')
        if regime_mode == 'boost':
            regime_label = '⚔️ <b>공격 모드</b>'
        else:
            regime_label = '🛡️ <b>방어 모드</b>'

    lines = [
        f'📡 AI 종목 브리핑 KR · {date_str}',
        regime_label,
    ]

    lines += [
        '국내 전 종목을 매일 자동 분석한',
        '종합 점수 상위 종목입니다.',
    ]

    # v79: cash 모드 제거 (Crash Cash 삭제됨)

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

    # ── 시스템 수익률 ──
    if system_returns and system_returns.get('days', 0) >= 5:
        sr = system_returns
        lines.append('')
        lines.append('📈 <b>시스템 수익률</b>')
        if sr.get('ytd_pct') is not None:
            ky = sr.get('kospi_ytd')
            kd = sr.get('kosdaq_ytd')
            idx = f' (코스피 {ky:+.1f}% 코스닥 {kd:+.1f}%)' if ky is not None and kd is not None else (f' (코스피 {ky:+.1f}%)' if ky is not None else '')
            lines.append(f'올해 {sr["ytd_pct"]:+.1f}%{idx}')
        if sr.get('month_pct') is not None:
            km = sr.get('kospi_month')
            kmd = sr.get('kosdaq_month')
            idx = f' (코스피 {km:+.1f}% 코스닥 {kmd:+.1f}%)' if km is not None and kmd is not None else (f' (코스피 {km:+.1f}%)' if km is not None else '')
            lines.append(f'1개월 {sr["month_pct"]:+.1f}%{idx}')
        if sr.get('ytd_pct') is None and sr.get('month_pct') is None:
            lines.append(f'누적 {sr["system_pct"]:+.1f}% (코스피 {sr["kospi_pct"]:+.1f}%)')

    n = len(picks)
    lines.append('')
    lines.append('━━━━━━━━━━━━━━━')
    lines.append('🛒 <b>매수 후보 종목</b>')
    lines.append('━━━━━━━━━━━━━━━')
    for i, pick in enumerate(picks):
        sector = pick.get('sector', '기타')
        lines.append(f'<b>{i+1}. {pick["name"]}({pick["ticker"]}) · {sector}</b>')

    # v74: 상관관계 경고 제거 (전략에서 corr 필터 미사용)
    meta = rankings_t0.get('metadata') or {}

    # ── 선정 과정 (퍼널) ──
    universe_count = meta.get('total_universe', 0)
    prefilter_count = meta.get('prefilter_passed', 0)
    scored_count = meta.get('scored_count', 0)
    v_count = sum(1 for s in pipeline if s['status'] == '✅')
    lines.append('')
    lines.append('📋 <b>선정 과정</b>')
    lines.append('국내 상장 전 종목 대상')
    lines.append('→ 재무·성장·수익성·추세 종합 채점')
    lines.append('→ 상위 20종목 매일 모니터링')
    lines.append(f'→ 3일 연속 상위 유지 {n}종목 선정')

    # ── 종목별 근거 ──
    lines.append('')
    lines.append('━━━━━━━━━━━━━━━')
    lines.append('📌 <b>종목 선정 근거</b>')
    lines.append('━━━━━━━━━━━━━━━')

    # cr 정렬 후 정수 순위 맵 (Signal 궤적용) — 당일 순수 실력 표시
    def _cr_int_rank_map_sig(rankings):
        if not rankings:
            return {}
        rlist = rankings.get('rankings', [])
        sorted_by_cr = sorted(rlist, key=lambda r: r.get('composite_rank', 999))
        return {r['ticker']: i + 1 for i, r in enumerate(sorted_by_cr)}

    t0_cr_sig = _cr_int_rank_map_sig(rankings_t0)
    t1_cr_sig = _cr_int_rank_map_sig(rankings_t1)
    t2_cr_sig = _cr_int_rank_map_sig(rankings_t2)

    for i, pick in enumerate(picks):
        ticker = pick['ticker']
        name = pick['name']
        sector = pick.get('sector', '기타')
        price = (pick.get('_tech') or {}).get('price', 0)

        # L0: 이름·업종·가격 (볼드)
        price_str = f'₩{price:,.0f}' if price else ''
        lines.append(f'<b>{i+1}. {name}({ticker}) {sector} · {price_str}</b>')

        # 궤적 = 각 날짜 cr-rank (당일 순수 실력). 점수 = 선형 wr 차이 반영
        r0 = t0_cr_sig.get(ticker, '-')
        r1 = t1_cr_sig.get(ticker, '-')
        r2 = t2_cr_sig.get(ticker, '-')
        # 100 - (wr - 1위_wr) × 5: wr 차이가 그대로 점수 차이로 (선형, 하한 5점)
        wr_val = pick.get('weighted_rank', pick.get('rank', i + 1))
        min_wr = picks[0].get('weighted_rank', picks[0].get('rank', 1)) if picks else 1
        score_100 = max(5.0, min(100.0, 100.0 - (wr_val - min_wr) * 5))
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

    # 순위 이탈 알림은 Watchlist 메시지(Top 20)에 통합 — Signal에선 제거

    # ── Signal footer: 매매 룰 (간결) ──
    _rule_e = ENTRY_RANK
    _rule_x = EXIT_RANK
    _rule_s = MAX_SLOTS
    try:
        from regime_indicator import get_regime_params as _grp_sig
        _rp_sig = _grp_sig(os.environ.get('REGIME_MODE', 'defense'))
        _rule_e = _rp_sig.get('ENTRY_RANK', ENTRY_RANK)
        _rule_x = _rp_sig.get('EXIT_RANK', EXIT_RANK)
        _rule_s = _rp_sig.get('MAX_SLOTS', MAX_SLOTS)
    except Exception:
        pass
    lines.append('')
    lines.append('━━━━━━━━━━━━━━━')
    lines.append(f'매수: 3일 연속 상위 {_rule_e}종목 (최대 {_rule_s}종목)')
    lines.append('')
    lines.append('매도 (아래 셋 중 하나라도 해당 시)')
    lines.append('• 매도 기준선 이탈 (Top 20 메시지 참고)')
    lines.append('• 매수가 대비 -10% 시')
    lines.append('• 최고가 대비 -8% 시')
    lines.append('')
    lines.append('분할매수 권장 (1차 50% + 다음날 추가)')
    lines.append('시스템은 신호만, 매매는 본인 판단')

    return '\n'.join(lines)


def create_ai_risk_message(credit, kospi_data, kosdaq_data, market_warnings,
                           ai_msg, biz_day, picks, final_action):
    """Message 2: AI Risk — 맥락 (시장 환경 + 리스크)

    시장 데이터(코스피/코스닥/HY/BBB-/VIX) + AI 해석 + 매수 주의
    """
    kospi_close, kospi_chg, kospi_color = kospi_data
    kosdaq_close, kosdaq_chg, kosdaq_color = kosdaq_data

    lines = [
        '━━━━━━━━━━━━━━━',
        '🤖 AI 리스크 필터',
        '━━━━━━━━━━━━━━━',
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
                             score_100_map=None, system_returns=None,
                             rp_current=None):
    """Message 3: Watchlist — 데이터 (Top 20 모니터링)

    종목당 1줄: 상태+순위+이름(업종)+순위궤적
    rank 순 정렬 (✅/⏳/🆕 인라인 마커)
    """
    lines = [
        '📋 <b>Top 20 종목 현황</b>',
        '상위 20종목과 순위 변동 현황입니다.',
        (f'✅ 3일 검증 ⏳ 2일 관찰 🆕 신규 진입 | 손절 {int(rp_current["STOP_LOSS"]*100)}%' if rp_current and rp_current.get("STOP_LOSS") else '✅ 3일 검증 ⏳ 2일 관찰 🆕 신규 진입') if rp_current else '✅ 3일 검증 ⏳ 2일 관찰 🆕 신규 진입 | 손절 -10%',
    ]

    if not pipeline:
        lines.append('━━━━━━━━━━━━━━━')
        lines.append('데이터 없음')
        return '\n'.join(lines)

    # 궤적 = cr 정렬 후 정수 순위 (당일 순수 실력 표시)
    def _cr_int_rank_map(rankings):
        if not rankings:
            return {}
        rlist = rankings.get('rankings', [])
        sorted_by_cr = sorted(rlist, key=lambda r: r.get('composite_rank', 999))
        return {r['ticker']: i + 1 for i, r in enumerate(sorted_by_cr)}

    t0_cr = _cr_int_rank_map(rankings_t0)
    t1_cr = _cr_int_rank_map(rankings_t1)
    t2_cr = _cr_int_rank_map(rankings_t2)

    for s in pipeline:
        s['_r0'] = t0_cr.get(s['ticker'], '-')
        # 🆕(1일) → T-1/T-2 검증 안 됨, ⏳(2일) → T-2 검증 안 됨 → '-' 표시
        # ✅(3일 검증)만 r1/r2 cr 순위 표시
        _st = s.get('status', '')
        if _st == '🆕':
            s['_r1'] = '-'
            s['_r2'] = '-'
        elif _st == '⏳':
            s['_r1'] = t1_cr.get(s['ticker'], '-')
            s['_r2'] = '-'
        else:  # ✅ 또는 미정
            s['_r1'] = t1_cr.get(s['ticker'], '-')
            s['_r2'] = t2_cr.get(s['ticker'], '-')

    # v70: weighted_rank 순 정렬 (rank 기반 진입/이탈과 일관)
    # v80: 동점 tie-breaker를 cr 작은 쪽(오늘 더 강한 종목) 우선 — 파일 생성/궤적 맵과 일치
    sorted_pipeline = sorted(pipeline, key=lambda x: (x.get('weighted_rank', x['rank']), x.get('composite_rank', 999)))

    # Watchlist 이격도20 차단 제거 (v80.9 BT 2026-05-16):
    # 47 시나리오 BT 결과 sma20 모든 임계 알파 손해 (-0.05 ~ -0.43).
    # v80.6 시절 +0.18 → v80.9 -0.151 환경 반전. 차단 무의미.
    # 또 진정 가속 성장 종목 (SK하이닉스/제주반도체)까지 차단 위험 → 관찰 표시 유지.

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

    # v79: 점수 = 100 - (wr - 1위_wr) × 5 (선형, wr 차이가 점수 차이로 직접 반영)
    # 1위=100, wr 1증가 = 5점 감소. 하한 5점. 순위 역전 가능성 한눈에 파악.

    _all_wr = [s.get('weighted_rank', 999) for s in display_pipeline]
    _min_wr = min(_all_wr) if _all_wr else 1

    exit_line_shown = False
    _cur_exit = rp_current.get('EXIT_RANK', EXIT_RANK) if rp_current else EXIT_RANK
    for idx, s in enumerate(display_pipeline, 1):
        name = s['name']
        sector = _SECTOR_SHORT.get(s.get('sector', '기타'), s.get('sector', '기타'))
        status = s['status']
        # 궤적 = 각 날짜 cr-rank (당일 순수 실력)
        r0 = s.get('_r0', idx)  # T-0 cr-rank
        r1 = s.get('_r1', '-')  # T-1 cr-rank
        r2 = s.get('_r2', '-')  # T-2 cr-rank
        w_rank_val = s.get('weighted_rank', idx)
        score_100 = max(5.0, min(100.0, 100.0 - (w_rank_val - _min_wr) * 5))
        score_disp = f'{score_100:.1f}'

        # 매도 기준선: 3일 가중순위 > EXIT_RANK 첫 종목 직전 (룰은 footer에 명시)
        w_rank = s.get('weighted_rank', 999)
        if not exit_line_shown and w_rank > _cur_exit:
            lines.append('━━━━━ 매도 기준선 ━━━━━')
            exit_line_shown = True

        # 궤적: cr-rank 그대로 표시 (없으면 "-")
        lines.append(f'{status} {idx}. {name}({sector}) {r2}→{r1}→{r0}위 · {score_disp}점')

    # ── 이탈 섹션 (사유별 묶기, 20위 다음 빈 줄 없이 바로) ──
    if exited:
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

    # NAV 디스카운트 섹션 제거 (2026-05-18, 사용자 명시: 메시지에서 빼자)
    # nav_discount_module.py 코드 + state/nav_discount.json은 유지 (나중 재활성 가능)

    # ── Watchlist footer: 면책 (간결, 빈 줄 없이 붙임) ──
    lines.append('━━━━━━━━━━━━━━━')
    lines.append('순위 표기: 3일 가중순위 (2일전 → 1일전 → 오늘)')
    lines.append('투자 손실 책임은 투자자 본인에게 있습니다.')

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
    # 국면(Regime) 상태 로드
    # ============================================================
    regime_info = load_regime_state()
    regime_mode = regime_info.get('mode', 'defense')
    # 환경변수가 있으면 우선 (run_daily.py에서 주입)
    if os.environ.get('REGIME_MODE'):
        regime_mode = os.environ['REGIME_MODE']
        regime_info['mode'] = regime_mode
    regime_switched = os.environ.get('REGIME_SWITCHED') == '1'
    regime_prev_mode = os.environ.get('REGIME_PREV_MODE', '')
    mode_transition = regime_switched
    print(f"\n[국면 상태] 모드: {regime_mode}, 브레스: {regime_info.get('breadth')}, "
          f"규칙: {regime_info.get('rule', '')}, 전환: {regime_switched}, prev: {regime_prev_mode}")

    # ============================================================
    # 날짜 계산 (최근 3거래일)
    # ============================================================
    TODAY = get_korea_now().strftime('%Y%m%d')

    if manual_dates:
        raw_dates = [d.strip() for d in manual_dates if d.strip()]
        # 단일 날짜 → 국면별 랭킹 파일 기반으로 3거래일 자동 확장
        if len(raw_dates) == 1:
            trading_dates = expand_single_date_to_3days(raw_dates[0], regime_mode)
            print(f"--dates {raw_dates[0]} → 3거래일 자동 확장: {trading_dates}")
        else:
            trading_dates = raw_dates
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
    # v80 이후 wr 기준 매수/매도 (점수 임계 X). 진입 ENTRY_RANK/퇴출 EXIT_RANK는 국면별 (regime_indicator 참조)
    print(f"\n[매수 추천 설정] 행동: {final_action} · 레벨: {pick_level['label']}")

    # ============================================================
    # 순위 데이터 로드 (3일) — 국면별 랭킹 파일 사용
    # ============================================================
    print(f"\n[순위 데이터 로드] 국면: {regime_mode}")
    rankings_t0 = load_ranking_for_regime(trading_dates[0], regime_mode)
    rankings_t1 = load_ranking_for_regime(trading_dates[1], regime_mode) if len(trading_dates) >= 2 else None
    rankings_t2 = load_ranking_for_regime(trading_dates[2], regime_mode) if len(trading_dates) >= 3 else None

    if rankings_t0 is None:
        print(f"T-0 ({trading_dates[0]}) 순위 없음! create_current_portfolio.py를 먼저 실행하세요.")
        sys.exit(1)

    # reranking 불필요 — ranking 파일이 이미 현재 버전 파라미터로 재계산됨

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
        system_returns = calc_system_returns(regime_info=None)
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
        # TS/SL cooldown 차단 제거 (2026-05-16 원복) — 사용자 지적:
        # 신규 가입자는 어느 날 가입할지 모름. 시스템이 매수했다고 가정 X.
        # TS/SL은 보유 중인 사용자가 알아서 지키는 룰. 매수 후보 표시는 모두에게 동일.
        verified_picks = [s for s in pipeline if s['status'] == '✅']
        verified_picks.sort(key=lambda x: score_100_pre.get(x['ticker'], 0), reverse=True)
        print(f"  ✅ 검증 종목: {len(verified_picks)}개")

        # cr 정렬 후 정수 순위 맵 (main 궤적용) — 당일 순수 실력 표시
        def _cr_int_rank_map_main(rankings):
            if not rankings:
                return {}
            rlist = rankings.get('rankings', [])
            sorted_by_cr = sorted(rlist, key=lambda r: r.get('composite_rank', 999))
            return {r['ticker']: i + 1 for i, r in enumerate(sorted_by_cr)}

        t0_cr_rank_main = _cr_int_rank_map_main(rankings_t0)
        t1_cr_rank_main = _cr_int_rank_map_main(rankings_t1)
        t2_cr_rank_main = _cr_int_rank_map_main(rankings_t2)

        # v80.9 매출 안전망 (BT 검증, 2026-05-16): jump > 2.0 AND revcv > 0.7
        # 47 시나리오 + 조합 BT: Cal 2.078 → 2.352 (+0.274), WF min 1.791, CV 0.544 (가장 안정)
        # 이전 sma20>1.5 안전망 제거 (v80.9 환경 반전 -0.151 손해)
        # AND 조건: jump 큰 진정 성장(SK하이닉스/제주반도체)은 통과, 함정 패턴(동아엘텍/선익시스템)만 차단
        JUMP_THRESHOLD = 2.0
        REVCV_THRESHOLD = 0.7
        overextended_excluded = []
        for candidate in verified_picks:
            tech = get_stock_technical(candidate['ticker'], BASE_DATE)
            candidate['_tech'] = tech
            candidate['rank_t0'] = t0_cr_rank_main.get(candidate['ticker'], candidate.get('composite_rank', candidate['rank']))
            candidate['rank_t1'] = t1_cr_rank_main.get(candidate['ticker'], '-')
            candidate['rank_t2'] = t2_cr_rank_main.get(candidate['ticker'], '-')
            daily_chg = (tech or {}).get('daily_chg', 0)

            if daily_chg <= -5:
                drop_info.append((candidate, daily_chg))

            # 매출 안전망: jump AND revcv 동시 초과 → 일회성 폭증 + 변동성 큰 함정 패턴
            jump = (tech or {}).get('jump')
            revcv = (tech or {}).get('revcv')
            if (jump is not None and revcv is not None
                    and jump > JUMP_THRESHOLD and revcv > REVCV_THRESHOLD):
                overextended_excluded.append((candidate, jump, revcv))
                print(f"  🚫 매출 안전망 차단: {candidate['name']} (jump {jump:.2f} > {JUMP_THRESHOLD} AND revcv {revcv:.2f} > {REVCV_THRESHOLD})")
                continue

            all_candidates.append(candidate)
            if tech:
                disp_str = f", 이격도20 {tech.get('disparity20', 0):.2f}" if tech.get('disparity20') else ''
                j = tech.get('jump'); c = tech.get('revcv')
                jc_str = f", jump {j:.2f}, revcv {c:.2f}" if (j is not None and c is not None) else ''
                print(f"    {candidate['name']}: rank {candidate['rank']}, RSI {tech['rsi']:.0f}, 52주 {tech['w52_pct']:.0f}%{disp_str}{jc_str}")
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
                    'disparity20': tech.get('disparity20'),  # v80.3: BT 검증 안전망 기준
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

    # v75: 국면별 진입/이탈/슬롯
    from ranking_manager import ENTRY_RANK as _DEFAULT_ENTRY, EXIT_RANK as _DEFAULT_EXIT, MAX_SLOTS as _DEFAULT_SLOTS
    try:
        from regime_indicator import get_regime_params as _grp2
        _rs_path2 = STATE_DIR / 'regime_state.json'
        _mode2 = 'defense'
        if _rs_path2.exists():
            with open(_rs_path2, 'r', encoding='utf-8') as _f2:
                _mode2 = json.load(_f2).get('mode', 'defense')
        _rp2 = _grp2(_mode2)
        _ENTRY = _rp2['ENTRY_RANK']
        _EXIT = _rp2['EXIT_RANK']
        _SLOTS = _rp2['MAX_SLOTS']
        _SL = _rp2.get('STOP_LOSS', -0.10)  # v80.2 rollback (2026-05-12)
    except Exception:
        _ENTRY, _EXIT, _SLOTS, _SL = _DEFAULT_ENTRY, _DEFAULT_EXIT, _DEFAULT_SLOTS, -0.10

    if market_max_picks == 0:
        picks = []
    else:
        # v80: 동점 tie-breaker는 cr 작은 쪽 우선 (매매 판단 일관성)
        picks = sorted(all_candidates, key=lambda x: (x.get('weighted_rank', 999), x.get('composite_rank', 999)))[:_ENTRY]
        picks = picks[:_SLOTS]
    if picks:
        stock_weight = round(100 / len(picks))
    _sl_s = f'{int(_SL*100)}%' if _SL else 'X'
    print(f"\n  최종 picks: {len(picks)}개 (진입: top{_ENTRY} · 이탈: wr>{_EXIT} · 슬롯: {_SLOTS} · 손절: {_sl_s})")

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
            import time as _t
            for _attempt in range(3):
                ai_picks_text = run_final_picks_analysis(final_stock_list, stock_weight, BASE_DATE, market_context=market_ctx)
                if ai_picks_text:
                    ai_narratives = parse_narratives(ai_picks_text)
                    if ai_narratives:
                        print(f"  AI 내러티브: {len(ai_narratives)}종목 추출 (시도 {_attempt+1})")
                        break
                print(f"  AI 내러티브 시도 {_attempt+1}/3 실패, 재시도...")
                _t.sleep(2)
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
        regime_info=regime_info,
    )

    msg_ai_risk = create_ai_risk_message(
        credit,
        (kospi_close, kospi_chg, kospi_color),
        (kosdaq_close, kosdaq_chg, kosdaq_color),
        market_warnings,
        ai_risk_ai_text,
        biz_day, picks, final_action,
    )

    # 현재 국면 파라미터
    try:
        from regime_indicator import get_regime_params as _grp
        _regime_state_path = STATE_DIR / 'regime_state.json'
        _cur_mode = 'defense'
        if _regime_state_path.exists():
            with open(_regime_state_path, 'r', encoding='utf-8') as _f:
                _cur_mode = json.load(_f).get('mode', 'defense')
        _rp = _grp(_cur_mode)
    except Exception:
        _rp = None

    msg_watchlist = create_watchlist_message(
        pipeline, exited, rankings_t0, rankings_t1, rankings_t2,
        cold_start=cold_start, credit=credit,
        score_100_map=score_100_pre,
        system_returns=system_returns,
        rp_current=_rp,
    )

    messages = []
    # 국면 전환 시 전환 안내 메시지를 먼저 전송 (v79: boost ↔ defense만)
    if mode_transition:
        msg_switch = create_regime_switch_message(regime_mode, prev_mode=regime_prev_mode)
        messages.append(msg_switch)
        print(f"\n[국면 전환] {regime_prev_mode or '?'} → {regime_mode} 전환 안내 메시지 추가")
    messages += [msg_signal, msg_ai_risk, msg_watchlist]

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
    msg_labels = (['Regime Switch'] if mode_transition else []) + ['Signal', 'AI Risk', 'Watchlist']
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
        def _send_batch(target_id, label):
            """한 타깃(채널/개인봇)에 3개 메시지 순차 전송. 개별 실패 시 계속 진행."""
            print(f'\n{label} ({target_id})...')
            for i, msg in enumerate(messages):
                try:
                    results = send_telegram_long(msg, TELEGRAM_BOT_TOKEN, target_id)
                    codes = [str(r.status_code) for r in results]
                    print(f'  {msg_labels[i]}: {", ".join(codes)}')
                except Exception as e:
                    print(f'  {msg_labels[i]}: 전송 실패 ({type(e).__name__}: {str(e)[:100]}) — 다음 메시지 계속')

        if cold_start:
            target = PRIVATE_CHAT_ID or TELEGRAM_CHAT_ID
            _send_batch(target, '콜드 스타트 — 개인봇 전송')
        else:
            _send_batch(TELEGRAM_CHAT_ID, '채널 전송')
            if PRIVATE_CHAT_ID and PRIVATE_CHAT_ID != TELEGRAM_CHAT_ID:
                _send_batch(PRIVATE_CHAT_ID, '개인봇 전송')

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
