"""고속 과거 ranking 생성기 v2 — 전면 최적화

핵심 최적화:
  1. Growth 팩터 사전계산: 분기 변경 시점만 계산, 날짜별 lookup (2-3초/일 → 0초/일)
  2. Market cap/fundamental 일괄 로드: per-day parquet read 제거 (0.5-1초/일 → 0초/일)
  3. 모멘텀/MA120 벡터화: per-ticker 루프 → numpy 행렬 연산 (0.3초/일 → 0.02초/일)
  4. Strategy에 fs_dict 주입: disk I/O 완전 제거

속도: ~4-5초/일 → ~0.3-0.5초/일 (10-15배 향상)
1,277일 기준: ~1.5시간 → ~8-10분

Usage:
    python backtest/fast_generate_rankings_v2.py 20210104 20251230
    python backtest/fast_generate_rankings_v2.py 20210104 20251230 --state-dir state/bt_2021
    python backtest/fast_generate_rankings_v2.py 20210104 20251230 --resume
"""
import json
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

from scipy import stats as scipy_stats
from scipy.stats import norm

CACHE_DIR = PROJECT_ROOT / 'data_cache'


# ============================================================================
# 1. 사전계산: Growth 팩터 (핵심 최적화)
# ============================================================================

def precompute_growth_factors(fs_dict, trading_dates):
    """모든 종목 × 모든 분기변경 시점의 growth 팩터 사전계산

    핵심 아이디어: growth 팩터는 새 분기 공시가 나올 때만 변한다.
    1,277일 × 200종목 = 255,400회 계산 → ~1,500종목 × ~30 분기변경 = ~45,000회로 축소

    Returns:
        growth_lookup: dict[date_str] → dict[ticker] → {'rev_yoy': float, 'oca': float}
        각 날짜에 대해 해당 시점에서 사용 가능한 최신 growth 값
    """
    print('  Growth 팩터 사전계산 중...')
    t0 = time.time()

    # 모든 종목의 분기 데이터를 날짜별 유효 값으로 변환
    # ticker → list of (effective_date, rev_yoy, oca)
    ticker_growth_events = {}

    use_rev_accel = fs_dict.get('__use_rev_accel__', False)
    use_gross_profit = fs_dict.get('__use_gross_profit__', False)
    rev_account = '매출총이익' if use_gross_profit else '매출액'

    for ticker, fs_df in fs_dict.items():
        if ticker.startswith('__'):
            continue
        events = _compute_ticker_growth_events(ticker, fs_df, rev_account=rev_account)
        if events and use_rev_accel:
            # oca 자리에 rev_accel(매출성장률 가속도) 넣기
            prev_rev = None
            new_events = []
            for eff_date, rev_yoy, oca in events:
                if rev_yoy is not None and prev_rev is not None:
                    rev_accel = rev_yoy - prev_rev
                else:
                    rev_accel = None
                if rev_yoy is not None:
                    prev_rev = rev_yoy
                new_events.append((eff_date, rev_yoy, rev_accel))
            events = new_events
        if events:
            ticker_growth_events[ticker] = events

    # 거래일 목록을 정렬
    sorted_dates = sorted(trading_dates)

    # 각 날짜에 대해 유효한 growth 값 lookup 테이블 구축
    # 최적화: 이전 날짜의 결과를 재사용 (변경분만 업데이트)
    growth_lookup = {}
    current_values = {}  # ticker → {'rev_yoy': float, 'oca': float}

    # 각 종목의 이벤트를 deque 형태로 (sorted, pop from front)
    ticker_event_iters = {}
    for ticker, events in ticker_growth_events.items():
        # events는 이미 effective_date 순 정렬
        ticker_event_iters[ticker] = iter(events)

    # 각 종목의 "다음 이벤트"를 peek
    next_events = {}
    for ticker, it in ticker_event_iters.items():
        try:
            next_events[ticker] = next(it)
        except StopIteration:
            pass

    for date_str in sorted_dates:
        date_ts = pd.Timestamp(date_str)

        # 이 날짜까지 유효한 이벤트 적용
        tickers_to_remove = []
        for ticker in list(next_events.keys()):
            while ticker in next_events:
                eff_date, rev_yoy, oca = next_events[ticker]
                if eff_date <= date_ts:
                    current_values[ticker] = {'rev_yoy': rev_yoy, 'oca': oca}
                    try:
                        next_events[ticker] = next(ticker_event_iters[ticker])
                    except StopIteration:
                        del next_events[ticker]
                else:
                    break

        # 현재 시점의 스냅샷 저장 (shallow copy — 값은 immutable dict)
        growth_lookup[date_str] = dict(current_values)

    elapsed = time.time() - t0
    print(f'    {len(ticker_growth_events)}종목, {len(growth_lookup)}일 → {elapsed:.1f}초')
    return growth_lookup


def _compute_ticker_growth_events(ticker, fs_df, rev_account='매출액'):
    """단일 종목의 growth 팩터 변경 이벤트 목록 — 최적화 버전

    dict lookup으로 DataFrame 연산 최소화
    rev_account: '매출액' (기본) 또는 '매출총이익' (gross profit)
    """
    from datetime import timedelta

    events = []
    q_mask = fs_df['공시구분'] == 'q'
    y_mask = fs_df['공시구분'] == 'y'
    has_rcept = 'rcept_dt' in fs_df.columns

    if not q_mask.any() and not y_mask.any():
        return events

    if q_mask.any():
        q_data = fs_df[q_mask]
        # 사전 인덱싱: {(기준일, 계정) → 값}, {기준일 → rcept_dt}
        q_vals = {}
        q_rcept = {}
        for row in q_data.itertuples(index=False):
            key = (row.기준일, row.계정)
            if key not in q_vals and pd.notna(row.값):
                q_vals[key] = row.값
            if has_rcept and row.기준일 not in q_rcept and hasattr(row, 'rcept_dt') and pd.notna(row.rcept_dt):
                q_rcept[row.기준일] = row.rcept_dt

        q_dates = sorted(set(d for d, _ in q_vals.keys()))

        # 연간 데이터 (폴백용)
        y_rev = {}  # 기준일 → 매출액
        y_rcept_map = {}
        if y_mask.any():
            for row in fs_df[y_mask].itertuples(index=False):
                if row.계정 == rev_account and pd.notna(row.값):
                    y_rev[row.기준일] = row.값
                if has_rcept and row.기준일 not in y_rcept_map and hasattr(row, 'rcept_dt') and pd.notna(row.rcept_dt):
                    y_rcept_map[row.기준일] = row.rcept_dt

        for qi, qd in enumerate(q_dates):
            # effective date
            if qd in q_rcept:
                eff_date = q_rcept[qd]
                if isinstance(eff_date, str):
                    eff_date = pd.Timestamp(eff_date)
            else:
                eff_date = qd + timedelta(days=90)

            avail_dates = sorted(q_dates[:qi+1], reverse=True)
            rev_yoy = None
            oca = None

            # TTM 매출 YoY (dict lookup)
            if len(avail_dates) >= 8:
                recent_4 = avail_dates[:4]
                prev_4 = avail_dates[4:8]
                r4 = sum(q_vals.get((d, rev_account), 0) for d in recent_4)
                p4 = sum(q_vals.get((d, rev_account), 0) for d in prev_4)
                if p4 > 0:
                    rev_yoy = (r4 / p4 - 1) * 100

                # op_change_asset
                op_r = sum(q_vals.get((d, '영업이익'), 0) for d in recent_4)
                op_p = sum(q_vals.get((d, '영업이익'), 0) for d in prev_4)
                # 직전 4분기 중 가장 최근 자산
                prev_asset = None
                for d in sorted(prev_4):  # 오래된→최신 순
                    a = q_vals.get((d, '자산'))
                    if a is not None:
                        prev_asset = a
                if prev_asset and prev_asset > 0:
                    oca = (op_r - op_p) / prev_asset * 100

            # 연간 폴백 for rev_yoy
            if rev_yoy is None and y_rev:
                sorted_y = sorted([d for d in y_rev.keys() if d <= qd])
                if len(sorted_y) >= 2:
                    latest = y_rev[sorted_y[-1]]
                    prev = y_rev[sorted_y[-2]]
                    if prev > 0:
                        rev_yoy = (latest / prev - 1) * 100

            if rev_yoy is not None or oca is not None:
                events.append((eff_date, rev_yoy, oca))

    elif y_mask.any():
        y_vals = {}
        y_rcept = {}
        for row in fs_df[y_mask].itertuples(index=False):
            if row.계정 == rev_account and pd.notna(row.값):
                y_vals[row.기준일] = row.값
            if has_rcept and row.기준일 not in y_rcept and hasattr(row, 'rcept_dt') and pd.notna(row.rcept_dt):
                y_rcept[row.기준일] = row.rcept_dt

        y_dates = sorted(y_vals.keys())
        for yi, yd in enumerate(y_dates):
            if yd in y_rcept:
                eff_date = y_rcept[yd]
                if isinstance(eff_date, str):
                    eff_date = pd.Timestamp(eff_date)
            else:
                eff_date = yd + timedelta(days=90)

            if yi >= 1:
                latest = y_vals[yd]
                prev = y_vals[y_dates[yi - 1]]
                if prev > 0:
                    rev_yoy = (latest / prev - 1) * 100
                    events.append((eff_date, rev_yoy, None))

    events.sort(key=lambda x: x[0])
    return events


# ============================================================================
# 1b. 사전계산: TTM 재무제표 (extract_magic_formula_data 대체)
# ============================================================================

# 손익계산서/현금흐름표 항목 (4분기 합산 대상)
_FLOW_ACCOUNTS = [
    '당기순이익', '법인세비용', '세전계속사업이익',
    '매출액', '매출총이익', '영업이익',
    '영업활동으로인한현금흐름', '감가상각비',
    '지배주주당기순이익',
]
# 재무상태표 항목 (최근 분기 값)
_STOCK_ACCOUNTS = [
    '자산', '부채', '유동부채', '유동자산', '비유동자산',
    '현금및현금성자산', '자본',
    '지배주주자본',
]
# 계정명 매핑
_ACCOUNT_MAPPING = {
    '당기순이익': '당기순이익', '세전계속사업이익': '세전계속사업이익',
    '법인세비용': '법인세비용', '자산': '자산', '부채': '총부채',
    '유동부채': '유동부채', '유동자산': '유동자산', '비유동자산': '비유동자산',
    '현금및현금성자산': '현금', '감가상각비': '감가상각비', '자본': '자본',
    '매출액': '매출액', '매출총이익': '매출총이익',
    '영업활동으로인한현금흐름': '영업현금흐름', '영업이익': '영업이익',
    '지배주주당기순이익': '지배주주당기순이익', '지배주주자본': '지배주주자본',
}


def precompute_ttm_fundamentals(fs_dict, trading_dates):
    """모든 종목의 TTM 재무제표를 사전계산

    핵심 아이디어: TTM 계산은 새 분기 공시가 나올 때만 변함.
    종목별 "이벤트" (새 분기/연간 데이터가 유효해지는 시점)마다 TTM 계산,
    각 거래일에는 가장 최근 유효한 TTM 결과를 lookup.

    Returns:
        ttm_lookup: dict[date_str] → dict[ticker] → dict[account → value]
    """
    print('  TTM 재무제표 사전계산 중...')
    t0 = time.time()

    # 각 종목의 TTM 이벤트 계산
    ticker_events = {}  # ticker → list of (eff_date, ttm_dict)
    for ticker, fs_df in fs_dict.items():
        events = _compute_ticker_ttm_events(ticker, fs_df)
        if events:
            ticker_events[ticker] = events

    # 날짜별 lookup 구축 (growth_lookup과 동일 패턴)
    sorted_dates = sorted(trading_dates)
    ttm_lookup = {}
    current_values = {}  # ticker → ttm_dict

    ticker_event_iters = {}
    for ticker, events in ticker_events.items():
        ticker_event_iters[ticker] = iter(events)

    next_events = {}
    for ticker, it in ticker_event_iters.items():
        try:
            next_events[ticker] = next(it)
        except StopIteration:
            pass

    for date_str in sorted_dates:
        date_ts = pd.Timestamp(date_str)

        for ticker in list(next_events.keys()):
            while ticker in next_events:
                eff_date, ttm_dict = next_events[ticker]
                if eff_date <= date_ts:
                    current_values[ticker] = ttm_dict
                    try:
                        next_events[ticker] = next(ticker_event_iters[ticker])
                    except StopIteration:
                        del next_events[ticker]
                else:
                    break

        ttm_lookup[date_str] = dict(current_values)

    elapsed = time.time() - t0
    print(f'    {len(ticker_events)}종목, {len(ttm_lookup)}일 → {elapsed:.1f}초')
    return ttm_lookup


def _compute_ticker_ttm_events(ticker, fs_df):
    """단일 종목의 TTM 재무제표 변경 이벤트 목록 — 최적화 버전

    DataFrame 연산 최소화: 데이터를 dict 구조로 변환 후 순수 Python으로 처리
    """
    from datetime import timedelta

    events = []
    q_mask = fs_df['공시구분'] == 'q'
    y_mask = fs_df['공시구분'] == 'y'

    if not q_mask.any() and not y_mask.any():
        return events

    base_weights = [1.6, 1.2, 0.8, 0.4]
    has_rcept = 'rcept_dt' in fs_df.columns

    if q_mask.any():
        q_data = fs_df[q_mask]
        # 전체 분기 데이터를 dict로 사전 변환: {(기준일, 계정) → 값}
        q_vals = {}      # (기준일, 계정) → 값
        q_rcept = {}     # 기준일 → rcept_dt (첫 번째)
        for row in q_data.itertuples(index=False):
            key = (row.기준일, row.계정)
            if key not in q_vals and pd.notna(row.값):
                q_vals[key] = row.값
            if has_rcept and row.기준일 not in q_rcept and hasattr(row, 'rcept_dt') and pd.notna(row.rcept_dt):
                q_rcept[row.기준일] = row.rcept_dt

        q_dates = sorted(set(d for d, _ in q_vals.keys()))

        for qi, qd in enumerate(q_dates):
            # effective date
            if qd in q_rcept:
                eff_date = q_rcept[qd]
                if isinstance(eff_date, str):
                    eff_date = pd.Timestamp(eff_date)
            else:
                eff_date = qd + timedelta(days=45)

            # 최근 4분기 (이 qd 포함, 역순)
            avail_dates = [d for d in q_dates[:qi+1]]
            avail_dates.sort(reverse=True)
            recent_dates = avail_dates[:4]
            n_quarters = len(recent_dates)
            latest_date = recent_dates[0]

            # 가중치
            raw_w = base_weights[:n_quarters]
            scale = 4.0 / sum(raw_w)
            weight_map = {d: raw_w[i] * scale for i, d in enumerate(recent_dates)}

            ttm_dict = {'종목코드': ticker, '기준일': latest_date}
            recent_set = set(recent_dates)

            # 손익계산서 가중 합산 (순수 dict lookup)
            for acct in _FLOW_ACCOUNTS:
                weighted_sum = 0.0
                found = False
                for d in recent_dates:
                    v = q_vals.get((d, acct))
                    if v is not None:
                        weighted_sum += v * weight_map[d]
                        found = True
                if found:
                    ttm_dict[_ACCOUNT_MAPPING.get(acct, acct)] = weighted_sum

            # 재무상태표: 최근 분기 값
            for acct in _STOCK_ACCOUNTS:
                v = q_vals.get((latest_date, acct))
                if v is None:
                    # 폴백: 직전 분기
                    for d in recent_dates[1:]:
                        v = q_vals.get((d, acct))
                        if v is not None:
                            break
                if v is not None:
                    ttm_dict[_ACCOUNT_MAPPING.get(acct, acct)] = v

            if len(ttm_dict) > 2:
                events.append((eff_date, ttm_dict))

    elif y_mask.any():
        y_data = fs_df[y_mask]
        y_vals = {}  # (기준일, 계정) → 값
        y_rcept = {}
        for row in y_data.itertuples(index=False):
            key = (row.기준일, row.계정)
            if key not in y_vals and pd.notna(row.값):
                y_vals[key] = row.값
            if has_rcept and row.기준일 not in y_rcept and hasattr(row, 'rcept_dt') and pd.notna(row.rcept_dt):
                y_rcept[row.기준일] = row.rcept_dt

        y_dates = sorted(set(d for d, _ in y_vals.keys()))
        for yd in y_dates:
            if yd in y_rcept:
                eff_date = y_rcept[yd]
                if isinstance(eff_date, str):
                    eff_date = pd.Timestamp(eff_date)
            else:
                eff_date = yd + timedelta(days=90)

            ttm_dict = {'종목코드': ticker, '기준일': yd}
            all_accounts = _FLOW_ACCOUNTS + _STOCK_ACCOUNTS
            for acct in all_accounts:
                v = y_vals.get((yd, acct))
                if v is not None:
                    ttm_dict[_ACCOUNT_MAPPING.get(acct, acct)] = v

            if len(ttm_dict) > 2:
                events.append((eff_date, ttm_dict))

    events.sort(key=lambda x: x[0])
    return events


def ttm_lookup_to_dataframe(ttm_for_date, universe_tickers):
    """ttm_lookup의 단일 날짜 결과 → extract_magic_formula_data 호환 DataFrame

    Returns:
        DataFrame with columns: 종목코드, 기준일, 당기순이익, 자산, ...
    """
    rows = []
    for ticker in universe_tickers:
        if ticker in ttm_for_date:
            rows.append(ttm_for_date[ticker])
    if not rows:
        return pd.DataFrame()

    result_df = pd.DataFrame(rows)

    # 필요 컬럼만 선택 (extract_magic_formula_data 출력과 동일)
    available_cols = ['종목코드']
    if '기준일' in result_df.columns:
        available_cols.append('기준일')
    for simple_name in _ACCOUNT_MAPPING.values():
        if simple_name in result_df.columns and simple_name not in available_cols:
            available_cols.append(simple_name)

    result_df = result_df[[c for c in available_cols if c in result_df.columns]]
    return result_df


# ============================================================================
# 2. 일괄 로드 + 인덱싱
# ============================================================================

def preload_all_data(start_str, end_str, trading_dates=None, use_rev_accel=False, use_gross_profit=False):
    """모든 데이터 1회 로드 — v2: 모든 parquet를 메모리에"""
    print('=== 데이터 프리로드 (v2) ===')
    t0 = time.time()
    data = {}

    # 1. OHLCV
    ohlcv_files = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'))
    ohlcv_files.sort(key=lambda f: f.stem.split('_')[2])
    ohlcv_file = ohlcv_files[0]
    print(f'  OHLCV: {ohlcv_file.name}')
    data['ohlcv'] = pd.read_parquet(ohlcv_file).replace(0, np.nan)
    print(f'    {data["ohlcv"].shape[0]}거래일 × {data["ohlcv"].shape[1]}종목 (0→NaN 변환 완료)')

    # 2. Market cap — 전부 메모리에 (핵심: per-day read 제거)
    print('  Market cap 일괄 로드 중...')
    t_mc = time.time()
    data['market_cap'] = {}
    mc_files = sorted(CACHE_DIR.glob('market_cap_ALL_*.parquet'))
    for f in mc_files:
        d = f.stem.split('_')[-1]
        if d <= end_str:
            data['market_cap'][d] = pd.read_parquet(f)
    print(f'    {len(data["market_cap"])}일 로드 ({time.time()-t_mc:.1f}초)')

    # 3. Fundamentals (pykrx PER/PBR)
    print('  Fundamentals 일괄 로드 중...')
    t_fn = time.time()
    data['fundamentals_pykrx'] = {}
    for f in sorted(CACHE_DIR.glob('fundamental_batch_ALL_*.parquet')):
        d = f.stem.split('_')[-1]
        if d <= end_str:
            data['fundamentals_pykrx'][d] = pd.read_parquet(f)
    print(f'    {len(data["fundamentals_pykrx"])}일 로드 ({time.time()-t_fn:.1f}초)')

    # 4. Sectors
    data['sectors'] = {}
    for f in sorted(CACHE_DIR.glob('krx_sector_*.parquet')):
        d = f.stem.split('_')[-1]
        if d <= end_str:
            data['sectors'][d] = f  # lazy load (infrequent, ~quarterly)

    print(f'  sectors: {len(data["sectors"])}일')

    # 5. 재무제표 (DART + FnGuide mismatch 체크)
    from create_current_portfolio import _check_data_mismatch
    print('  재무제표 로드 중...')
    data['fs'] = {}
    dart_count = fn_count = mismatch_swap = 0

    dart_map = {}
    for f in CACHE_DIR.glob('fs_dart_*.parquet'):
        ticker = f.stem.replace('fs_dart_', '')
        try:
            df = pd.read_parquet(f)
            if not df.empty:
                dart_map[ticker] = df
        except Exception:
            pass

    fn_map = {}
    for f in CACHE_DIR.glob('fs_fnguide_*.parquet'):
        ticker = f.stem.replace('fs_fnguide_', '')
        try:
            df = pd.read_parquet(f)
            if not df.empty:
                fn_map[ticker] = df
        except Exception:
            pass

    all_tickers = set(dart_map) | set(fn_map)
    for ticker in all_tickers:
        if ticker in dart_map:
            if ticker in fn_map and _check_data_mismatch(dart_map[ticker], fn_map[ticker]):
                data['fs'][ticker] = fn_map[ticker]
                fn_count += 1
                mismatch_swap += 1
            else:
                data['fs'][ticker] = dart_map[ticker]
                dart_count += 1
        elif ticker in fn_map:
            data['fs'][ticker] = fn_map[ticker]
            fn_count += 1

    swap_msg = f', 불일치→FnGuide {mismatch_swap}' if mismatch_swap else ''
    print(f'    {len(data["fs"])}종목 (DART {dart_count} + FnGuide {fn_count}{swap_msg})')

    # 6. Growth 팩터 사전계산
    fs_for_growth = dict(data['fs'])
    if use_rev_accel:
        fs_for_growth['__use_rev_accel__'] = True
    if use_gross_profit:
        fs_for_growth['__use_gross_profit__'] = True
    if trading_dates:
        data['growth_lookup'] = precompute_growth_factors(fs_for_growth, trading_dates)
    else:
        data['growth_lookup'] = {}

    # 6b. TTM 재무제표 사전계산
    if trading_dates:
        data['ttm_lookup'] = precompute_ttm_fundamentals(data['fs'], trading_dates)
    else:
        data['ttm_lookup'] = {}

    # 7. 종목명 캐시
    print('  종목명 빌드...')
    data['ticker_names'] = {}
    names_cache = CACHE_DIR / 'ticker_names_cache.json'
    if names_cache.exists():
        with open(names_cache, 'r', encoding='utf-8') as f:
            data['ticker_names'] = json.load(f)
        print(f'    캐시에서 {len(data["ticker_names"])}종목 로드')
    else:
        try:
            latest_mcap_dates = sorted(data['market_cap'].keys())
            if latest_mcap_dates:
                latest_mcap = data['market_cap'][latest_mcap_dates[-1]]
                from pykrx import stock as pykrx_stock
                for ticker in latest_mcap.index[:3000]:
                    try:
                        name = pykrx_stock.get_market_ticker_name(ticker)
                        if name:
                            data['ticker_names'][ticker] = name
                    except Exception:
                        pass
                print(f'    pykrx에서 {len(data["ticker_names"])}종목 매핑')
        except Exception as e:
            print(f'    종목명 매핑 실패: {e}')

    # 8. 거래대금 20일 평균 사전계산
    print('  거래대금 20일 평균 사전계산 중...')
    t_vol = time.time()
    data['avg_volume'] = precompute_avg_volume(data['market_cap'])
    print(f'    {len(data["avg_volume"])}일 ({time.time()-t_vol:.1f}초)')

    elapsed = time.time() - t0
    print(f'  프리로드 완료: {elapsed:.1f}초')
    return data


def precompute_avg_volume(market_cap_dict):
    """거래대금 20일 이동평균 사전계산 — 최적화 버전

    1단계: 모든 날짜의 거래대금을 하나의 DataFrame으로 합침
    2단계: rolling(20).mean() 으로 한방에 계산
    """
    sorted_dates = sorted(market_cap_dict.keys())

    # 전체 거래대금을 하나의 DataFrame으로 (날짜 x 종목)
    vol_series_list = []
    valid_dates = []
    for d in sorted_dates:
        mcap_df = market_cap_dict[d]
        if '거래대금' in mcap_df.columns:
            vol_series_list.append(mcap_df['거래대금'])
            valid_dates.append(d)

    if not vol_series_list:
        return {}

    # DataFrame: rows=dates, cols=tickers
    vol_df = pd.DataFrame(vol_series_list, index=valid_dates)

    # rolling 20일 평균 (한방 계산)
    avg_df = vol_df.rolling(window=20, min_periods=1).mean() / 1e8

    # dict 변환
    avg_vol = {}
    for d in valid_dates:
        avg_vol[d] = avg_df.loc[d]

    return avg_vol


# ============================================================================
# 3. 벡터화된 팩터 계산
# ============================================================================

def vectorized_ma120_filter(price_df, universe_tickers, base_ts):
    """MA120 필터 — 벡터화 (per-ticker 루프 제거)"""
    valid = [t for t in universe_tickers if t in price_df.columns]
    if not valid:
        return [], []

    # 마지막 120일 가격
    prices_slice = price_df[valid].iloc[-120:]
    if len(prices_slice) < 120:
        return valid, []

    # 현재가 (마지막 행)
    current = prices_slice.iloc[-1]
    # MA120
    ma120 = prices_slice.mean()
    # 필터: 현재가 >= MA120 (원본 코드는 current >= ma120, buffer 없음)
    mask = current >= ma120
    # NaN 처리: 가격 없는 종목 제외
    mask = mask.fillna(False)

    passed = mask[mask].index.tolist()
    failed = mask[~mask].index.tolist()
    return passed, failed


def vectorized_momentum(price_df, tickers, mom_period='6m'):
    """모멘텀 + K_ratio 벡터화 계산

    Returns:
        mom_dict: ticker → momentum_score
        kratio_dict: ticker → k_ratio
    """
    LOOKBACK_6M = 126
    LOOKBACK_12M = 252
    LOOKBACK_1M = 21
    VOL_FLOOR = 15.0

    if mom_period in ('12m', '12m-1m'):
        min_required = LOOKBACK_12M + 1
    else:
        min_required = LOOKBACK_6M + 1

    if price_df is None or price_df.empty or len(price_df) < min_required:
        return {}, {}

    valid = [t for t in tickers if t in price_df.columns]
    if not valid:
        return {}, {}

    prices = price_df[valid]

    # 모멘텀 계산 (벡터화)
    mom_dict = {}
    if mom_period == '6m':
        current = prices.iloc[-1]
        start = prices.iloc[-(LOOKBACK_6M + 1)]
        valid_mask = (start > 0) & start.notna() & current.notna()
        ret = (current / start - 1) * 100
        daily_rets = prices.iloc[-(LOOKBACK_6M + 1):].pct_change().iloc[1:]
        annual_vol = daily_rets.std() * np.sqrt(252) * 100
        annual_vol = annual_vol.clip(lower=VOL_FLOOR)
        momentum = ret / annual_vol
        momentum = momentum.where(valid_mask)
        mom_dict = momentum.dropna().to_dict()

    elif mom_period == '6m-1m':
        start = prices.iloc[-(LOOKBACK_6M + 1)]
        end_1m = prices.iloc[-(LOOKBACK_1M + 1)]
        valid_mask = (start > 0) & (end_1m > 0) & start.notna() & end_1m.notna()
        ret = (end_1m / start - 1) * 100
        daily_rets = prices.iloc[-(LOOKBACK_6M + 1):-(LOOKBACK_1M)].pct_change().iloc[1:]
        annual_vol = daily_rets.std() * np.sqrt(252) * 100
        annual_vol = annual_vol.clip(lower=VOL_FLOOR)
        momentum = ret / annual_vol
        momentum = momentum.where(valid_mask)
        mom_dict = momentum.dropna().to_dict()

    elif mom_period == '12m-1m':
        if len(prices) >= LOOKBACK_12M + 1:
            start = prices.iloc[-(LOOKBACK_12M + 1)]
            end_1m = prices.iloc[-(LOOKBACK_1M + 1)]
            valid_mask = (start > 0) & (end_1m > 0) & start.notna() & end_1m.notna()
            ret = (end_1m / start - 1) * 100
            daily_rets = prices.iloc[-(LOOKBACK_12M + 1):-(LOOKBACK_1M)].pct_change().iloc[1:]
            annual_vol = daily_rets.std() * np.sqrt(252) * 100
            annual_vol = annual_vol.clip(lower=VOL_FLOOR)
            momentum = ret / annual_vol
            momentum = momentum.where(valid_mask)
            mom_dict = momentum.dropna().to_dict()

    elif mom_period == '12m':
        if len(prices) >= LOOKBACK_12M + 1:
            current = prices.iloc[-1]
            start = prices.iloc[-(LOOKBACK_12M + 1)]
            valid_mask = (start > 0) & start.notna() & current.notna()
            ret = (current / start - 1) * 100
            daily_rets = prices.iloc[-(LOOKBACK_12M + 1):].pct_change().iloc[1:]
            annual_vol = daily_rets.std() * np.sqrt(252) * 100
            annual_vol = annual_vol.clip(lower=VOL_FLOOR)
            momentum = ret / annual_vol
            momentum = momentum.where(valid_mask)
            mom_dict = momentum.dropna().to_dict()

    # K_ratio 계산 (벡터화)
    kr_slice = prices.iloc[-(LOOKBACK_6M + 1):]
    # log prices, handle zeros/negatives
    kr_valid = kr_slice.where(kr_slice > 0)
    log_prices = np.log(kr_valid)

    kratio_dict = {}
    # K_ratio requires linregress per-ticker (slope/stderr), but we can batch:
    x = np.arange(len(kr_slice))
    for t in valid:
        lp = log_prices[t].dropna()
        if len(lp) < LOOKBACK_6M:
            continue
        lp_vals = lp.iloc[-LOOKBACK_6M:].values
        try:
            slope, _, _, _, std_err = scipy_stats.linregress(x[:len(lp_vals)], lp_vals)
            if std_err > 0:
                kratio_dict[t] = slope / std_err
        except (ValueError, IndexError):
            continue

    return mom_dict, kratio_dict


def vectorized_correlation(price_df, top30_tickers, n_days=60):
    """상관관계 계산 — 벡터화"""
    valid = [t for t in top30_tickers if t in price_df.columns]
    if len(valid) < 2 or len(price_df) < 20:
        return {}

    rets = price_df[valid].tail(n_days).pct_change().dropna()
    if len(rets) < 20:
        return {}

    corr_matrix = rets.corr()
    corr_60d = {}
    for ci in range(len(valid)):
        for cj in range(ci + 1, len(valid)):
            t1, t2 = valid[ci], valid[cj]
            c = corr_matrix.iloc[ci, cj]
            if not pd.isna(c):
                key = '_'.join(sorted([t1, t2]))
                corr_60d[key] = round(float(c), 3)
    return corr_60d


# ============================================================================
# 4. 최적화된 멀티팩터 점수 계산 (strategy_b 인라인)
# ============================================================================

def rank_zscore_series(series, ascending=True):
    """Rank-based z-score (Blom 변환) — 전체 유니버스"""
    valid = series.dropna()
    if len(valid) < 5:
        return pd.Series(np.nan, index=series.index)
    result = pd.Series(np.nan, index=series.index)
    valid_mask = series.notna()
    n = valid_mask.sum()
    ranks = series[valid_mask].rank(ascending=ascending, method='average')
    uniform = (ranks - 0.375) / (n + 0.25)
    uniform = uniform.clip(0.001, 0.999)
    result[valid_mask] = norm.ppf(uniform)
    return result


def rank_zscore_sector(series, sectors, ascending=True, min_sector=10):
    """Rank-based z-score with sector neutralization"""
    valid_mask = series.notna()
    if valid_mask.sum() < 5:
        return pd.Series(np.nan, index=series.index)

    result = pd.Series(np.nan, index=series.index)

    # 전체 유니버스 z-score (소형 섹터 fallback용)
    full_z = rank_zscore_series(series, ascending)

    for sector_name in sectors[valid_mask].unique():
        sector_mask = (sectors == sector_name) & valid_mask
        count = sector_mask.sum()

        if count >= min_sector:
            n = count
            ranks = series[sector_mask].rank(ascending=ascending, method='average')
            uniform = (ranks - 0.375) / (n + 0.25)
            uniform = uniform.clip(0.001, 0.999)
            result[sector_mask] = norm.ppf(uniform)
        else:
            result[sector_mask] = full_z[sector_mask]

    return result


def calculate_multifactor_fast(multifactor_df, price_df, sector_map, base_date,
                                growth_lookup, mom_period='6m'):
    """인라인 멀티팩터 계산 — disk I/O 없음

    strategy_b_multifactor.py의 calculate_multifactor_score를 인라인화하되,
    growth 팩터는 사전계산된 lookup에서 조회, 모멘텀은 벡터화.
    """
    data = multifactor_df.copy()

    # --- Value 팩터 ---
    if 'pykrx_PER' in data.columns:
        data['PER'] = data['pykrx_PER'].where(data['pykrx_PER'] > 0, np.nan)
    else:
        data['PER'] = np.nan

    if 'pykrx_PBR' in data.columns:
        data['PBR'] = data['pykrx_PBR'].where(data['pykrx_PBR'] > 0, np.nan)
    else:
        data['PBR'] = np.nan

    if '영업현금흐름' in data.columns and '시가총액' in data.columns:
        data['PCR'] = np.where(data['영업현금흐름'] > 0, data['시가총액'] / data['영업현금흐름'], np.nan)

    if '매출액' in data.columns and '시가총액' in data.columns:
        data['PSR'] = np.where(data['매출액'] > 0, data['시가총액'] / data['매출액'], np.nan)

    # --- Quality 팩터 ---
    if 'pykrx_EPS' in data.columns and 'pykrx_BPS' in data.columns:
        data['ROE'] = np.where(data['pykrx_BPS'] > 0, data['pykrx_EPS'] / data['pykrx_BPS'] * 100, np.nan)
    else:
        data['ROE'] = np.nan

    if '매출총이익' in data.columns and '자산' in data.columns:
        data['GPA'] = data['매출총이익'] / data['자산'] * 100

    if '영업현금흐름' in data.columns and '자산' in data.columns:
        data['CFO'] = data['영업현금흐름'] / data['자산'] * 100

    # --- Growth 팩터 (사전계산 lookup에서 조회!) ---
    date_growth = growth_lookup.get(base_date, {})
    data['매출성장률'] = data['종목코드'].map(
        lambda t: date_growth.get(t, {}).get('rev_yoy') if t in date_growth else np.nan
    )
    data['이익변화량'] = data['종목코드'].map(
        lambda t: date_growth.get(t, {}).get('oca') if t in date_growth else np.nan
    )

    # --- Momentum 팩터 (벡터화) ---
    tickers = data['종목코드'].tolist()
    mom_dict, kratio_dict = vectorized_momentum(price_df, tickers, mom_period)
    data['모멘텀'] = data['종목코드'].map(mom_dict)
    data['K_ratio'] = data['종목코드'].map(kratio_dict)

    # --- 섹터 매핑 ---
    sectors = None
    if sector_map:
        data['섹터'] = data['종목코드'].map(sector_map).fillna('기타')
        sectors = data['섹터']

    # --- PER/PBR 이상치 처리 ---
    for col in ['PER', 'PBR', 'PCR', 'PSR']:
        if col in data.columns:
            data.loc[data[col] <= 0, col] = np.nan

    # PER > 200 제외
    if 'PER' in data.columns:
        extreme_per_mask = data['PER'] > 200
        if extreme_per_mask.any():
            data = data[~extreme_per_mask].copy()

    # --- Rank z-score ---
    value_zs = []
    for col in ['PER', 'PBR', 'PCR', 'PSR']:
        if col in data.columns:
            data[f'{col}_z'] = rank_zscore_series(data[col], ascending=False)
            value_zs.append(f'{col}_z')

    quality_zs = []
    for col in ['ROE', 'GPA', 'CFO']:
        if col in data.columns and data[col].notna().sum() > 0:
            data[f'{col}_z'] = rank_zscore_series(data[col], ascending=True)
            quality_zs.append(f'{col}_z')

    growth_zs = []
    if '매출성장률' in data.columns and data['매출성장률'].notna().sum() > 0:
        data['매출성장률_z'] = rank_zscore_series(data['매출성장률'], ascending=True)
        growth_zs.append('매출성장률_z')
    if '이익변화량' in data.columns and data['이익변화량'].notna().sum() > 0:
        data['이익변화량_z'] = rank_zscore_series(data['이익변화량'], ascending=True)
        growth_zs.append('이익변화량_z')

    momentum_zs = []
    # 섹터 중립 z-score: data['섹터'] 직접 사용 (필터 후에도 index 정합)
    cur_sectors = data['섹터'] if '섹터' in data.columns and sector_map else None
    if '모멘텀' in data.columns and data['모멘텀'].notna().sum() > 0:
        data['모멘텀_z'] = rank_zscore_sector(data['모멘텀'], cur_sectors, ascending=True) if cur_sectors is not None else rank_zscore_series(data['모멘텀'], ascending=True)
        momentum_zs.append('모멘텀_z')
    if 'K_ratio' in data.columns and data['K_ratio'].notna().sum() > 0:
        data['K_ratio_z'] = rank_zscore_sector(data['K_ratio'], cur_sectors, ascending=True) if cur_sectors is not None else rank_zscore_series(data['K_ratio'], ascending=True)
        momentum_zs.append('K_ratio_z')

    # Growth NaN 대체
    if '이익변화량_z' in growth_zs and '매출성장률_z' in growth_zs:
        oca_nan = data['이익변화량_z'].isna()
        data.loc[oca_nan, '이익변화량_z'] = data.loc[oca_nan, '매출성장률_z']

    # NaN → 0
    for zs in [value_zs, quality_zs, growth_zs, momentum_zs]:
        for col in zs:
            data[col] = data[col].fillna(0.0)

    # 카테고리 평균
    data['밸류_raw'] = data[value_zs].mean(axis=1) if value_zs else 0
    data['퀄리티_raw'] = data[quality_zs].mean(axis=1) if quality_zs else 0

    # Growth 가중
    if len(growth_zs) == 2 and '매출성장률_z' in growth_zs and '이익변화량_z' in growth_zs:
        g_rev_w = float(os.environ.get('G_REVENUE_WEIGHT', '0.7'))
        data['성장_raw'] = data['매출성장률_z'] * g_rev_w + data['이익변화량_z'] * (1.0 - g_rev_w)
    else:
        data['성장_raw'] = data[growth_zs].mean(axis=1) if growth_zs else 0

    data['모멘텀_raw'] = data[momentum_zs].mean(axis=1) if momentum_zs else 0

    # 재표준화
    for raw_col, score_col in [('밸류_raw', '밸류_점수'), ('퀄리티_raw', '퀄리티_점수'),
                                ('성장_raw', '성장_점수'), ('모멘텀_raw', '모멘텀_점수')]:
        valid = data[raw_col].dropna()
        cat_mean = valid.mean() if len(valid) > 0 else 0
        cat_std = valid.std() if len(valid) > 0 else 0
        if cat_std > 0:
            data[score_col] = (data[raw_col] - cat_mean) / cat_std
        else:
            data[score_col] = 0.0
        data[score_col] = data[score_col].fillna(0.0)

    # ROE 하드게이트
    if 'ROE' in data.columns:
        roe_neg_mask = data['ROE'] <= 0
        if roe_neg_mask.any():
            data = data[~roe_neg_mask].copy()

    # 단일팩터 바닥
    EXTREME_THRESHOLD = -1.5
    cat_cols_4 = ['밸류_점수', '퀄리티_점수', '성장_점수', '모멘텀_점수']
    extreme_mask = (data[cat_cols_4] < EXTREME_THRESHOLD).any(axis=1)
    if extreme_mask.any():
        data = data[~extreme_mask].copy()

    # 최종 가중합 (환경변수로 동적 설정)
    V_W = float(os.environ.get('FACTOR_V_W', '0.20'))
    Q_W = float(os.environ.get('FACTOR_Q_W', '0.20'))
    G_W = float(os.environ.get('FACTOR_G_W', '0.45'))
    M_W = float(os.environ.get('FACTOR_M_W', '0.15'))
    if momentum_zs:
        data['멀티팩터_점수'] = (data['밸류_점수'] * V_W +
                                data['퀄리티_점수'] * Q_W +
                                data['성장_점수'] * G_W +
                                data['모멘텀_점수'] * M_W)
    else:
        data['멀티팩터_점수'] = (data['밸류_점수'] * 0.5 + data['퀄리티_점수'] * 0.5)

    data['멀티팩터_순위'] = data['멀티팩터_점수'].rank(ascending=False, method='first', na_option='bottom')

    return data


# ============================================================================
# 5. 메인 날짜별 처리 (최적화)
# ============================================================================

def find_nearest_cache(cache_dict, target_date, max_gap_days=120):
    """target_date 이하에서 가장 가까운 캐시 찾기 (반환: 키 or None)"""
    candidates = sorted([d for d in cache_dict.keys() if d <= target_date], reverse=True)
    if not candidates:
        return None
    best = candidates[0]
    gap = (pd.Timestamp(target_date) - pd.Timestamp(best)).days
    if gap > max_gap_days:
        return None
    return best


def generate_ranking_for_date(date_str, preloaded, state_dir):
    """단일 날짜 ranking 생성 — v2 최적화"""
    from create_current_portfolio import get_broad_sector, EXCLUDE_KEYWORDS

    ohlcv = preloaded['ohlcv']
    base_ts = pd.Timestamp(date_str)
    tnames = preloaded['ticker_names']

    # --- 1. Market Cap (메모리에서 조회) ---
    mcap_key = find_nearest_cache(preloaded['market_cap'], date_str, max_gap_days=5)
    if mcap_key is None:
        return False, 'no market_cap'
    mcap_df = preloaded['market_cap'][mcap_key]
    mcap_df = mcap_df.copy()
    mcap_df['시가총액_억'] = mcap_df['시가총액'] / 1e8

    # 시총 필터
    min_mcap = preloaded.get('min_mcap', 1000)
    filtered = mcap_df[mcap_df['시가총액_억'] >= min_mcap].copy()

    # --- 2. 거래대금 (사전계산된 20일 평균) ---
    avg_vol_key = find_nearest_cache(preloaded['avg_volume'], date_str, max_gap_days=5)
    has_real_volume = False

    if avg_vol_key is not None:
        avg_tv = preloaded['avg_volume'][avg_vol_key]
        filtered = filtered.join(pd.DataFrame({'avg_tv': avg_tv}), how='left')
        filtered['avg_tv'] = filtered['avg_tv'].fillna(filtered['거래대금'] / 1e8 if '거래대금' in filtered.columns else 0)
        has_real_volume = (filtered['avg_tv'] > 0).sum() > len(filtered) * 0.1
    else:
        filtered['avg_tv'] = filtered['거래대금'] / 1e8 if '거래대금' in filtered.columns else 0

    if has_real_volume:
        large = filtered[filtered['시가총액_억'] >= 10000]
        mid = filtered[filtered['시가총액_억'] < 10000]
        mid_threshold = 30 if preloaded.get('strict_filter') else 20
        pass_large = large[large['avg_tv'] >= 50]
        pass_mid = mid[mid['avg_tv'] >= mid_threshold]
        filtered = pd.concat([pass_large, pass_mid])
    else:
        large = filtered[filtered['시가총액_억'] >= 10000]
        mid = filtered[(filtered['시가총액_억'] >= 3000) & (filtered['시가총액_억'] < 10000)]
        filtered = pd.concat([large, mid])

    # --- 3. 종목명 + 금융 제외 ---
    filtered['종목명'] = filtered.index.map(lambda t: tnames.get(t, t))
    extra_kw = ['화재', '생명'] if preloaded.get('strict_filter') else []
    all_keywords = list(EXCLUDE_KEYWORDS) + extra_kw
    exclude_mask = filtered['종목명'].apply(
        lambda n: any(kw in str(n) for kw in all_keywords)
    )
    filtered = filtered[~exclude_mask]
    universe_tickers = filtered.index.tolist()

    if len(universe_tickers) < 10:
        return False, f'universe too small ({len(universe_tickers)})'

    # --- 4. 재무제표 → magic_df (사전계산 TTM lookup에서 조회!) ---
    ttm_for_date = preloaded['ttm_lookup'].get(date_str, {})
    magic_df = ttm_lookup_to_dataframe(ttm_for_date, universe_tickers)
    if magic_df.empty:
        return False, 'no financial data'

    magic_df = magic_df.merge(
        filtered[['시가총액', '종목명']],
        left_on='종목코드', right_index=True, how='left'
    )
    magic_df['시가총액'] = magic_df['시가총액'] / 1e8

    if '자본' in magic_df.columns:
        magic_df = magic_df[magic_df['자본'] > 0].copy()

    # --- 5. OHLCV slice + MA120 필터 (벡터화) ---
    # 0→NaN은 프리로드에서 1회 처리, copy 불필요 (읽기전용)
    price_df = ohlcv[ohlcv.index <= base_ts]

    if preloaded.get('no_ma120', False):
        ma120_pass = magic_df['종목코드'].tolist()
    else:
        ma120_pass, ma120_fail = vectorized_ma120_filter(
            price_df, magic_df['종목코드'].tolist(), base_ts
        )
        if not ma120_pass:
            return False, 'MA120 filter: 0 passed'
    magic_df = magic_df[magic_df['종목코드'].isin(ma120_pass)].copy()

    # --- 6. 섹터 맵 (캐시) ---
    sector_key = find_nearest_cache(preloaded['sectors'], date_str)
    sector_map = {}
    if sector_key is not None:
        # 섹터 파일은 분기별이므로 파싱 결과를 캐시
        if sector_key not in preloaded.get('_sector_cache', {}):
            sector_path = preloaded['sectors'][sector_key]
            sec_df = pd.read_parquet(sector_path)
            col_code = sec_df.columns[0]
            col_sector = sec_df.columns[1]
            sm = {}
            for _, row in sec_df.iterrows():
                sm[row[col_code]] = str(row[col_sector])
            if '_sector_cache' not in preloaded:
                preloaded['_sector_cache'] = {}
            preloaded['_sector_cache'][sector_key] = sm
        sector_map = preloaded['_sector_cache'][sector_key]

    # --- 7. pykrx fundamental 병합 ---
    fund_key = find_nearest_cache(preloaded['fundamentals_pykrx'], date_str, max_gap_days=5)
    multifactor_df = magic_df.copy()
    if fund_key is not None:
        fund_df = preloaded['fundamentals_pykrx'][fund_key]
        for col, new_col in [('PER', 'pykrx_PER'), ('PBR', 'pykrx_PBR'),
                              ('EPS', 'pykrx_EPS'), ('BPS', 'pykrx_BPS')]:
            if col in fund_df.columns:
                col_map = fund_df[col].to_dict()
                multifactor_df[new_col] = multifactor_df['종목코드'].map(col_map)

    multifactor_df['종목명'] = multifactor_df['종목코드'].map(tnames)

    # --- 8. 멀티팩터 계산 (인라인, disk I/O 없음) ---
    os.environ['DISABLE_FWD_BONUS'] = '1'
    mom_period = os.environ.get('MOM_PERIOD', '6m')

    scored = calculate_multifactor_fast(
        multifactor_df, price_df, sector_map, date_str,
        preloaded['growth_lookup'], mom_period
    )

    if scored.empty:
        return False, 'scoring failed'

    # --- 9. Ranking JSON 저장 ---
    scored_sorted = scored.sort_values('멀티팩터_점수', ascending=False)
    rankings_list = []
    for rank_idx, (_, row) in enumerate(scored_sorted.iterrows(), 1):
        ticker = str(row.get('종목코드', '')).zfill(6)
        item = {
            'rank': rank_idx,
            'composite_rank': int(row.get('멀티팩터_순위', rank_idx)),
            'ticker': ticker,
            'name': str(row.get('종목명', '')),
            'score': round(float(row.get('멀티팩터_점수', 0)), 4) if pd.notna(row.get('멀티팩터_점수')) else 0,
            'sector': get_broad_sector(sector_map.get(ticker, '')),
        }
        for col, key in [('밸류_점수', 'value_s'), ('퀄리티_점수', 'quality_s'),
                         ('성장_점수', 'growth_s'), ('모멘텀_점수', 'momentum_s')]:
            val = row.get(col)
            if val is not None and pd.notna(val):
                item[key] = round(float(val), 4)
        for col, key in [('매출성장률_z', 'rev_z'), ('이익변화량_z', 'oca_z')]:
            val = row.get(col)
            if val is not None and pd.notna(val):
                item[key] = round(float(val), 4)
        if ticker in price_df.columns and base_ts in price_df.index:
            p = price_df.loc[base_ts, ticker]
            if pd.notna(p) and p > 0:
                item['price'] = int(p)
        if 'price' not in item:
            continue
        rankings_list.append(item)

    # 상관관계
    top30_tickers = [r['ticker'] for r in rankings_list[:30]]
    corr_60d = vectorized_correlation(price_df, top30_tickers)

    ranking_data = {
        'date': date_str,
        'generated_at': pd.Timestamp.now(tz='Asia/Seoul').isoformat(),
        'rankings': rankings_list,
        'metadata': {
            'universe_count': len(universe_tickers),
            'scored_count': len(scored),
            'generator': 'fast_generate_rankings_v2',
            'correlation_60d': corr_60d,
        },
    }
    out_path = state_dir / f'ranking_{date_str}.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(ranking_data, f, ensure_ascii=False, indent=2)

    return True, f'{len(rankings_list)}종목'


# ============================================================================
# 6. 메인
# ============================================================================

def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = [a for a in sys.argv[1:] if a.startswith('--')]

    if len(args) < 2:
        print('사용법: python backtest/fast_generate_rankings_v2.py START END [--state-dir=DIR] [--resume]')
        return

    start_str, end_str = args[0], args[1]
    state_dir = PROJECT_ROOT / 'state'
    for f in flags:
        if f.startswith('--state-dir='):
            state_dir = Path(f.split('=', 1)[1])
        elif f == '--state-dir' and len(args) > 2:
            state_dir = Path(args[2])

    state_dir.mkdir(parents=True, exist_ok=True)
    resume = '--resume' in flags
    no_ma120 = '--no-ma120' in flags
    if no_ma120:
        print('[옵션] MA120 필터 비활성화')
    use_rev_accel = '--rev-accel' in flags
    if use_rev_accel:
        print('[옵션] oca → rev_accel 교체')
    use_gross_profit = '--gross-profit' in flags
    if use_gross_profit:
        print('[옵션] 매출액 → 매출총이익 교체')
    use_strict_filter = '--strict-filter' in flags
    if use_strict_filter:
        print('[옵션] 거래대금 30억 + 키워드 화재/생명 추가')
    min_mcap = 1000
    for f in flags:
        if f.startswith('--min-mcap='):
            min_mcap = int(f.split('=')[1])
            print(f'[옵션] 시총 하한: {min_mcap}억')

    global CACHE_DIR
    for f in flags:
        if f.startswith('--cache-dir='):
            CACHE_DIR = Path(f.split('=', 1)[1])
    for i, f in enumerate(sys.argv[1:]):
        if f == '--cache-dir' and i + 2 < len(sys.argv):
            CACHE_DIR = Path(sys.argv[i + 2])

    # 거래일 목록
    ohlcv_files = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'))
    ohlcv_files.sort(key=lambda f: f.stem.split('_')[2])
    ohlcv_df = pd.read_parquet(ohlcv_files[0])
    all_dates = ohlcv_df.index
    MIN_HISTORY = 130

    earliest = all_dates[MIN_HISTORY]
    start = max(pd.Timestamp(start_str), earliest)
    end = pd.Timestamp(end_str)
    target_dates = [d.strftime('%Y%m%d') for d in all_dates if start <= d <= end]

    # 기존 파일 체크
    existing = set()
    for f in state_dir.glob('ranking_*.json'):
        d = f.stem.replace('ranking_', '')
        if len(d) == 8 and d.isdigit():
            existing.add(d)

    if resume:
        todo = [d for d in target_dates if d not in existing]
    else:
        todo = target_dates

    print(f'기간: {start_str} ~ {end_str}')
    print(f'거래일: {len(target_dates)}일, 기존: {len(existing)}일, 생성: {len(todo)}일')
    print(f'출력: {state_dir}')

    if not todo:
        print('생성할 날짜 없음')
        return

    # 프리로드 (거래일 목록 전달 → growth 사전계산)
    preload_start = (pd.Timestamp(todo[0]) - pd.Timedelta(days=70)).strftime('%Y%m%d')
    preloaded = preload_all_data(preload_start, end_str, trading_dates=todo,
                                 use_rev_accel=use_rev_accel,
                                 use_gross_profit=use_gross_profit)
    preloaded['no_ma120'] = no_ma120
    preloaded['strict_filter'] = use_strict_filter
    preloaded['min_mcap'] = min_mcap

    # 생성
    success = 0
    fail = 0
    t_start = time.time()

    for idx, date_str in enumerate(todo):
        t0 = time.time()
        try:
            ok, msg = generate_ranking_for_date(date_str, preloaded, state_dir)
        except Exception as e:
            ok = False
            msg = str(e)[:80]

        elapsed = time.time() - t0
        if ok:
            success += 1
            if (idx + 1) % 50 == 0 or idx == 0:
                total_elapsed = time.time() - t_start
                avg = total_elapsed / (idx + 1)
                remaining = avg * (len(todo) - idx - 1) / 60
                print(f'[{idx+1}/{len(todo)}] {date_str}: {msg}, {elapsed:.1f}초 (~{remaining:.0f}분 남음)')
        else:
            fail += 1
            print(f'[{idx+1}/{len(todo)}] {date_str}: FAIL — {msg} ({elapsed:.1f}초)')

    wall = time.time() - t_start
    print(f'\n{"="*60}')
    print(f'완료: {success}성공 / {fail}실패 / {len(todo)}전체')
    print(f'소요: {wall/60:.1f}분 (평균 {wall/max(success,1):.1f}초/일)')
    print(f'ranking: {len(list(state_dir.glob("ranking_*.json")))}일')
    print(f'{"="*60}')


if __name__ == '__main__':
    main()
