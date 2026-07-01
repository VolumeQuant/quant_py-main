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

# CP 의존성 제거: BT용 인라인 정의 (create_current_portfolio.py 임포트 시 KRX 인증 발생)
KRX_SECTOR_MAP = {
    '바이오/제약': '바이오/제약', '제약': '바이오/제약', '의료정밀': '의료기기',
    '운수장비': '자동차', '운수창고': '물류', '전기가스': '에너지/유틸',
    '금융': '금융', '증권': '금융', '보험': '금융',
    '출판/매체': '미디어', '기타제조': '기타',
}
def get_broad_sector(krx_sector: str) -> str:
    return KRX_SECTOR_MAP.get(krx_sector, krx_sector or '기타')


# 2026-05-24: KRX 분류 부정확 종목 ticker 기반 수동 매핑 (사용자 혼란 해소)
# KRX = '금융' 분류된 산업지주사 → '지주' / 실제 사업 분류 X 종목 → 본업 분류
TICKER_SECTOR_OVERRIDE = {
    # 산업지주사 (KRX = 금융 → 지주)
    '402340': '지주',  # SK스퀘어
    '034730': '지주',  # SK
    '009540': '지주',  # HD한국조선해양
    '267250': '지주',  # HD현대
    '003550': '지주',  # LG
    '006260': '지주',  # LS
    '180640': '지주',  # 한진칼
    '078930': '지주',  # GS
    '001040': '지주',  # CJ
    '004800': '지주',  # 효성
    '000150': '지주',  # 두산
    '000880': '지주',  # 한화
    '004990': '지주',  # 롯데지주
    '241560': '지주',  # 두산밥캣 → 사실 기계지만 보류
    '003410': '지주',  # 쌍용양회 X → 시멘트, 보류
    '079160': '지주',  # CJ CGV X → 미디어
    '011170': '지주',  # 롯데케미칼 X → 화학
    # KRX 분류 오류 (실제 사업 ≠ KRX)
    '008060': '전기전자',  # 대덕 (PCB 제조, KRX 분류상 금융이지만 실제 PCB)
    # KRX '의료정밀' 버킷 오분류 (2026-06-11, 웹검증) — 반도체/전자부품인데 '의료기기'로 표시되던 종목
    '131290': '반도체',    # 티에스이 (반도체 테스트 프로브카드/소켓)
    '025560': '반도체',    # 미래산업 (반도체 테스트 핸들러 장비)
    '281820': '반도체',    # 케이씨텍 (반도체 CMP 장비·슬러리 소재)
    '049630': '전기전자',  # 재영솔루텍 (스마트폰 카메라 VCM/OIS 부품 — 의료 무관)
    # 인바디(041830) 등 실제 의료기기는 '의료기기' 유지 (override 안 함)
}
# 무효 매핑 제거
for _bad in ('241560', '003410', '079160', '011170'):
    TICKER_SECTOR_OVERRIDE.pop(_bad, None)


# ── KSIC(DART 표준산업분류) 기반 정확 섹터 (2026-06-11) ──
# KRX 24개 대분류('의료·정밀기기'에 반도체검사장비/카메라/실제의료기기 혼재)가 부정확.
# DART induty_code(5자리)로 정확 분류. 표시 전용, 매매 무관.
def ksic_to_sector(code):
    """KSIC induty_code → 표시섹터. 매핑 안 되면 None(→ KRX맵 폴백)."""
    if code is None:
        return None
    c = str(code)
    # 반도체: 칩제조(261) + 반도체 제조용 기계(29271) + 정밀계측/검사장비(272, 사용자 선택)
    if c.startswith('261') or c.startswith('29271') or c.startswith('272'):
        return '반도체'
    if c.startswith('271'):           # 의료용 기기 (진짜 의료기기)
        return '의료기기'
    if c.startswith('273') or c.startswith('274'):  # 광학/카메라/시계
        return '전기전자'
    if c.startswith('26') or c.startswith('28'):    # 기타 전자부품/PCB/통신/전기장비
        return '전기전자'
    if c.startswith('29'):            # 비반도체 기계
        return '기계'
    return None                        # 그 외는 KRX 대분류 맵에 위임


def _load_ksic_sector_map():
    """ksic_sector_map.parquet → {ticker: 표시섹터}. 없으면 빈 dict."""
    import os
    path = 'data_cache/ksic_sector_map.parquet'
    if not os.path.exists(path):
        path = os.path.join(os.path.dirname(__file__), '..', 'data_cache', 'ksic_sector_map.parquet')
    try:
        import pandas as _pd
        df = _pd.read_parquet(path)
        out = {}
        for t, code in zip(df['ticker'].astype(str).str.zfill(6), df['induty_code']):
            s = ksic_to_sector(code)
            if s:
                out[t] = s
        return out
    except Exception:
        return {}

KSIC_SECTOR_MAP = _load_ksic_sector_map()


def get_sector_with_override(ticker: str, krx_sector: str) -> str:
    """수동 override 우선 → KSIC(정확) → KRX 대분류 폴백."""
    if ticker in TICKER_SECTOR_OVERRIDE:
        return TICKER_SECTOR_OVERRIDE[ticker]
    s = KSIC_SECTOR_MAP.get(ticker)
    if s:
        return s
    return get_broad_sector(krx_sector)

EXCLUDE_KEYWORDS = ['금융', '은행', '증권', '보험', '캐피탈', '카드', '저축',
                   '지주', '홀딩스', 'SPAC', '스팩', '리츠', 'REIT',
                   '생명', '화재', '손해보험', 'IB투자', '벤처투자', '자산운용', '신탁']


# ============================================================================
# 0. DART+FnGuide FS 유틸 (모듈 레벨 — CP에서도 import 가능)
# ============================================================================

def check_data_mismatch(dart_df, fn_df):
    """DART vs FnGuide 연간 데이터 불일치 체크"""
    try:
        mismatch_count = 0
        check_accounts = ['매출액', '영업이익', '당기순이익', '자산', '자본', '영업활동으로인한현금흐름']
        for acct in check_accounts:
            d_rows = dart_df[(dart_df['공시구분'] == 'y') & (dart_df['계정'] == acct)].copy()
            f_rows = fn_df[(fn_df['공시구분'] == 'y') & (fn_df['계정'] == acct)].copy()
            if d_rows.empty or f_rows.empty:
                continue
            d_rows['year'] = d_rows['기준일'].dt.year
            f_rows['year'] = f_rows['기준일'].dt.year
            common_years = set(d_rows['year']) & set(f_rows['year'])
            for yr in common_years:
                dv = d_rows[d_rows['year'] == yr].iloc[0]['값']
                fv = f_rows[f_rows['year'] == yr].iloc[0]['값']
                if acct in ('매출액', '자산'):
                    if fv > 0 and dv > 0:
                        ratio = dv / fv
                        if ratio < 0.5 or ratio > 2.0:
                            mismatch_count += 1
                            break
                else:
                    if dv != 0 and fv != 0 and (dv > 0) != (fv > 0):
                        mismatch_count += 1
                        break
                    if fv != 0 and dv != 0:
                        ratio = dv / fv
                        if ratio < 0.2 or ratio > 5.0:
                            mismatch_count += 1
                            break
        return mismatch_count >= 1
    except Exception:
        return False


_MISMATCH_RATIO_ACCTS = ('매출액', '자산', '자본')
_MISMATCH_SIGNED_ACCTS = ('영업이익', '당기순이익', '영업활동으로인한현금흐름')
_MISMATCH_ALL_ACCTS = _MISMATCH_RATIO_ACCTS + _MISMATCH_SIGNED_ACCTS


def fix_dart_account_mismatch(dart_df, fn_df):
    """항목별 DART vs FN mismatch 자동 정정 — mismatch row만 제거. 벡터화.

    기존 check_data_mismatch는 매출/자산 mismatch 1건이라도 있으면 DART 전체 폐기.
    실측 결과 (2026-05-12 EDA): mismatch는 항목별 독립 발생.
      - y 매출 mismatch 183개 중 영업이익도 mismatch 1개, 자산 0개, 자본 0개
    → 광범위 폐기 대신 항목별 정정. merge_fs_supplement이 FN으로 자동 보충.

    Part 1 (cross-sectional)만 유지. Part 2 시계열 검증은 폐기 (2026-05-12):
    - 링네트 사건 진짜 원인 = fs_dart 캐시 자체가 잘못된 값 (1/10 크기)
    - 전체 재수집으로 캐시 정정 → 시계열 검증 불필요

    Returns:
        (cleaned_df, removed_keys) — removed_keys: [(공시구분, 계정, 기준일), ...]
    """
    if dart_df is None or dart_df.empty:
        return dart_df, []

    removed_keys = []

    # ========== Part 1: DART vs FN cross-sectional 비교 (기존) ==========
    if fn_df is not None and not fn_df.empty:
        d_sub = dart_df[dart_df['계정'].isin(_MISMATCH_ALL_ACCTS)][['공시구분', '계정', '기준일', '값']]
        if not d_sub.empty:
            f_sub = fn_df[fn_df['계정'].isin(_MISMATCH_ALL_ACCTS)][['공시구분', '계정', '기준일', '값']]
            if not f_sub.empty:
                d_sub = d_sub.drop_duplicates(['공시구분', '계정', '기준일'], keep='first').rename(columns={'값': 'dv'})
                f_sub = f_sub.drop_duplicates(['공시구분', '계정', '기준일'], keep='first').rename(columns={'값': 'fv'})
                m = d_sub.merge(f_sub, on=['공시구분', '계정', '기준일'], how='inner')
                if not m.empty:
                    m = m[m['dv'].notna() & m['fv'].notna() & (m['dv'] != 0) & (m['fv'] != 0)]
                    if not m.empty:
                        is_ratio = m['계정'].isin(_MISMATCH_RATIO_ACCTS)
                        ratio = m['dv'] / m['fv']
                        abs_ratio = ratio.abs()
                        sign_diff = (m['dv'] > 0) != (m['fv'] > 0)
                        ratio_bad = is_ratio & ((ratio < 0.5) | (ratio > 2.0))
                        signed_bad = (~is_ratio) & (sign_diff | (abs_ratio < 0.2) | (abs_ratio > 5.0))
                        bad = ratio_bad | signed_bad
                        if bad.any():
                            bad_rows = m[bad]
                            removed_keys.extend(list(zip(bad_rows['공시구분'], bad_rows['계정'], bad_rows['기준일'])))

    if not removed_keys:
        return dart_df, []

    rem_set = set(removed_keys)
    keys = pd.Series(list(zip(dart_df['공시구분'], dart_df['계정'], dart_df['기준일'])), index=dart_df.index)
    mask = ~keys.isin(rem_set)
    cleaned = dart_df[mask].reset_index(drop=True)
    return cleaned, removed_keys


def merge_fs_supplement(primary_df, secondary_df):
    """primary에 없는 계정을 secondary에서 보충 — 벡터화 버전"""
    # primary 키셋 (벡터화)
    pk = primary_df[['기준일', '공시구분', '계정']].apply(tuple, axis=1)
    primary_keys = set(pk)

    # rcept_dt 맵 (벡터화)
    rcept_map = {}
    if 'rcept_dt' in primary_df.columns:
        mask = primary_df['rcept_dt'].notna()
        rdf = primary_df.loc[mask, ['기준일', '공시구분', 'rcept_dt']].drop_duplicates(subset=['기준일', '공시구분'], keep='first')
        for _, row in rdf.iterrows():
            rcept_map[(row['기준일'], row['공시구분'])] = row['rcept_dt']

    # secondary에서 보충 대상 필터 (벡터화)
    sk = secondary_df[['기준일', '공시구분', '계정']].apply(tuple, axis=1)
    mask = ~sk.isin(primary_keys) & secondary_df['값'].notna()
    sup = secondary_df.loc[mask].copy()

    if sup.empty:
        return primary_df, 0

    default_ticker = primary_df.iloc[0].get('종목코드', '') if not primary_df.empty else ''
    if '종목코드' not in sup.columns:
        sup['종목코드'] = default_ticker

    if 'rcept_dt' in primary_df.columns:
        sup['rcept_dt'] = sup.apply(
            lambda r: rcept_map.get((r['기준일'], r['공시구분']),
                                    r.get('rcept_dt') if 'rcept_dt' in secondary_df.columns else None),
            axis=1)

    cols = [c for c in ['계정', '기준일', '값', '종목코드', '공시구분', 'rcept_dt'] if c in sup.columns]
    merged = pd.concat([primary_df, sup[cols]], ignore_index=True)
    return merged, len(sup)


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
        # rev_accel 계산 (매출성장률 2차미분)
        if events:
            prev_rev = None
            for i, (eff_date, vals) in enumerate(events):
                rev_yoy = vals.get('rev_yoy')
                if rev_yoy is not None and prev_rev is not None:
                    vals['rev_accel'] = rev_yoy - prev_rev
                else:
                    vals['rev_accel'] = None
                if rev_yoy is not None:
                    prev_rev = rev_yoy
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
                eff_date, vals = next_events[ticker]
                if eff_date <= date_ts:
                    current_values[ticker] = vals  # dict with 6 sub-factors
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


def _weighted_ttm_sum(vals, quarters, weights=None):
    """TTM 합산 — 가중/균등 지원. quarters[0]=최신, quarters[-1]=가장 오래된."""
    if weights is None:
        return sum(vals[q] for q in quarters)
    # quarters와 weights 길이 맞춤 (quarters가 짧으면 앞에서부터)
    n = min(len(quarters), len(weights))
    raw = sum(vals[quarters[i]] * weights[i] for i in range(n))
    w_sum = sum(weights[:n])
    return raw / w_sum if w_sum > 0 else 0  # 가중 합산 후 정규화


# TTM 가중치: 환경변수 TTM_WEIGHTS=0.4,0.3,0.2,0.1 (미설정=균등)
_ttm_weights_env = os.environ.get('TTM_WEIGHTS', '')
TTM_WEIGHTS = [float(x) for x in _ttm_weights_env.split(',') if x.strip()] if _ttm_weights_env else None
if TTM_WEIGHTS:
    print(f'[TTM] 가중 TTM 적용: {TTM_WEIGHTS}')


def _compute_ticker_growth_events(ticker, fs_df, rev_account='매출액'):
    """단일 종목의 growth 6-서브팩터 변경 이벤트 — v75 확장

    Returns: list of (eff_date, dict) where dict has:
      rev_yoy: 매출성장률 TTM YoY
      oca: 영업이익변화량/자산
      rev_accel: 매출성장률 가속도 (2차미분)
      gp_yoy: 매출총이익 TTM YoY
      op_margin_chg: 영업이익률 변화 (OPM_t - OPM_t-4)
      cfo_yoy: 영업현금흐름 TTM YoY
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

        # 계정별 날짜 리스트 (0 채우기 금지 — 실제 데이터 있는 분기만)
        rev_dates = sorted(d for d in q_dates if (d, rev_account) in q_vals)
        op_dates = sorted(d for d in q_dates if (d, '영업이익') in q_vals)
        gp_dates = sorted(d for d in q_dates if (d, '매출총이익') in q_vals)
        cfo_dates = sorted(d for d in q_dates if (d, '영업활동으로인한현금흐름') in q_vals)

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

            rev_yoy = None
            oca = None

            # TTM 매출 YoY — 매출액 존재하는 분기만 사용
            rev_avail = sorted([d for d in rev_dates if d <= qd], reverse=True)
            if len(rev_avail) >= 8:
                recent_4 = rev_avail[:4]
                prev_4 = rev_avail[4:8]
                # 갭 체크: 18개월 이상 갭이면 TTM 무효
                gap_days = (recent_4[-1] - prev_4[0]).days
                if gap_days <= 450:
                    _rv = {d: q_vals[(d, rev_account)] for d in recent_4}
                    _pv = {d: q_vals[(d, rev_account)] for d in prev_4}
                    r4 = _weighted_ttm_sum(_rv, recent_4, TTM_WEIGHTS)
                    p4 = _weighted_ttm_sum(_pv, prev_4, TTM_WEIGHTS)
                    if p4 > 0:
                        rev_yoy = (r4 / p4 - 1) * 100

            # op_change_asset — 영업이익 존재하는 분기만 사용
            op_avail = sorted([d for d in op_dates if d <= qd], reverse=True)
            if len(op_avail) >= 8:
                recent_4_op = op_avail[:4]
                prev_4_op = op_avail[4:8]
                gap_days_op = (recent_4_op[-1] - prev_4_op[0]).days
                if gap_days_op <= 550:
                    _ov_r = {d: q_vals[(d, '영업이익')] for d in recent_4_op}
                    _ov_p = {d: q_vals[(d, '영업이익')] for d in prev_4_op}
                    op_r = _weighted_ttm_sum(_ov_r, recent_4_op, TTM_WEIGHTS)
                    op_p = _weighted_ttm_sum(_ov_p, prev_4_op, TTM_WEIGHTS)
                    prev_asset = None
                    for d in sorted(prev_4_op):
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

            # --- 추가 4개 서브팩터 ---
            # gp_yoy: 매출총이익 TTM YoY
            gp_yoy = None
            gp_avail = sorted([d for d in gp_dates if d <= qd], reverse=True)
            if len(gp_avail) >= 8:
                _gv_r = {d: q_vals[(d, '매출총이익')] for d in gp_avail[:4]}
                _gv_p = {d: q_vals[(d, '매출총이익')] for d in gp_avail[4:8]}
                r4 = _weighted_ttm_sum(_gv_r, gp_avail[:4], TTM_WEIGHTS)
                p4 = _weighted_ttm_sum(_gv_p, gp_avail[4:8], TTM_WEIGHTS)
                if p4 > 0:
                    gp_yoy = (r4 / p4 - 1) * 100

            # op_margin_chg: 영업이익률 변화
            op_margin_chg = None
            if len(op_avail) >= 4 and len(rev_avail) >= 4:
                # 현재 OPM (TTM)
                _om_or = {d: q_vals[(d, '영업이익')] for d in op_avail[:4]}
                _om_rr = {d: q_vals.get((d, rev_account), 0) for d in rev_avail[:4]}
                op_r = _weighted_ttm_sum(_om_or, op_avail[:4], TTM_WEIGHTS)
                rev_r = _weighted_ttm_sum(_om_rr, rev_avail[:4], TTM_WEIGHTS)
                if rev_r > 0:
                    opm_now = op_r / rev_r
                    # 4분기 전 OPM
                    if len(op_avail) >= 8 and len(rev_avail) >= 8:
                        _om_op = {d: q_vals[(d, '영업이익')] for d in op_avail[4:8]}
                        _om_rp = {d: q_vals.get((d, rev_account), 0) for d in rev_avail[4:8]}
                        op_p = _weighted_ttm_sum(_om_op, op_avail[4:8], TTM_WEIGHTS)
                        rev_p = _weighted_ttm_sum(_om_rp, rev_avail[4:8], TTM_WEIGHTS)
                        if rev_p > 0:
                            opm_prev = op_p / rev_p
                            op_margin_chg = (opm_now - opm_prev) * 100  # %p

            # cfo_yoy: 영업현금흐름 TTM YoY
            cfo_yoy = None
            cfo_avail = sorted([d for d in cfo_dates if d <= qd], reverse=True)
            if len(cfo_avail) >= 8:
                _cv_r = {d: q_vals[(d, '영업활동으로인한현금흐름')] for d in cfo_avail[:4]}
                _cv_p = {d: q_vals[(d, '영업활동으로인한현금흐름')] for d in cfo_avail[4:8]}
                r4 = _weighted_ttm_sum(_cv_r, cfo_avail[:4], TTM_WEIGHTS)
                p4 = _weighted_ttm_sum(_cv_p, cfo_avail[4:8], TTM_WEIGHTS)
                if p4 > 0:
                    cfo_yoy = (r4 / p4 - 1) * 100

            # QoQ — 단일 분기 직전 대비 (v80.12 NEW)
            rev_qoq = None
            op_qoq = None
            if len(rev_avail) >= 2 and (qd, rev_account) in q_vals:
                cur_rev = q_vals[(qd, rev_account)]
                prev_q_d = rev_avail[1] if rev_avail[0] == qd else rev_avail[0]
                prev_rev = q_vals.get((prev_q_d, rev_account))
                if prev_rev is not None and prev_rev > 0:
                    rev_qoq = (cur_rev - prev_rev) / prev_rev * 100
            if len(op_avail) >= 2 and (qd, '영업이익') in q_vals:
                cur_op = q_vals[(qd, '영업이익')]
                prev_op_d = op_avail[1] if op_avail[0] == qd else op_avail[0]
                prev_op_val = q_vals.get((prev_op_d, '영업이익'))
                if prev_op_val is not None and abs(prev_op_val) > 1:
                    op_qoq = (cur_op - prev_op_val) / abs(prev_op_val) * 100

            if any(v is not None for v in [rev_yoy, oca, gp_yoy, op_margin_chg, cfo_yoy, rev_qoq, op_qoq]):
                events.append((eff_date, {
                    'rev_yoy': rev_yoy, 'oca': oca,
                    'gp_yoy': gp_yoy, 'op_margin_chg': op_margin_chg,
                    'cfo_yoy': cfo_yoy,
                    'rev_qoq': rev_qoq, 'op_qoq': op_qoq,
                }))

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
                    events.append((eff_date, {
                        'rev_yoy': rev_yoy, 'oca': None,
                        'gp_yoy': None, 'op_margin_chg': None, 'cfo_yoy': None,
                    }))

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

    # TTM_FUND_EQUAL=1: 균등 TTM(진짜 trailing 12M, 4분기 1:1:1:1). default=최근가중(1.6/1.2/0.8/0.4)
    base_weights = [1.0, 1.0, 1.0, 1.0] if os.environ.get('TTM_FUND_EQUAL') == '1' else [1.6, 1.2, 0.8, 0.4]
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

def preload_all_data(start_str, end_str, trading_dates=None, use_rev_accel=False, use_gross_profit=False,
                     production_mode=False):
    """모든 데이터 1회 로드 — v2: 모든 parquet를 메모리에
    production_mode=True: 최근 30일 MC/Fund만 로드 + 유니버스 FS만 로드 (4분→40초)
    """
    print(f'=== 데이터 프리로드 (v2{" — 프로덕션 경량" if production_mode else ""}) ===')
    t0 = time.time()
    data = {}

    # 프로덕션 모드: MC 최근 30일만 로드 → 거래대금+시총 필터 → 유니버스 결정
    prod_universe = None
    mc_recent = None
    if production_mode:
        mc_files = sorted(CACHE_DIR.glob('market_cap_ALL_*.parquet'))
        mc_files = [f for f in mc_files if f.stem.split('_')[-1] <= end_str]
        mc_recent = mc_files[-30:] if len(mc_files) > 30 else mc_files

    # 1. OHLCV — OHLCV_FILE env 오버라이드(수정주가 BT용) 우선, 없으면 _full 파일
    _ohlcv_override = os.environ.get('OHLCV_FILE', '')
    if _ohlcv_override and Path(_ohlcv_override).exists():
        ohlcv_file = Path(_ohlcv_override)
    else:
        ohlcv_files = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'))
        full_files = [f for f in ohlcv_files if '_full' in f.stem]
        if full_files:
            ohlcv_files = full_files
        ohlcv_files.sort(key=lambda f: f.stem.split('_')[2])
        ohlcv_file = ohlcv_files[0]
    print(f'  OHLCV: {ohlcv_file.name}')
    data['ohlcv'] = pd.read_parquet(ohlcv_file).replace(0, np.nan)
    print(f'    {data["ohlcv"].shape[0]}거래일 × {data["ohlcv"].shape[1]}종목 (0→NaN 변환 완료)')

    # 2. Market cap — 프로덕션: 최근 30일만 / 백테스트: 전부
    print('  Market cap 일괄 로드 중...')
    t_mc = time.time()
    data['market_cap'] = {}
    if production_mode and mc_recent:
        for f in mc_recent:
            d = f.stem.split('_')[-1]
            data['market_cap'][d] = pd.read_parquet(f)
    else:
        mc_files = sorted(CACHE_DIR.glob('market_cap_ALL_*.parquet'))
        for f in mc_files:
            d = f.stem.split('_')[-1]
            if d <= end_str:
                data['market_cap'][d] = pd.read_parquet(f)
    print(f'    {len(data["market_cap"])}일 로드 ({time.time()-t_mc:.1f}초)')

    # 프로덕션 모드: MC+거래대금으로 유니버스 결정 (FS 로딩 전)
    if production_mode and data['market_cap']:
        t_univ = time.time()
        avg_vol = precompute_avg_volume(data['market_cap'])
        latest_mc_date = sorted(data['market_cap'].keys())[-1]
        latest_mc = data['market_cap'][latest_mc_date]
        latest_vol_date = sorted(avg_vol.keys())[-1] if avg_vol else None
        latest_vol = avg_vol.get(latest_vol_date, pd.Series(dtype=float))
        # 시총 1000억+ 종목 (여유분 800억으로 확장)
        mcap_pass = set(latest_mc[latest_mc['시가총액'] >= 8e10].index) if '시가총액' in latest_mc.columns else set(latest_mc.index)
        # 거래대금 필터 (억 단위): 대형(1조+) 50억, 중소형 15억 (여유분)
        vol_pass = set()
        for tk in mcap_pass:
            mcap_val = latest_mc.loc[tk, '시가총액'] if tk in latest_mc.index else 0
            vol_val = latest_vol.get(tk, 0) if isinstance(latest_vol, pd.Series) else 0
            is_large = mcap_val >= 1e12
            if is_large and vol_val >= 40:
                vol_pass.add(tk)
            elif not is_large and vol_val >= 15:
                vol_pass.add(tk)
        # 우선주 제거 (끝자리 != 0)
        prod_universe = {tk for tk in vol_pass if tk[-1] == '0'}
        print(f'  프로덕션 유니버스: {len(prod_universe)}종목 (시총+거래대금+보통주, {time.time()-t_univ:.1f}초)')

    # 3. Fundamentals (pykrx PER/PBR) — 프로덕션: 최근 30일만
    print('  Fundamentals 일괄 로드 중...')
    t_fn = time.time()
    data['fundamentals_pykrx'] = {}
    fund_files = sorted(CACHE_DIR.glob('fundamental_batch_ALL_*.parquet'))
    if production_mode:
        fund_files = [f for f in fund_files if f.stem.split('_')[-1] <= end_str]
        fund_files = fund_files[-30:] if len(fund_files) > 30 else fund_files
    for f in fund_files:
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

    # 5. 재무제표 (DART + FnGuide mismatch 체크 — 모듈 레벨 함수 사용)
    print('  재무제표 로드 중...')
    data['fs'] = {}
    dart_count = fn_count = mismatch_swap = 0

    dart_map = {}
    for f in CACHE_DIR.glob('fs_dart_*.parquet'):
        ticker = f.stem.replace('fs_dart_', '')
        if prod_universe is not None and ticker not in prod_universe:
            continue
        try:
            df = pd.read_parquet(f)
            if not df.empty:
                dart_map[ticker] = df
        except Exception:
            pass

    fn_map = {}
    for f in CACHE_DIR.glob('fs_fnguide_*.parquet'):
        ticker = f.stem.replace('fs_fnguide_', '')
        if prod_universe is not None and ticker not in prod_universe:
            continue
        try:
            df = pd.read_parquet(f)
            if not df.empty:
                fn_map[ticker] = df
        except Exception:
            pass

    supplement_total = 0
    fix_total = 0  # 항목별 정정 row 수 (옵션F 폐기 후 0 유지)
    fix_tickers = 0
    all_tickers = set(dart_map) | set(fn_map)
    for ticker in all_tickers:
        if ticker in dart_map:
            # 옵션F (fix_dart_account_mismatch) 폐기 — 2026-05-12 사고
            # 사유: 같은 종목 24년(잘못)+25년(정상) 매출을 섞어 가짜 YoY 알파 생성
            #       (KBI메탈 cr 1위 사례). 캐시 정확하면 mismatch 정정 자체 불필요.
            #       항목별 정정이 필요한 경우 = 캐시 자체 오염 → 재수집이 정공법.
            if ticker in fn_map and check_data_mismatch(dart_map[ticker], fn_map[ticker]):
                data['fs'][ticker] = fn_map[ticker]
                fn_count += 1
                mismatch_swap += 1
            elif ticker in fn_map:
                dart_q = len(dart_map[ticker][dart_map[ticker]['공시구분'] == 'q']['기준일'].unique())
                fn_q = len(fn_map[ticker][fn_map[ticker]['공시구분'] == 'q']['기준일'].unique())
                if dart_q < 8 and fn_q > dart_q:
                    # DART 부족 → FnGuide 주 데이터 + DART 보충
                    merged, n_sup = merge_fs_supplement(fn_map[ticker], dart_map[ticker])
                    data['fs'][ticker] = merged
                    fn_count += 1
                    supplement_total += n_sup
                else:
                    # DART 기반 + FnGuide 보충
                    merged, n_sup = merge_fs_supplement(dart_map[ticker], fn_map[ticker])
                    data['fs'][ticker] = merged
                    dart_count += 1
                    supplement_total += n_sup
            else:
                data['fs'][ticker] = dart_map[ticker]
                dart_count += 1
        elif ticker in fn_map:
            data['fs'][ticker] = fn_map[ticker]
            fn_count += 1

    swap_msg = f', 불일치→FnGuide {mismatch_swap}' if mismatch_swap else ''
    sup_msg = f', FnGuide보충 {supplement_total}건' if supplement_total else ''
    fix_msg = f', 항목정정 {fix_tickers}종목/{fix_total}row' if fix_total else ''
    print(f'    {len(data["fs"])}종목 (DART {dart_count} + FnGuide {fn_count}{swap_msg}{sup_msg}{fix_msg})')

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

    # 8. 거래대금 20일 평균 사전계산 (+보조 N일 평균)
    print('  거래대금 20일 평균 사전계산 중...')
    t_vol = time.time()
    data['avg_volume'] = precompute_avg_volume(data['market_cap'])
    # 보조 필터용 N일 평균 (VOL_SUB_DAYS env var, 기본: 없음)
    vol_sub_days = int(os.environ.get('VOL_SUB_DAYS', '0'))
    if vol_sub_days > 0:
        data['avg_volume_sub'] = precompute_avg_volume(data['market_cap'], window=vol_sub_days)
        print(f'    {len(data["avg_volume"])}일 + 보조 {vol_sub_days}일 ({time.time()-t_vol:.1f}초)')
    else:
        data['avg_volume_sub'] = {}
        print(f'    {len(data["avg_volume"])}일 ({time.time()-t_vol:.1f}초)')

    # 9. 3년 연속 적자 — 종목별 연간 NI 시계열 캐싱 (PIT 적용)
    ni_yearly = {}
    for ticker, fs_df in data['fs'].items():
        ni = fs_df[(fs_df['계정'] == '당기순이익') & (fs_df['공시구분'] == 'y')].sort_values('기준일')
        if 'rcept_dt' in ni.columns:
            ni_yearly[ticker] = [(r['기준일'], r['rcept_dt'], r['값']) for _, r in ni.iterrows()]
        else:
            # rcept_dt 없으면 기준일+90일 추정
            ni_yearly[ticker] = [(r['기준일'], r['기준일'] + pd.Timedelta(days=90), r['값']) for _, r in ni.iterrows()]
    data['ni_yearly'] = ni_yearly
    # 이전 전역 chronic_3yr은 하위호환용 유지 (BT 날짜별 체크는 generate_ranking_for_date에서)
    chronic_3yr_current = set()
    for ticker, history in ni_yearly.items():
        vals = [v for _, _, v in history[-3:]]
        if len(vals) >= 3 and all(v < 0 for v in vals):
            chronic_3yr_current.add(ticker)
    data['chronic_loss_3yr'] = chronic_3yr_current  # 현재 시점 기준 (하위호환)
    print(f'  3년 연속 적자(현재): {len(chronic_3yr_current)}, ni_yearly 캐시: {len(ni_yearly)}종목')

    # 10. 자산급변 — 종목별 연간 자산/매출 시계열 캐싱 (PIT 적용)
    asset_rev_yearly = {}
    for ticker, fs_df in data['fs'].items():
        a_df = fs_df[(fs_df['계정'] == '자산') & (fs_df['공시구분'] == 'y')].sort_values('기준일')
        r_df = fs_df[(fs_df['계정'] == '매출액') & (fs_df['공시구분'] == 'y')].sort_values('기준일')
        if len(a_df) >= 2 and len(r_df) >= 2:
            a_list = [(r['기준일'], r.get('rcept_dt', r['기준일'] + pd.Timedelta(days=90)), r['값']) for _, r in a_df.iterrows()]
            rv_list = [(r['기준일'], r.get('rcept_dt', r['기준일'] + pd.Timedelta(days=90)), r['값']) for _, r in r_df.iterrows()]
            asset_rev_yearly[ticker] = {'assets': a_list, 'revenue': rv_list}
    data['asset_rev_yearly'] = asset_rev_yearly
    # 현재 시점 기준 asset_dilution (하위호환)
    asset_dilution_current = set()
    for ticker, hist in asset_rev_yearly.items():
        a_last = hist['assets'][-2:]
        r_last = hist['revenue'][-2:]
        if len(a_last) == 2 and len(r_last) == 2:
            a_prev, a_curr = a_last[0][2], a_last[1][2]
            r_prev, r_curr = r_last[0][2], r_last[1][2]
            if a_prev > 0 and r_prev > 0:
                a_growth = (a_curr / a_prev - 1) * 100
                r_growth = (r_curr / r_prev - 1) * 100
                if a_growth > 100 and r_growth < a_growth * 0.5:
                    asset_dilution_current.add(ticker)
    data['asset_dilution'] = asset_dilution_current
    print(f'  자산급변(현재): {len(asset_dilution_current)}, asset_rev_yearly 캐시: {len(asset_rev_yearly)}종목')

    elapsed = time.time() - t0
    print(f'  프리로드 완료: {elapsed:.1f}초')
    return data


def precompute_avg_volume(market_cap_dict, window=20):
    """거래대금 N일 이동평균 사전계산 — 최적화 버전

    1단계: 모든 날짜의 거래대금을 하나의 DataFrame으로 합침
    2단계: rolling(N).mean() 으로 한방에 계산
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

    # rolling N일 평균 (한방 계산)
    avg_df = vol_df.rolling(window=window, min_periods=1).mean() / 1e8

    # dict 변환
    avg_vol = {}
    for d in valid_dates:
        avg_vol[d] = avg_df.loc[d]

    return avg_vol


# ============================================================================
# 3. 벡터화된 팩터 계산
# ============================================================================

def vectorized_ma120_filter(price_df, universe_tickers, base_ts):
    """MA120 필터 — 벡터화 (per-ticker 루프 제거)

    2가지 조건 동시 적용 (v77 설계):
    1. 126일(6M) 이상 OHLCV 데이터 — 모멘텀 계산 가능, IPO 노이즈 회피
    2. 현재가 >= 120일 이동평균 — 하락 추세 종목 사전 배제 (모멘텀 전략 일관성)

    → 하락장 직후엔 이 필터로 유니버스가 크게 축소됨 (2023-01: 580→~280).
    → 이는 v77이 "모멘텀 기반" 전략이라 의도된 동작.
    """
    valid = [t for t in universe_tickers if t in price_df.columns]
    if not valid:
        return [], []

    # 마지막 120일 가격
    # 126일 미만 종목 제외: 전체 히스토리에서 유효 거래일 체크
    full_valid = price_df[valid].notna().sum()
    too_short = full_valid < 126

    _ma_days = int(os.environ.get('MA_FILTER_DAYS', '120'))  # 기본 120(현행 불변), MA60 BT용 env 오버라이드
    prices_slice = price_df[valid].iloc[-_ma_days:]
    if len(prices_slice) < _ma_days:
        return valid, []

    # 현재가 (마지막 행)
    current = prices_slice.iloc[-1]
    # MA(기본 120)
    ma120 = prices_slice.mean()
    # 필터: 현재가 >= MA AND 126일 이상
    mask = current >= ma120
    mask = mask.fillna(False) & ~too_short

    passed = mask[mask].index.tolist()
    failed = mask[~mask].index.tolist()
    return passed, failed


def _backadjust_corpaction(price_df):
    """권리락(무상증자/액면분할/병합) 자동보정 — 가격팩터(모멘텀/mom_10/저변동성) 왜곡 제거.
    KR 일일 가격제한 ±30% → 하루 수익률 <-33% 또는 >+45% = corporate action(권리락).
    각 권리락 비율을 이전 주가에 누적 곱으로 스티칭. price_df가 base_date까지 슬라이스돼
    있으면 point-in-time 안전(미래 권리락 미반영). 2026-06-16 기본 OFF로 전환(호출부 참조); 켜려면 CORPACTION_ADJ_ENABLE=1.
    Returns: (adjusted_df, 보정된_종목수)
    """
    if price_df is None or price_df.empty or len(price_df) < 2:
        return price_df, 0
    rets = price_df.pct_change(fill_method=None)
    ca = (rets < -0.33) | (rets > 0.45)
    if not bool(ca.to_numpy().any()):
        return price_df, 0
    factor = (rets + 1.0).where(ca)
    factor = factor.where((factor >= 0.02) & (factor <= 50.0))  # sanity: 데이터오류 제외 (1:50 병합·98%감자까지 보정, 미래산업 1:18 등)
    has_ca = ca & factor.notna()
    if not bool(has_ca.to_numpy().any()):
        return price_df, 0
    f = pd.DataFrame(1.0, index=price_df.index, columns=price_df.columns)
    f = f.mask(has_ca, factor)
    R = f[::-1].cumprod()[::-1]          # R[t] = prod(f[s] for s>=t)
    mult = R.shift(-1)                   # mult[t] = prod(f[s] for s>t) = 그 날짜 '이후' 권리락 곱
    mult.iloc[-1] = 1.0
    adjusted = price_df * mult
    n_stocks = int(has_ca.any(axis=0).sum())
    return adjusted, n_stocks


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


# 밸류 -1.5σ 필터로 제외된 종목 기록 (date → [종목코드]). 이탈 사유 정확 라벨링용.
# 급등으로 PER/PBR 폭등해 밸류_점수 < -1.5 된 종목 = '밸류 과열'(거래부족 아님).
_VALUE_OVERHEAT_BY_DATE = {}


def calculate_multifactor_fast(multifactor_df, price_df, sector_map, base_date,
                                growth_lookup, mom_period='6m'):
    """인라인 멀티팩터 계산 — disk I/O 없음

    strategy_b_multifactor.py의 calculate_multifactor_score를 인라인화하되,
    growth 팩터는 사전계산된 lookup에서 조회, 모멘텀은 벡터화.
    """
    data = multifactor_df.copy()

    # --- Value 팩터 ---
    # USE_SELF_PER=1: 자체 TTM PER (fs_dart 4분기 NI 합 기반, 어닝 즉시 반영)
    # 기본 (=0): pykrx PER (KRX 공식, 시차 있음)
    USE_SELF_PER = os.environ.get('USE_SELF_PER', '0') == '1'
    if USE_SELF_PER and '시가총액' in data.columns:
        ttm_ni_eok = data['지배주주당기순이익'].fillna(data.get('당기순이익', np.nan)) if '지배주주당기순이익' in data.columns else data.get('당기순이익', pd.Series(dtype=float))
        ttm_ni_won = ttm_ni_eok * 1e8  # 억원 → 원
        self_per = np.where(ttm_ni_won > 0, data['시가총액'] / ttm_ni_won, np.nan)
        data['PER'] = self_per
        # pykrx_PER을 self_per로 폴백 (그러나 pykrx>0이고 self가 없는 종목엔 pykrx 사용)
        if 'pykrx_PER' in data.columns:
            fallback = pd.isna(data['PER']) & (data['pykrx_PER'] > 0)
            data.loc[fallback, 'PER'] = data.loc[fallback, 'pykrx_PER']
    elif 'pykrx_PER' in data.columns:
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
    # ROE: 기본(=0) pykrx EPS/BPS(연간) 우선 + DART TTM 폴백.
    # USE_SELF_ROE=1: DART TTM(지배순이익/자본) 우선 + pykrx 폴백 → PER과 일관된 TTM 기준
    USE_SELF_ROE = os.environ.get('USE_SELF_ROE', '0') == '1'
    data['ROE'] = np.nan

    def _dart_ttm_roe():
        # 1순위: 지배주주당기순이익 TTM / 지배주주자본 (분자분모 기준 일치)
        if '지배주주당기순이익' in data.columns and '지배주주자본' in data.columns:
            m = data['ROE'].isna() & data['지배주주당기순이익'].notna() & (data['지배주주자본'] > 0)
            data.loc[m, 'ROE'] = data.loc[m, '지배주주당기순이익'] / data.loc[m, '지배주주자본'] * 100
        # 2순위: 지배주주당기순이익 TTM / 자본
        if '지배주주당기순이익' in data.columns and '자본' in data.columns:
            m = data['ROE'].isna() & data['지배주주당기순이익'].notna() & (data['자본'] > 0)
            data.loc[m, 'ROE'] = data.loc[m, '지배주주당기순이익'] / data.loc[m, '자본'] * 100
        # 3순위: 당기순이익 TTM / 자본 (별도재무제표 — 당기순이익=지배주주순이익)
        if '당기순이익' in data.columns and '자본' in data.columns:
            m = data['ROE'].isna() & data['당기순이익'].notna() & (data['자본'] > 0)
            data.loc[m, 'ROE'] = data.loc[m, '당기순이익'] / data.loc[m, '자본'] * 100

    def _pykrx_roe():
        if 'pykrx_EPS' in data.columns and 'pykrx_BPS' in data.columns:
            m = data['ROE'].isna() & (data['pykrx_EPS'] != 0) & (data['pykrx_BPS'] > 0)
            data.loc[m, 'ROE'] = data.loc[m, 'pykrx_EPS'] / data.loc[m, 'pykrx_BPS'] * 100

    if USE_SELF_ROE:
        _dart_ttm_roe()  # TTM 우선
        _pykrx_roe()     # pykrx 폴백
    else:
        _pykrx_roe()     # pykrx 우선 (기존 동작)
        _dart_ttm_roe()  # DART TTM 폴백 (기존 동작)

    if '매출총이익' in data.columns and '자산' in data.columns:
        data['GPA'] = data['매출총이익'] / data['자산'] * 100

    if '영업현금흐름' in data.columns and '자산' in data.columns:
        data['CFO'] = data['영업현금흐름'] / data['자산'] * 100

    # --- Growth 6-서브팩터 (사전계산 lookup에서 조회) ---
    date_growth = growth_lookup.get(base_date, {})
    _g_keys = ['rev_yoy', 'oca', 'rev_accel', 'gp_yoy', 'op_margin_chg', 'cfo_yoy']
    _g_names = ['매출성장률', '이익변화량', '매출가속도', '매출총이익성장', '영업이익률변화', '현금흐름성장']
    for gk, gn in zip(_g_keys, _g_names):
        data[gn] = data['종목코드'].map(
            lambda t, _k=gk: date_growth.get(t, {}).get(_k) if t in date_growth else np.nan
        )

    # --- Momentum 팩터 (벡터화, 4종 동시 계산) ---
    tickers = data['종목코드'].tolist()
    mom_dict, kratio_dict = vectorized_momentum(price_df, tickers, mom_period)
    data['모멘텀'] = data['종목코드'].map(mom_dict)
    data['K_ratio'] = data['종목코드'].map(kratio_dict)

    # 추가 모멘텀 (BT용: 그리드서치에서 모멘텀 타입 비교)
    _all_mom_periods = ['6m', '6m-1m', '12m', '12m-1m']
    _extra_mom = {}
    for mp in _all_mom_periods:
        if mp != mom_period:
            md, _ = vectorized_momentum(price_df, tickers, mp)
            _extra_mom[mp] = md
        else:
            _extra_mom[mp] = mom_dict

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
    # 6개 G 서브팩터 z-score
    _g_sub_cols = [
        ('매출성장률', '매출성장률_z'),
        ('이익변화량', '이익변화량_z'),
        ('매출가속도', '매출가속도_z'),
        ('매출총이익성장', '매출총이익성장_z'),
        ('영업이익률변화', '영업이익률변화_z'),
        ('현금흐름성장', '현금흐름성장_z'),
    ]
    for raw_col, z_col in _g_sub_cols:
        if raw_col in data.columns and data[raw_col].notna().sum() > 0:
            data[z_col] = rank_zscore_series(data[raw_col], ascending=True)
            growth_zs.append(z_col)
        else:
            data[z_col] = 0.0

    momentum_zs = []
    # 섹터 중립 z-score: data['섹터'] 직접 사용 (필터 후에도 index 정합)
    cur_sectors = data['섹터'] if '섹터' in data.columns and sector_map else None
    if '모멘텀' in data.columns and data['모멘텀'].notna().sum() > 0:
        data['모멘텀_z'] = rank_zscore_sector(data['모멘텀'], cur_sectors, ascending=True) if cur_sectors is not None else rank_zscore_series(data['모멘텀'], ascending=True)
        momentum_zs.append('모멘텀_z')
    if 'K_ratio' in data.columns and data['K_ratio'].notna().sum() > 0:
        data['K_ratio_z'] = rank_zscore_sector(data['K_ratio'], cur_sectors, ascending=True) if cur_sectors is not None else rank_zscore_series(data['K_ratio'], ascending=True)
        momentum_zs.append('K_ratio_z')

    # Growth NaN 대체: 모든 서브팩터에서 NaN은 매출성장률_z로 대체
    if '매출성장률_z' in growth_zs:
        for z_col in ['이익변화량_z', '매출가속도_z', '매출총이익성장_z', '영업이익률변화_z', '현금흐름성장_z']:
            if z_col in data.columns:
                nan_mask = data[z_col].isna() | (data[z_col] == 0.0)
                data.loc[nan_mask, z_col] = data.loc[nan_mask, '매출성장률_z']

    # NaN → 0
    for zs in [value_zs, quality_zs, growth_zs, momentum_zs]:
        for col in zs:
            data[col] = data[col].fillna(0.0)

    # 카테고리 평균
    data['밸류_raw'] = data[value_zs].mean(axis=1) if value_zs else 0
    data['퀄리티_raw'] = data[quality_zs].mean(axis=1) if quality_zs else 0

    # Growth 가중 — G_SUB1/G_SUB2(/G_SUB3) env var로 서브팩터 선택 (v77: 3팩터 지원)
    _sub_map = {'rev_z': '매출성장률_z', 'oca_z': '이익변화량_z', 'rev_accel_z': '매출가속도_z',
                'gp_growth_z': '매출총이익성장_z', 'op_margin_z': '영업이익률변화_z', 'cfo_growth_z': '현금흐름성장_z'}
    _g_sub1_env = os.environ.get('G_SUB1')
    _g_sub2_env = os.environ.get('G_SUB2')
    _g_sub3_env = os.environ.get('G_SUB3')  # 3팩터 (None이면 2팩터)
    _g_w1_env = os.environ.get('G_W1')

    if _g_sub3_env and _g_w1_env:
        # 3팩터: G_W1*SUB1 + G_W2*SUB2 + G_W3*SUB3
        g_s1 = _sub_map.get(_g_sub1_env, '매출성장률_z')
        g_s2 = _sub_map.get(_g_sub2_env, '이익변화량_z')
        g_s3 = _sub_map.get(_g_sub3_env, '매출총이익성장_z')
        w1 = float(os.environ.get('G_W1', '0.5'))
        w2 = float(os.environ.get('G_W2', '0.3'))
        w3 = float(os.environ.get('G_W3', '0.2'))
        cols_ok = all(c in data.columns for c in [g_s1, g_s2, g_s3])
        if cols_ok:
            data['성장_raw'] = data[g_s1] * w1 + data[g_s2] * w2 + data[g_s3] * w3
        else:
            data['성장_raw'] = data[growth_zs].mean(axis=1) if growth_zs else 0
    elif _g_sub1_env and _g_sub2_env:
        # 2팩터: G_REVENUE_WEIGHT * SUB1 + (1-w) * SUB2
        g_rev_w = float(os.environ.get('G_REVENUE_WEIGHT', '0.7'))
        g_s1 = _sub_map.get(_g_sub1_env, '매출성장률_z')
        g_s2 = _sub_map.get(_g_sub2_env, '이익변화량_z')
        if g_s1 in data.columns and g_s2 in data.columns:
            data['성장_raw'] = data[g_s1] * g_rev_w + data[g_s2] * (1.0 - g_rev_w)
        else:
            data['성장_raw'] = data[growth_zs].mean(axis=1) if growth_zs else 0
    else:
        g_rev_w = float(os.environ.get('G_REVENUE_WEIGHT', '0.7'))
        if len(growth_zs) == 2 and '매출성장률_z' in growth_zs and '이익변화량_z' in growth_zs:
            data['성장_raw'] = data['매출성장률_z'] * g_rev_w + data['이익변화량_z'] * (1.0 - g_rev_w)
        else:
            data['성장_raw'] = data[growth_zs].mean(axis=1) if growth_zs else 0

    data['모멘텀_raw'] = data[momentum_zs].mean(axis=1) if momentum_zs else 0

    # 추가 모멘텀 z-score (BT 저장용)
    for mp, md in _extra_mom.items():
        col_raw = f'mom_{mp.replace("-","")}_raw'
        data[col_raw] = data['종목코드'].map(md)
        if data[col_raw].notna().sum() > 0:
            data[f'mom_{mp.replace("-","")}_z'] = rank_zscore_sector(
                data[col_raw], cur_sectors, ascending=True
            ) if cur_sectors is not None else rank_zscore_series(data[col_raw], ascending=True)
        else:
            data[f'mom_{mp.replace("-","")}_z'] = 0.0
        # K_ratio 포함 평균
        if 'K_ratio_z' in data.columns:
            data[f'mom_{mp.replace("-","")}_score'] = (
                data[f'mom_{mp.replace("-","")}_z'].fillna(0) + data['K_ratio_z'].fillna(0)
            ) / 2.0
        else:
            data[f'mom_{mp.replace("-","")}_score'] = data[f'mom_{mp.replace("-","")}_z'].fillna(0)
        # 재표준화
        valid = data[f'mom_{mp.replace("-","")}_score'].dropna()
        m, s = valid.mean(), valid.std()
        if s > 0:
            data[f'mom_{mp.replace("-","")}_s'] = (data[f'mom_{mp.replace("-","")}_score'] - m) / s
        else:
            data[f'mom_{mp.replace("-","")}_s'] = 0.0

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

    # ROE 하드게이트: ROE <= 0 제거 (적자 기업 배제 — v77 설계)
    # ROE NaN(pykrx+DART 모두 산출 불가)은 스킵 — GPA/CFO로 Quality 평가
    if 'ROE' in data.columns:
        roe_neg_mask = data['ROE'] <= 0
        if roe_neg_mask.any():
            data = data[~roe_neg_mask].copy()

    # 단일팩터 바닥 (v77 설계 — 심각히 부진한 종목 사전 배제)
    # V/Q/G/M 4개 점수 중 하나라도 -1.5σ 미만이면 제외
    # 예: 하이닉스 2024-01-02 같이 Growth 점수가 -1.5 미만이면 제외됨
    # 이는 "모든 팩터가 균형 있게 좋은 종목" 선호하는 v77 철학 반영
    # 단일팩터 바닥 필터 — env var로 옵션 제어:
    #   EXTREME_MODE=A: 임계값 -2.0 (완화)
    #   EXTREME_MODE=B: V(밸류) 제외, Q/G/M만 -1.5 적용
    #   EXTREME_MODE=C: 필터 비활성 (전부 통과)
    #   EXTREME_MODE=D: V 낮아도 Q+G+M 평균 > 0이면 유지
    #   미설정 (기본): 기존 v77 방식 (-1.5σ, 4팩터 전부)
    _extreme_mode = os.environ.get('EXTREME_MODE', '')
    cat_cols_4 = ['밸류_점수', '퀄리티_점수', '성장_점수', '모멘텀_점수']

    if _extreme_mode == 'C':
        pass  # 필터 없음
    elif _extreme_mode == 'A':
        EXTREME_THRESHOLD = -2.0
        extreme_mask = (data[cat_cols_4] < EXTREME_THRESHOLD).any(axis=1)
        if extreme_mask.any():
            data = data[~extreme_mask].copy()
    elif _extreme_mode == 'B':
        # V 제외, Q/G/M만 -1.5
        qgm_cols = ['퀄리티_점수', '성장_점수', '모멘텀_점수']
        extreme_mask = (data[qgm_cols] < -1.5).any(axis=1)
        if extreme_mask.any():
            data = data[~extreme_mask].copy()
    elif _extreme_mode == 'D':
        # V 낮아도 Q+G+M 평균 > 0이면 유지
        qgm_avg = data[['퀄리티_점수', '성장_점수', '모멘텀_점수']].mean(axis=1)
        extreme_mask = (data[cat_cols_4] < -1.5).any(axis=1) & (qgm_avg <= 0)
        if extreme_mask.any():
            data = data[~extreme_mask].copy()
    elif _extreme_mode == 'E':
        # ★V 바닥 면제: 고모멘텀(M >= VFLOOR_MOM_EXEMPT)이면 V<-1.5 무시. Q/G/M<-1.5는 항상 제외.
        # 근거: 브이엠 등 고PBR 모멘텀 승자가 급등→V 극단→강제이탈(휩쏘) 방지. 2026-06-26 실험.
        MOM_EXEMPT = float(os.environ.get('VFLOOR_MOM_EXEMPT', '1.0'))
        qgm_cols = ['퀄리티_점수', '성장_점수', '모멘텀_점수']
        other_viol = (data[qgm_cols] < -1.5).any(axis=1)
        v_viol = (data['밸류_점수'] < -1.5) & (data['모멘텀_점수'] < MOM_EXEMPT)
        extreme_mask = other_viol | v_viol
        if '밸류_점수' in data.columns and '종목코드' in data.columns:
            _vo = data.loc[(data['밸류_점수'] < -1.5) & (data['모멘텀_점수'] >= MOM_EXEMPT), '종목코드'].astype(str).tolist()
        if extreme_mask.any():
            data = data[~extreme_mask].copy()
    else:
        # 기본 (v77 원본)
        EXTREME_THRESHOLD = -1.5
        extreme_mask = (data[cat_cols_4] < EXTREME_THRESHOLD).any(axis=1)
        # 밸류 과열 기록: 밸류_점수 < -1.5 로 제외되는 종목 (이탈 사유 라벨용)
        if '밸류_점수' in data.columns and '종목코드' in data.columns:
            _vo = data.loc[data['밸류_점수'] < EXTREME_THRESHOLD, '종목코드'].astype(str).tolist()
            _VALUE_OVERHEAT_BY_DATE[base_date] = _vo
        if extreme_mask.any():
            data = data[~extreme_mask].copy()

    # 최종 가중합 (환경변수로 동적 설정)
    V_W = float(os.environ.get('FACTOR_V_W', '0.20'))
    Q_W = float(os.environ.get('FACTOR_Q_W', '0.20'))
    G_W = float(os.environ.get('FACTOR_G_W', '0.30'))
    M_W = float(os.environ.get('FACTOR_M_W', '0.30'))
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

def find_nearest_cache(cache_dict, target_date, max_gap_days=120, strict=False):
    """target_date 이하(strict=True면 미만)에서 가장 가까운 캐시 찾기"""
    if strict:
        candidates = sorted([d for d in cache_dict.keys() if d < target_date], reverse=True)
    else:
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
    # get_broad_sector, EXCLUDE_KEYWORDS: 모듈 상단에 인라인 정의 (CP 임포트 제거)

    ohlcv = preloaded['ohlcv']
    base_ts = pd.Timestamp(date_str)
    tnames = preloaded['ticker_names']

    # --- 1. Market Cap (당일 종가 기준 — 시간외 종가매매로 당일 매매 가능) ---
    mcap_key = find_nearest_cache(preloaded['market_cap'], date_str, max_gap_days=10)
    if mcap_key is None:
        return False, 'no market_cap'
    mcap_df = preloaded['market_cap'][mcap_key]
    mcap_df = mcap_df.copy()
    mcap_df['시가총액_억'] = mcap_df['시가총액'] / 1e8

    # 시총 필터
    min_mcap = preloaded.get('min_mcap', 1000)
    filtered = mcap_df[mcap_df['시가총액_억'] >= min_mcap].copy()

    # 우선주 제거 (보통주 티커는 끝자리 0)
    filtered = filtered[filtered.index.str[-1] == '0']

    # --- 2. 거래대금 (사전계산된 20일 평균) ---
    avg_vol_key = find_nearest_cache(preloaded['avg_volume'], date_str, max_gap_days=10)
    has_real_volume = False

    if avg_vol_key is not None:
        avg_tv = preloaded['avg_volume'][avg_vol_key]
        filtered = filtered.join(pd.DataFrame({'avg_tv': avg_tv}), how='left')
        filtered['avg_tv'] = filtered['avg_tv'].fillna(filtered['거래대금'] / 1e8 if '거래대금' in filtered.columns else 0)
        has_real_volume = (filtered['avg_tv'] > 0).sum() > len(filtered) * 0.1
    else:
        # avg_volume 없을 때: market_cap의 당일 거래대금 사용 (단일일이라도 필터 가능)
        if '거래대금' in filtered.columns:
            filtered['avg_tv'] = filtered['거래대금'] / 1e8
            has_real_volume = (filtered['avg_tv'] > 0).sum() > len(filtered) * 0.1
        else:
            filtered['avg_tv'] = 0

    if has_real_volume:
        large = filtered[filtered['시가총액_억'] >= 10000]
        mid = filtered[filtered['시가총액_억'] < 10000]
        mid_threshold = 30 if preloaded.get('strict_filter') else 20
        pass_large = large[large['avg_tv'] >= 50]
        pass_mid = mid[mid['avg_tv'] >= mid_threshold]
        filtered = pd.concat([pass_large, pass_mid])
        # 보조 필터 (VOL_SUB_DAYS + VOL_SUB_THRESHOLD)
        vol_sub_threshold = float(os.environ.get('VOL_SUB_THRESHOLD', '0'))
        if vol_sub_threshold > 0 and preloaded.get('avg_volume_sub'):
            sub_key = find_nearest_cache(preloaded['avg_volume_sub'], date_str, max_gap_days=10)
            if sub_key:
                sub_tv = preloaded['avg_volume_sub'][sub_key]
                filtered = filtered.join(pd.DataFrame({'sub_tv': sub_tv}), how='left')
                filtered['sub_tv'] = filtered['sub_tv'].fillna(0)
                filtered = filtered[filtered['sub_tv'] >= vol_sub_threshold]
    else:
        large = filtered[filtered['시가총액_억'] >= 10000]
        mid = filtered[(filtered['시가총액_억'] >= 3000) & (filtered['시가총액_억'] < 10000)]
        filtered = pd.concat([large, mid])

    # --- 3. 종목명 키워드 제외 ---
    # 2026-05-12: KRX 섹터 "금융" 필터 제거 (산업지주사 NAV 알파 보존).
    # 5/12 link 사건 분석: 섹터필터로 link 차단 안 됨 (link은 IT섹터, 오늘 데이터 기준).
    # link 차단 실패한 다른 안전망: 이격도20/매출CV/매출점프/RSI 모두 실패.
    # 결론: link은 시스템적 차단 불가능 (정량적으로 정상 알파 분포 안).
    # 매수 후보 Top 3엔 link 안 들어감 = 부모님 매수 신호 차단 OK.
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
    # point-in-time: market_cap에 존재하는 종목만 OHLCV에서 사용 (look-ahead bias 방지)
    mcap_tickers = set(mcap_df.index)
    ohlcv_cols = [c for c in ohlcv.columns if c in mcap_tickers]
    price_df = ohlcv.loc[ohlcv.index <= base_ts, ohlcv_cols]
    # 권리락(무상증자/분할/병합) 자동보정 — 기본 ON (표준 total-return 방식, 가격왜곡 보정).
    # ★2026-06-17 재복원: 06-16에 "corp-OFF가 7.4년 Calmar 4.31>1.74로 우월"이라며 껐으나 ★측정오류.
    # 그 4.31은 분할 미보정(왜곡) 가격으로 모멘텀(신호)을 계산해 권리락 직후 부실주를 우연히 회피한 artifact.
    # 왜곡 가격으로 신호 만드는 건 부적절(표준=분할보정 모멘텀), honest(보정) 성과는 ~1.74. 깨끗히 잡히는
    # 권리락회피 알파는 명시팩터로 +0.41뿐. 디바이스(무상증자 후 정상종목) 부당제외 부작용도 있었음.
    # → 보정 ON 복원. 끄려면 CORPACTION_ADJ_DISABLE=1.
    if os.environ.get('CORPACTION_ADJ_DISABLE') != '1':
        price_df, _n_corpadj = _backadjust_corpaction(price_df)

    ma120_fail = []
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
    fund_key = find_nearest_cache(preloaded['fundamentals_pykrx'], date_str, max_gap_days=10)
    multifactor_df = magic_df.copy()
    if fund_key is not None:
        fund_df = preloaded['fundamentals_pykrx'][fund_key]
        for col, new_col in [('PER', 'pykrx_PER'), ('PBR', 'pykrx_PBR'),
                              ('EPS', 'pykrx_EPS'), ('BPS', 'pykrx_BPS')]:
            if col in fund_df.columns:
                col_map = fund_df[col].to_dict()
                multifactor_df[new_col] = multifactor_df['종목코드'].map(col_map)

    multifactor_df['종목명'] = multifactor_df['종목코드'].map(tnames)

    # --- 7.5. 데이터 품질 필터 ---
    # (a) pykrx PER/PBR/EPS/BPS 전부 0 → 데이터 산출 불가 (적자 or 신규상장)
    if all(c in multifactor_df.columns for c in ['pykrx_PER', 'pykrx_PBR', 'pykrx_EPS', 'pykrx_BPS']):
        all_zero = ((multifactor_df['pykrx_PER'].fillna(0) == 0) &
                    (multifactor_df['pykrx_PBR'].fillna(0) == 0) &
                    (multifactor_df['pykrx_EPS'].fillna(0) == 0) &
                    (multifactor_df['pykrx_BPS'].fillna(0) == 0))
        multifactor_df = multifactor_df[~all_zero]
    # (b) 3년 연속 적자 제거 — PIT: base_date 시점까지 공시된 연간 NI로 판정
    if os.environ.get('FILTER_NO_CHRONIC') != '1':
        ni_yearly = preloaded.get('ni_yearly', {})
        if ni_yearly:
            chronic_at_date = set()
            for tk, history in ni_yearly.items():
                avail = [(d, v) for d, rcpt, v in history if rcpt is not None and rcpt <= base_ts]
                if len(avail) >= 3 and all(v < 0 for _, v in avail[-3:]):
                    chronic_at_date.add(tk)
            multifactor_df = multifactor_df[~multifactor_df['종목코드'].isin(chronic_at_date)]
        elif preloaded.get('chronic_loss_3yr'):  # 폴백 (구버전)
            multifactor_df = multifactor_df[~multifactor_df['종목코드'].isin(preloaded['chronic_loss_3yr'])]
    # (c) 자산급변 — PIT: base_date 시점까지 공시된 자산/매출로 판정
    if os.environ.get('FILTER_NO_ASSET_DIL') != '1':
        ar_yearly = preloaded.get('asset_rev_yearly', {})
        if ar_yearly:
            asset_dil_at_date = set()
            for tk, hist in ar_yearly.items():
                a_avail = [(d, v) for d, rcpt, v in hist['assets'] if rcpt is not None and rcpt <= base_ts]
                r_avail = [(d, v) for d, rcpt, v in hist['revenue'] if rcpt is not None and rcpt <= base_ts]
                if len(a_avail) >= 2 and len(r_avail) >= 2:
                    a_prev, a_curr = a_avail[-2][1], a_avail[-1][1]
                    r_prev, r_curr = r_avail[-2][1], r_avail[-1][1]
                    if a_prev > 0 and r_prev > 0:
                        a_g = (a_curr / a_prev - 1) * 100
                        r_g = (r_curr / r_prev - 1) * 100
                        if a_g > 100 and r_g < a_g * 0.5:
                            asset_dil_at_date.add(tk)
            multifactor_df = multifactor_df[~multifactor_df['종목코드'].isin(asset_dil_at_date)]
        elif preloaded.get('asset_dilution'):  # 폴백 (구버전)
            multifactor_df = multifactor_df[~multifactor_df['종목코드'].isin(preloaded['asset_dilution'])]
    # (d) 시점별 DART 분기보고서 8개(2년) 미만 제외 — 신규 상장/분할 baseline 부족
    #     base_date 시점까지 공시된 분기 기준 (rcept_dt <= base_date)
    #     예: 솔루스첨단소재 2021-05 시점엔 5분기 → capped → 제외
    if os.environ.get('FILTER_NO_NEW_LISTING') != '1':
        fs_dict = preloaded.get('fs', {})
        if fs_dict:
            min_quarters = 8
            insufficient = []
            base_ts_for_filter = base_ts
            for tk in multifactor_df['종목코드'].tolist():
                fs_df = fs_dict.get(tk)
                if fs_df is None or fs_df.empty:
                    insufficient.append(tk); continue
                if '공시구분' not in fs_df.columns:
                    insufficient.append(tk); continue
                q_df = fs_df[fs_df['공시구분'] == 'q']
                # 시점별: rcept_dt <= base_date (공시 시점까지만)
                if 'rcept_dt' in q_df.columns:
                    q_available = q_df[q_df['rcept_dt'].notna() & (q_df['rcept_dt'] <= base_ts_for_filter)]
                    q_dates_avail = q_available['기준일'].unique()
                else:
                    # rcept_dt 없으면 기준일+90일 추정
                    q_df = q_df.copy()
                    q_df['_est_avail'] = q_df['기준일'] + pd.Timedelta(days=90)
                    q_available = q_df[q_df['_est_avail'] <= base_ts_for_filter]
                    q_dates_avail = q_available['기준일'].unique()
                if len(q_dates_avail) < min_quarters:
                    insufficient.append(tk)
            if insufficient:
                multifactor_df = multifactor_df[~multifactor_df['종목코드'].isin(insufficient)]

    # --- 8. 멀티팩터 계산 (인라인, disk I/O 없음) ---
    mom_period = os.environ.get('MOM_PERIOD', '6m')

    scored = calculate_multifactor_fast(
        multifactor_df, price_df, sector_map, date_str,
        preloaded['growth_lookup'], mom_period
    )

    if scored.empty:
        return False, 'scoring failed'

    # ============================================================
    # 얇은 밸류트랩 제외 (대덕류) — 2026-06-10
    # 지주사/밸류트랩이 PBR 낮아(자회사 장부가) -1.5σ 밸류필터 통과 → 추천되던 문제.
    # 시그니처: PER>40 & PBR<1.5 & 거래대금<50억(단일일). 대덕(184/1.08/19억) 제거,
    # 브이엠(PBR 11.8=고PBR)은 안 건드림. 7년 BT 수익 무해(+0.08, MDD/WF/OOS/LOO 비악화),
    # 제거 카테고리(7년 6종목 32건 fwd -5.55%/승률28% vs 나머지 +3.73%/49%) 일관 열위.
    # 알파 아닌 '거래 곤란한 얇은 밸류트랩 제거' 품질필터. 환경변수: THIN_VTRAP_DISABLE=1.
    # ============================================================
    if os.environ.get('THIN_VTRAP_DISABLE') != '1' and 'PER' in scored.columns and 'PBR' in scored.columns:
        _tvmap = (mcap_df['거래대금'] / 1e8).to_dict() if '거래대금' in mcap_df.columns else {}
        _tv = scored['종목코드'].map(_tvmap)
        _vtrap = (scored['PER'] > 40) & (scored['PBR'] > 0) & (scored['PBR'] < 1.5) & _tv.notna() & (_tv < 50)
        _n_vt = int(_vtrap.sum())
        if _n_vt > 0:
            # v80.27 검증/감사: 제거 종목명+지표 로그 (forward 오제거 모니터링용 — N=1 forward 리스크 가시화)
            _rm = scored[_vtrap]
            _names = ' / '.join(
                f"{r.get('종목명', r['종목코드'])}(PER{r['PER']:.0f}/PBR{r['PBR']:.1f}/{_tvmap.get(r['종목코드'], 0):.0f}억)"
                for _, r in _rm.iterrows())
            print(f'  얇은 밸류트랩 제외: {_n_vt}종목 — {_names} (고PER>40+저PBR<1.5+거래<50억)')
            scored = scored[~_vtrap].copy()

    # ============================================================
    # v80.7 (2026-05-16): 계절성 패널티
    # Q2+Q4 매출 / Q1+Q3 매출 > 1.4 인 종목 → 성장_점수 × 0.5
    # 효과: 7.4y Cal 2.90 → 3.29 (+0.39, MDD 개선)
    # 사용자 케이스(선익시스템) 함정 회피 — 8.6세대 OLED 같은 일회성 Q2/Q4 폭증 패턴 자동 감지
    # 환경변수: SEASONALITY_DISABLE=1로 비활성화
    # ============================================================
    if os.environ.get('SEASONALITY_DISABLE') != '1':
        # v80.9 (2026-05-16 저녁): curr 식 복귀 + PENALTY 0.3
        # 이유: v80.8 (bi 양방향)이 제주반도체 같은 진짜 가속 성장 종목 잘못 패널티 → 사용자 통찰 위반
        # curr 식이 사용자 의도 100% 만족 (선익/동아 패널티, 제주 보호)
        # 인접 안정성 BT: curr 1.4/0.3 Cal 3.222 (curr 1.4/0.5 +0.096)
        SEAS_RATIO_THRESH = float(os.environ.get('SEASONALITY_RATIO_THRESH', '1.4'))
        SEAS_PENALTY = float(os.environ.get('SEASONALITY_PENALTY', '0.3'))
        SEAS_FORMULA = os.environ.get('SEASONALITY_FORMULA', 'curr').lower()
        SEAS_CV_THRESH = float(os.environ.get('SEASONALITY_CV_THRESH', '0.40'))
        fs_dict_local = preloaded.get('fs', {})
        seas_applied = 0
        for idx, row in scored.iterrows():
            tk = row.get('종목코드')
            if not tk or tk not in fs_dict_local: continue
            fs_tk = fs_dict_local[tk]
            q_tk = fs_tk[(fs_tk['공시구분']=='q') & (fs_tk['계정']=='매출액')]
            if 'rcept_dt' not in q_tk.columns: continue
            q_avail = q_tk[q_tk['rcept_dt'].notna() & (q_tk['rcept_dt'] <= base_ts)]
            if len(q_avail) < 8: continue
            last8 = q_avail.sort_values('rcept_dt').tail(8)
            vals = last8['값'].astype(float).values
            if (vals <= 0).any(): continue
            months = last8['기준일'].dt.month.values
            q24 = vals[(months == 6) | (months == 12)].sum()
            q13 = vals[(months == 3) | (months == 9)].sum()
            if q13 <= 0 or q24 <= 0: continue
            ratio_curr = q24 / q13

            # 식 후보별 판정
            triggered = False
            if SEAS_FORMULA == 'curr':
                triggered = ratio_curr > SEAS_RATIO_THRESH
            elif SEAS_FORMULA == 'bi':
                ratio_bi = max(ratio_curr, 1.0 / ratio_curr)
                triggered = ratio_bi > SEAS_RATIO_THRESH
            elif SEAS_FORMULA == 'bi_and_cv':
                ratio_bi = max(ratio_curr, 1.0 / ratio_curr)
                import numpy as _np
                cv = _np.std(vals) / _np.mean(vals)
                triggered = (ratio_bi > SEAS_RATIO_THRESH) and (cv > SEAS_CV_THRESH)
            elif SEAS_FORMULA == 'bi_or_cv':
                ratio_bi = max(ratio_curr, 1.0 / ratio_curr)
                import numpy as _np
                cv = _np.std(vals) / _np.mean(vals)
                triggered = (ratio_bi > SEAS_RATIO_THRESH) or (cv > SEAS_CV_THRESH)
            elif SEAS_FORMULA == 'max2min2':
                import numpy as _np
                sv = _np.sort(vals)
                m2m2 = sv[-2:].sum() / max(sv[:2].sum(), 1e-9)
                triggered = m2m2 > SEAS_RATIO_THRESH
            elif SEAS_FORMULA == 'cv':
                import numpy as _np
                cv = _np.std(vals) / _np.mean(vals)
                triggered = cv > SEAS_CV_THRESH

            if triggered:
                # v80.10 후보 (2026-05-17): 진정 성장 종목 면제
                # 조건: min(last4) / max(last4) > MM_THRESH (직전 4분기 변동성 작음 = 일관 성장)
                # 브이엠 0.35 ✓, 보성파워텍 0.31 ✓ → 진정 성장 (보호)
                # 동아엘텍 0.11, 선익시스템 0.07 → 함정 (차단 유지)
                # 환경변수: SEASONALITY_EXEMPT_MM_THRESH (v80.10: 기본 0.2 활성)
                # 7.4y BT Cal -0.07 (noise 범위) + MDD -0.71%p 개선 + 브이엠/보성파워텍 보호
                MM_THRESH = float(os.environ.get('SEASONALITY_EXEMPT_MM_THRESH', '0.2'))
                if MM_THRESH > 0 and len(vals) >= 4:
                    import numpy as _np
                    last4 = vals[-4:]
                    mn, mx = float(_np.min(last4)), float(_np.max(last4))
                    if mx > 0 and (mn / mx) > MM_THRESH:
                        continue  # 면제 → 패널티 적용 X

                # 성장_점수 × penalty + 멀티팩터_점수 재계산
                V_W = float(os.environ.get('FACTOR_V_W', '0.20'))
                Q_W = float(os.environ.get('FACTOR_Q_W', '0.20'))
                G_W = float(os.environ.get('FACTOR_G_W', '0.30'))
                M_W = float(os.environ.get('FACTOR_M_W', '0.30'))
                new_g = (row.get('성장_점수', 0) or 0) * SEAS_PENALTY
                scored.at[idx, '성장_점수'] = new_g
                scored.at[idx, '멀티팩터_점수'] = (
                    (row.get('밸류_점수', 0) or 0) * V_W +
                    (row.get('퀄리티_점수', 0) or 0) * Q_W +
                    new_g * G_W +
                    (row.get('모멘텀_점수', 0) or 0) * M_W
                )
                seas_applied += 1
        if seas_applied > 0:
            # 순위 재부여
            scored['멀티팩터_순위'] = scored['멀티팩터_점수'].rank(ascending=False, method='first', na_option='bottom')
            print(f'    계절성 패널티: {seas_applied}종목 (ratio>{SEAS_RATIO_THRESH}, ×{SEAS_PENALTY})')

    # ============================================================
    # v80.29 (2026-06-24): 일회성 분기(lumpiness) 페널티 — 방향무관 매출 변동성
    # 디바이스(187870)·선익형 = 대형 프로젝트 선적되는 분기만 반짝, 사이엔 텅 빈 회사.
    # 한 분기 블록버스터가 TTM 뻥튀기→성장2σ→진입권. 다음분기 꺼지면 -50%.
    # 계절성('curr' Q2/Q4 방향)이 못 잡는 Q1/Q3 산발 lumpiness를 잡음.
    # 척도: min(최근4분기 매출)/max(최근4분기 매출) < 0.25 → "가장 약한 분기가 센 분기의 25% 미만"
    #   = 어느 분기가 텅 빔 = 프로젝트 회사. → 성장_점수 × 0.3
    # PIT(rcept_dt<=base_ts), 8분기 이상·전부 양수 필요. 환경변수 LUMPINESS_DISABLE=1로 비활성.
    # 검증(7.4년): 진입 5505건 중 min/max<0.25 코호트 fwd60 -0.15%/승률28%(전체 +10%/50%).
    #   WF 전구간 ≥baseline(약세장 무해), 디바이스 매수일 전부 매수권밖(1→11위 등), 제주반도체 보존,
    #   LOWO(디바이스·선익 제외) +0.28=광범위. 계절성/일회성(accruals)과 별개 ADD.
    # ============================================================
    if os.environ.get('LUMPINESS_DISABLE') != '1':
        LUMP_THRESH = float(os.environ.get('LUMPINESS_MINMAX_THRESH', '0.25'))
        LUMP_PENALTY = float(os.environ.get('LUMPINESS_PENALTY', '0.3'))
        fs_dict_lump = preloaded.get('fs', {})
        lump_applied = 0
        for idx, row in scored.iterrows():
            tk = row.get('종목코드')
            if not tk or tk not in fs_dict_lump: continue
            fs_tk = fs_dict_lump[tk]
            q_tk = fs_tk[(fs_tk['공시구분'] == 'q') & (fs_tk['계정'] == '매출액')]
            if 'rcept_dt' not in q_tk.columns: continue
            q_avail = q_tk[q_tk['rcept_dt'].notna() & (q_tk['rcept_dt'] <= base_ts)]
            if len(q_avail) < 8: continue
            vals = q_avail.sort_values('rcept_dt').tail(8)['값'].astype(float).values
            if (vals <= 0).any(): continue
            last4 = vals[-4:]
            mx = float(last4.max())
            if mx <= 0: continue
            if (float(last4.min()) / mx) < LUMP_THRESH:
                V_W = float(os.environ.get('FACTOR_V_W', '0.20'))
                Q_W = float(os.environ.get('FACTOR_Q_W', '0.20'))
                G_W = float(os.environ.get('FACTOR_G_W', '0.30'))
                M_W = float(os.environ.get('FACTOR_M_W', '0.30'))
                new_g = (row.get('성장_점수', 0) or 0) * LUMP_PENALTY
                scored.at[idx, '성장_점수'] = new_g
                scored.at[idx, '멀티팩터_점수'] = (
                    (row.get('밸류_점수', 0) or 0) * V_W +
                    (row.get('퀄리티_점수', 0) or 0) * Q_W +
                    new_g * G_W +
                    (row.get('모멘텀_점수', 0) or 0) * M_W
                )
                lump_applied += 1
        if lump_applied > 0:
            scored['멀티팩터_순위'] = scored['멀티팩터_점수'].rank(ascending=False, method='first', na_option='bottom')
            print(f'    일회성분기(lumpiness) 패널티: {lump_applied}종목 (min/max<{LUMP_THRESH}, ×{LUMP_PENALTY})')

    # ============================================================
    # v80.25 (2026-06-09): 일회성 이익 페널티 — accruals + 분기쏠림
    # 한 분기 일회성 이익으로 TTM 뻥튀기된 스캠(에스에이엠티/삼지전자 등) 차단.
    # B = (당기순이익TTM - 영업현금흐름TTM)/자산 ×100  (이익이 현금으로 안 들어옴 = 가짜)
    # C = max(최근4분기 영업이익) / 영업이익TTM            (한 분기 쏠림 = 일회성)
    # B>25 AND C>0.7 → 성장_점수 × 0.24 (소프트 페널티; 하드컷/진입차단은 winner 학살로 기각)
    # 7.4y BT(X6 production-replay) 강도스윕: 0.30~0.22 무해평탄(Cal~4.48, 2026 +284%) / 0.20부터 절벽(-39p). 하드·진입차단 2026 -25.8p.
    # 0.24 채택 — 에스에이엠티를 삼성전자 아래(wr 5위)로 밀되 BT는 0.30과 동급. MDD 강도무관 동일(분산+순위이탈이 공매도 tail 흡수).
    # 약세장(2022) 무해, 인접 CV 0.014, LOWO 견고. 제주반도체(B21<25)·엑시콘(B20<25) 보존.
    # 일괄 규칙(종목 예외 없음). 계절성 패널티와 동일 패턴(PIT: rcept_dt<=base_ts). 환경변수: ONEOFF_DISABLE=1로 비활성화
    # ============================================================
    if os.environ.get('ONEOFF_DISABLE') != '1':
        ONEOFF_B = float(os.environ.get('ONEOFF_B_THRESH', '25'))
        ONEOFF_C = float(os.environ.get('ONEOFF_C_THRESH', '0.7'))
        ONEOFF_PENALTY = float(os.environ.get('ONEOFF_PENALTY', '0.24'))
        V_W = float(os.environ.get('FACTOR_V_W', '0.20'))
        Q_W = float(os.environ.get('FACTOR_Q_W', '0.20'))
        G_W = float(os.environ.get('FACTOR_G_W', '0.30'))
        M_W = float(os.environ.get('FACTOR_M_W', '0.30'))
        fs_dict_oneoff = preloaded.get('fs', {})
        def _ttm_last4(fs_tk, acct, base_ts):
            q = fs_tk[(fs_tk['공시구분'] == 'q') & (fs_tk['계정'] == acct)]
            if 'rcept_dt' not in q.columns: return None
            q = q[q['rcept_dt'].notna() & (q['rcept_dt'] <= base_ts)]
            if len(q) == 0: return None
            q = q.sort_values('rcept_dt').drop_duplicates('기준일', keep='last').sort_values('기준일')
            return q['값'].astype(float).values
        oneoff_applied = 0
        for idx, row in scored.iterrows():
            tk = row.get('종목코드')
            if not tk or tk not in fs_dict_oneoff: continue
            fs_tk = fs_dict_oneoff[tk]
            opv = _ttm_last4(fs_tk, '영업이익', base_ts)
            niv = _ttm_last4(fs_tk, '당기순이익', base_ts)
            cfv = _ttm_last4(fs_tk, '영업활동으로인한현금흐름', base_ts)
            asv = _ttm_last4(fs_tk, '자산', base_ts)
            if opv is None or niv is None or cfv is None or asv is None: continue
            if len(opv) < 4 or len(niv) < 4 or len(cfv) < 4 or len(asv) < 1: continue
            op4 = opv[-4:]
            op_ttm = float(op4.sum()); asset = float(asv[-1])
            if op_ttm <= 0 or asset <= 0: continue
            B = (float(niv[-4:].sum()) - float(cfv[-4:].sum())) / asset * 100
            C = float(op4.max()) / op_ttm
            if B > ONEOFF_B and C > ONEOFF_C:
                new_g = (row.get('성장_점수', 0) or 0) * ONEOFF_PENALTY
                scored.at[idx, '성장_점수'] = new_g
                scored.at[idx, '멀티팩터_점수'] = (
                    (row.get('밸류_점수', 0) or 0) * V_W +
                    (row.get('퀄리티_점수', 0) or 0) * Q_W +
                    new_g * G_W +
                    (row.get('모멘텀_점수', 0) or 0) * M_W
                )
                oneoff_applied += 1
        if oneoff_applied > 0:
            scored['멀티팩터_순위'] = scored['멀티팩터_점수'].rank(ascending=False, method='first', na_option='bottom')
            print(f'    일회성이익 패널티: {oneoff_applied}종목 (B>{ONEOFF_B}&C>{ONEOFF_C}, ×{ONEOFF_PENALTY})')

    # ============================================================
    # v80.12 (2026-05-18): QoQ 패널티 — base 효과 종목 차단
    # 사용자 통찰: 보성파워텍처럼 25Q1 base 작아서 26Q1 OP YoY +285%이지만 QoQ +11% 미미
    # 옵션: A (qoq_op<-10%→0.5x), B (qoq_op<-5%→0.5x), C (AND-Gate)
    # 환경변수: G_QOQ_PENALTY=A/B/C (default off)
    # ============================================================
    qoq_mode = os.environ.get('G_QOQ_PENALTY', '').upper()
    if qoq_mode in ('A', 'B', 'C', 'D6'):
        QOQ_PENALTY = float(os.environ.get('G_QOQ_PENALTY_MULTIPLIER', '0.5'))
        QOQ_THRESHOLD = float(os.environ.get('G_QOQ_PENALTY_THRESHOLD', '-10'))
        # v80.12 SG6: 강한 boost (KOSPI > MA220 × (1+SG6)) 일 때만 패널티 적용
        # 약한 boost (회복기) 또는 defense에선 baseline 유지 → 회복기 종목 보호
        # 환경변수: G_QOQ_SG6_THRESH (기본 0.06 = 6% 거리)
        sg6_active = False
        sg6_thresh = float(os.environ.get('G_QOQ_SG6_THRESH', '0.06'))
        if sg6_thresh > 0:
            try:
                kdf = pd.read_parquet(CACHE_DIR / 'kospi_yf.parquet')
                kp_s = kdf['close'] if 'close' in kdf.columns else kdf.iloc[:, 0]
                ma220 = kp_s.rolling(220).mean()
                base_ts_q = pd.Timestamp(date_str)
                # Series.get(key)는 정확 매칭만 — 거래일 timestamp 매칭 위해 asof/loc 사용
                # date_str (YYYYMMDD) → kp_s index 중 최근 거래일
                avail_idx = kp_s.index[kp_s.index <= base_ts_q]
                if len(avail_idx) == 0:
                    k_now = None; ma_now = None
                else:
                    last_d = avail_idx[-1]
                    k_now = kp_s.loc[last_d]
                    ma_now = ma220.loc[last_d]
                if k_now is not None and pd.notna(k_now) and pd.notna(ma_now) and ma_now > 0:
                    sg6_active = k_now > ma_now * (1 + sg6_thresh)
                else:
                    sg6_active = False
            except Exception as _e:
                print(f'    SG6 체크 에러: {_e}')
                sg6_active = False
        else:
            sg6_active = True  # SG6 비활성화 시 모든 boost 적용
        if not sg6_active:
            qoq_mode = ''  # 패널티 안 적용
        else:
            print(f'    SG6 활성 (k={k_now:.0f}, ma={ma_now:.0f}, 거리 {(k_now/ma_now-1)*100:+.1f}%)')
    if qoq_mode in ('A', 'B', 'C', 'D6'):
        # growth_lookup에서 PIT QoQ 추출 (이미 _compute_ticker_growth_events에서 계산)
        gl = preloaded.get('growth_lookup', {})
        cur_gl = gl.get(date_str, {})
        qoq_applied = 0
        V_W = float(os.environ.get('FACTOR_V_W', '0.20'))
        Q_W = float(os.environ.get('FACTOR_Q_W', '0.20'))
        G_W = float(os.environ.get('FACTOR_G_W', '0.30'))
        M_W = float(os.environ.get('FACTOR_M_W', '0.30'))
        for idx, row in scored.iterrows():
            tk = row.get('종목코드')
            if not tk: continue
            vals = cur_gl.get(tk) if cur_gl else None
            if not vals: continue
            rev_qoq = vals.get('rev_qoq')
            op_qoq = vals.get('op_qoq')
            penalize = False
            if qoq_mode == 'A' and op_qoq is not None and op_qoq < -10:
                penalize = True
            elif qoq_mode == 'B' and op_qoq is not None and op_qoq < -5:
                penalize = True
            elif qoq_mode == 'C':
                if op_qoq is not None and rev_qoq is not None:
                    if op_qoq <= 0 or rev_qoq <= 0:
                        penalize = True
            elif qoq_mode == 'D6' and op_qoq is not None and op_qoq < QOQ_THRESHOLD:
                # D6: G_QOQ_PENALTY_THRESHOLD (default +20%) 미만이면 패널티
                # 양수 미미 종목까지 잡음 (보성파워텍 같은 base 효과 차단)
                penalize = True
            if penalize:
                new_g = (row.get('성장_점수', 0) or 0) * QOQ_PENALTY
                scored.at[idx, '성장_점수'] = new_g
                scored.at[idx, '멀티팩터_점수'] = (
                    (row.get('밸류_점수', 0) or 0) * V_W +
                    (row.get('퀄리티_점수', 0) or 0) * Q_W +
                    new_g * G_W +
                    (row.get('모멘텀_점수', 0) or 0) * M_W
                )
                qoq_applied += 1
        if qoq_applied > 0:
            scored['멀티팩터_순위'] = scored['멀티팩터_점수'].rank(ascending=False, method='first', na_option='bottom')
            print(f'    QoQ 패널티({qoq_mode}): {qoq_applied}종목 (×{QOQ_PENALTY})')

    # (e) 2차 안전망: G 서브팩터 5개 이상 동일값 → capped 신호 → 제외
    #     (d) 시점별 필터를 통과했어도 rcept_dt 누락 등 엣지 케이스 잡기
    if os.environ.get('FILTER_NO_CAPPED') != '1':
        g_sub_cols = ['매출성장률_z', '이익변화량_z', '매출가속도_z', '매출총이익성장_z', '영업이익률변화_z', '현금흐름성장_z']
        existing = [c for c in g_sub_cols if c in scored.columns]
        if len(existing) >= 5:
            def _is_capped(row):
                vals = [row[c] for c in existing if pd.notna(row[c])]
                if len(vals) < 5: return False
                from collections import Counter
                mc = Counter(vals).most_common(1)[0]
                return mc[1] >= 5 and abs(mc[0]) > 1.5
            capped_mask = scored.apply(_is_capped, axis=1)
            if capped_mask.any():
                scored = scored[~capped_mask].copy()
                # 순위 재부여
                if not scored.empty:
                    scored['멀티팩터_순위'] = scored['멀티팩터_점수'].rank(ascending=False, method='first', na_option='bottom')

    # ============================================================
    # v80.20 (2026-05-27): mom_10 + vol_low 신팩터 boost 가산
    # BT: Cal 2.43 → 3.06 (+25%), MDD 31% → 29%, OOS 4.17 → 5.60
    # 사용자 의도: 가격 변동이 매일 ranking에 자연 반영
    # mom_10 = 10일 가격 변동률 (단기 모멘텀)
    # vol_low = 20일 일별 수익률 std 역수 (저변동성 우대 = MDD 보호)
    # 환경변수: FACTOR_MOM_10_W=0.05, FACTOR_VOL_LOW_W=0.06 (boost only)
    # ============================================================
    MOM_10_W = float(os.environ.get('FACTOR_MOM_10_W', '0.0'))
    VOL_LOW_W = float(os.environ.get('FACTOR_VOL_LOW_W', '0.0'))
    if (MOM_10_W != 0 or VOL_LOW_W != 0) and not scored.empty and price_df is not None:
        # CRITICAL: OHLCV 캐시는 캘린더 인덱스 (주말/휴일 = NaN 행).
        # iloc[-N]을 단순 적용하면 주말에 떨어질 위험 → 영업일만 추출.
        # 한국 KRX 거래일 기준 row가 데이터 있는 행만 사용 (>=50% 종목 가격 있음).
        nonempty_mask = price_df.notna().sum(axis=1) >= (price_df.shape[1] * 0.5)
        biz_prices = price_df.loc[nonempty_mask]
        if MOM_10_W != 0 and len(biz_prices) >= 11:
            mom_10_raw = biz_prices.iloc[-1] / biz_prices.iloc[-11] - 1
            mom_10_raw = mom_10_raw.replace([np.inf, -np.inf], np.nan).dropna()
            m, s = mom_10_raw.mean(), mom_10_raw.std()
            if s > 0:
                mom_10_z = (mom_10_raw - m) / s
                scored['mom_10_z'] = scored['종목코드'].map(mom_10_z.to_dict()).fillna(0)
                scored['멀티팩터_점수'] = scored['멀티팩터_점수'] + scored['mom_10_z'] * MOM_10_W
        if VOL_LOW_W != 0 and len(biz_prices) >= 21:
            daily_rets = biz_prices.iloc[-21:].pct_change().iloc[1:]
            vol_20 = daily_rets.std()
            vol_20 = vol_20.replace([np.inf, -np.inf], np.nan).dropna()
            m, s = vol_20.mean(), vol_20.std()
            if s > 0:
                vol_low_z = -(vol_20 - m) / s  # 저변동성 = 양수 z
                scored['vol_low_z'] = scored['종목코드'].map(vol_low_z.to_dict()).fillna(0)
                scored['멀티팩터_점수'] = scored['멀티팩터_점수'] + scored['vol_low_z'] * VOL_LOW_W
        # 순위 재부여
        scored['멀티팩터_순위'] = scored['멀티팩터_점수'].rank(ascending=False, method='first', na_option='bottom')

    # ============================================================
    # v80.31 과열+과대성장아님 펌프게이트 — 펀더 대비 과열된 종목 매수차단
    # 이격도20(종가/20일평균) > 1.4 AND 성장_점수 < 1.5 → 멀티팩터_점수 바닥(매수권 제외)
    # ★2026-07-01 확장: 성장임계 0.5→1.5. 근거: 과열(이격도>1.4)은 성장이 극단(>1.7σ)일 때만
    #   정당하고, 적당한 성장(0.5~1.7)이면 반락. EDA(rank≤6 과열): 성장0.5~1.0 −23%/승0%,
    #   1.0~1.7 −14%/승17%, >1.7 +24%/승62%. 미래산업(성장0.7·이격도1.46·+363%/3M)류 포착.
    # 시그니처: "펀더(성장)가 폭발적이지 않은데 가격만 과열"(금호 정치펌프 + 미래산업 모멘텀과열).
    # ★단독 이격도/단독 저성장은 BT 실패(승자 학살), 교집합만 robust.
    # BT 임계스윕: 성장<1.5가 최적 Calmar +0.084(MDD 25.9% 불변), LOWO 전부+(미래산업 포함),
    #   1.0~1.5 안정고원·1.7부터 SK존 침범해 −0.11. SK(1.8)·제주(2.1) 안전. env PUMPGATE_GROWTH.
    # ============================================================
    if os.environ.get('PUMPGATE_DISABLE') != '1' and not scored.empty and price_df is not None:
        PUMP_DISP = float(os.environ.get('PUMPGATE_DISP', '1.4'))
        PUMP_GROWTH = float(os.environ.get('PUMPGATE_GROWTH', '1.3'))
        try:
            _ne = price_df.notna().sum(axis=1) >= (price_df.shape[1] * 0.5)
            _bp = price_df.loc[_ne]
            if len(_bp) >= 20:
                _cur = _bp.iloc[-1]
                _ma20 = _bp.iloc[-20:].mean()
                _disp = (_cur / _ma20).replace([np.inf, -np.inf], np.nan)
                _dmap = _disp.to_dict()
                pump_applied = 0
                for idx, row in scored.iterrows():
                    _dv = _dmap.get(row['종목코드'])
                    _gv = row.get('성장_점수', 0) or 0
                    if _dv is not None and _dv == _dv and _dv > PUMP_DISP and _gv < PUMP_GROWTH:
                        scored.at[idx, '멀티팩터_점수'] = -999.0
                        pump_applied += 1
                if pump_applied:
                    scored['멀티팩터_순위'] = scored['멀티팩터_점수'].rank(ascending=False, method='first', na_option='bottom')
                    print(f'    과열+저성장 펌프게이트: {pump_applied}종목 매수차단 (이격도>{PUMP_DISP} & 성장<{PUMP_GROWTH})')
        except Exception as _pe:
            print(f'    펌프게이트 스킵: {_pe}')

    # ============================================================
    # 성장-밸류 괴리 과열 캡 (pen_cs) — 가격반응 earnings yield 기반 (boost only)
    # 자기 PER = 시총(일별, 가격반응) / TTM 지배순이익(PIT). 단면 z 중 '비싼 쪽'만 감점.
    # 사용자 의도: 가격 폭등 종목 자동 회피(추격매수 위험), 가격이 순위에 반영.
    # 비대칭 설계: 싼 건 무보상(모멘텀 승자 보호), 초고평가만 감점(거품 회피).
    # EDA(2023-24, 82일): top-3 평균수익 중립(+3.64 vs +3.59) + 승률 84% (vol_low形 일관성↑).
    # 단면 cheap-tilt / 시계열 PE압축은 top-3 평균 악화 → 기각. pen_cs만 무해.
    # 환경변수: FACTOR_OVERHEAT_W (기본 0 = 비활성, production 미배선 상태)
    # ============================================================
    OVERHEAT_W = float(os.environ.get('FACTOR_OVERHEAT_W', '0.0'))
    # STORE_OVERHEAT_PEN=1: pen 계산·저장만 (score 미반영) — 1회 재생성으로 W 그리드 BT용
    STORE_PEN = os.environ.get('STORE_OVERHEAT_PEN', '0') == '1'
    if (OVERHEAT_W != 0 or STORE_PEN) and not scored.empty and '시가총액' in scored.columns:
        # TTM 지배순이익(억원) — 지배주주당기순이익 우선, 당기순이익 폴백 (USE_SELF_PER와 동일 규칙)
        if '지배주주당기순이익' in scored.columns:
            ni_eok = scored['지배주주당기순이익'].fillna(scored.get('당기순이익', np.nan))
        else:
            ni_eok = scored.get('당기순이익', pd.Series(index=scored.index, dtype=float))
        mcap = scored['시가총액']
        ey = pd.Series(np.where((ni_eok > 0) & (mcap > 0), (ni_eok * 1e8) / mcap, np.nan),
                       index=scored.index)
        valid = ey.notna() & (ey > 0)
        if valid.sum() >= 20:
            log_ey = np.log(ey[valid])
            m, s = log_ey.mean(), log_ey.std()
            if s > 0:
                ey_z = (np.log(ey.where(valid)) - m) / s        # 비싼=음수, 싼=양수, 무효=NaN
                pen_cs = ey_z.clip(upper=0).fillna(0.0)         # 비싼 쪽만 감점, 싼 쪽/무효=0
                scored['overheat_pen'] = pen_cs
                if OVERHEAT_W != 0:                              # STORE 모드(W=0)에선 점수 미반영
                    scored['멀티팩터_점수'] = scored['멀티팩터_점수'] + pen_cs * OVERHEAT_W
                    scored['멀티팩터_순위'] = scored['멀티팩터_점수'].rank(ascending=False, method='first', na_option='bottom')

    # ============================================================
    # 최근 CA 페널티 (recent_ca) — 하락CA(무상증자/분할/유상증자) 직후 부실주 회피 (boost)
    # 2026-06-17: 수정주가 전환 시 사라지는 'post-CA 회피 알파'를 가격왜곡 없이 명시 포착.
    # 2026-06-18 down-only: CA_EVENTS_FILE(raw<-33% 하락갭=당일 관측가능 PIT)의 CA가 최근 K영업일내면 감점.
    #   병합(+45% 상승갭) 제외 — 방향분해 BT(_v6_blockers.py): 병합 페널티 기여 -0.072(해로움),
    #   하락CA-only Calmar 4.050>both 3.978. WF 3폴드 약세 OOS +0.498(W를 타폴드서 선택해도), 임계둔감(dlog0.1~0.4 다 4.07).
    # BT(7.4년, 수정주가 momentum 기반): Calmar 2.76→4.05(W0.3 K126 down-only). env FACTOR_RECENT_CA_W(기본 0).
    # ============================================================
    RECENT_CA_W = float(os.environ.get('FACTOR_RECENT_CA_W', '0.0'))
    RECENT_CA_K = int(os.environ.get('FACTOR_RECENT_CA_K', '126'))
    _ca_file = os.environ.get('CA_EVENTS_FILE', str(CACHE_DIR / 'ca_events.json'))
    if RECENT_CA_W != 0 and os.path.exists(_ca_file) and not scored.empty and price_df is not None:
        import json as _json
        _ca_by_tk = _json.load(open(_ca_file, encoding='utf-8')).get('ca_by_ticker', {})
        _nonempty = price_df.notna().sum(axis=1) >= (price_df.shape[1] * 0.5)
        _biz = price_df.loc[_nonempty].index
        if len(_biz) >= 1:
            _cut = (_biz[-(RECENT_CA_K + 1)] if len(_biz) > RECENT_CA_K else _biz[0]).strftime('%Y%m%d')
            _base = base_ts.strftime('%Y%m%d')
            def _recent_ca(tk):
                ds = _ca_by_tk.get(tk)
                return 1 if ds and any(_cut < d <= _base for d in ds) else 0
            scored['recent_ca'] = scored['종목코드'].map(_recent_ca)
            scored['멀티팩터_점수'] = scored['멀티팩터_점수'] - scored['recent_ca'] * RECENT_CA_W
            scored['멀티팩터_순위'] = scored['멀티팩터_점수'].rank(ascending=False, method='first', na_option='bottom')

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
            'sector': get_sector_with_override(ticker, sector_map.get(ticker, '')),
        }
        for col, key in [('밸류_점수', 'value_s'), ('퀄리티_점수', 'quality_s'),
                         ('성장_점수', 'growth_s'), ('모멘텀_점수', 'momentum_s')]:
            val = row.get(col)
            if val is not None and pd.notna(val):
                item[key] = round(float(val), 4)
        # 6개 G 서브팩터 z-score
        for col, key in [('매출성장률_z', 'rev_z'), ('이익변화량_z', 'oca_z'),
                         ('매출가속도_z', 'rev_accel_z'), ('매출총이익성장_z', 'gp_growth_z'),
                         ('영업이익률변화_z', 'op_margin_z'), ('현금흐름성장_z', 'cfo_growth_z')]:
            val = row.get(col)
            if val is not None and pd.notna(val):
                item[key] = round(float(val), 4)
        # 4종 모멘텀 점수
        for mp in ['6m', '6m1m', '12m', '12m1m']:
            col = f'mom_{mp}_s'
            val = row.get(col)
            if val is not None and pd.notna(val):
                item[f'mom_{mp}_s'] = round(float(val), 4)
        # 과열 캡 페널티 (FACTOR_OVERHEAT_W 활성 시) — 검증/디버깅용
        _op = row.get('overheat_pen')
        if _op is not None and pd.notna(_op):
            item['overheat_pen'] = round(float(_op), 4)
        # 최근 CA 페널티 발동 여부 (recent_ca=1 → 최근 K영업일내 무상증자/분할/병합)
        _rc = row.get('recent_ca')
        if _rc is not None and pd.notna(_rc) and int(_rc) != 0:
            item['recent_ca'] = int(_rc)
        # v80.20 mom_10_z / vol_low_z (가중치 그리드 BT용 — z 저장, score 재계산 가능)
        for _zc, _zk in [('mom_10_z', 'mom_10_z'), ('vol_low_z', 'vol_low_z')]:
            _zv = row.get(_zc)
            if _zv is not None and pd.notna(_zv):
                item[_zk] = round(float(_zv), 6)
        # v77.2: price NaN이면 가장 최근 유효 가격 사용 (ffill) — 거래정지 종목도 랭킹 포함
        if ticker in price_df.columns:
            ser = price_df[ticker]
            # base_ts 이하의 마지막 유효 가격
            valid = ser[(ser.index <= base_ts) & ser.notna() & (ser > 0)]
            if len(valid) > 0:
                item['price'] = int(valid.iloc[-1])
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
            'universe_count': len(universe_tickers),  # 시총+거래대금+금융제외 후 (MA120 전)
            'scored_count': len(scored),  # 모든 필터(+MA120+d'+e+스코어링) 통과
            'ma120_passed': len(ma120_pass) if 'ma120_pass' in dir() else None,  # MA120 통과 후
            'final_count': len(rankings_list),  # price 조건 통과 후 최종
            'generator': 'fast_generate_rankings_v2',
            'correlation_60d': corr_60d,
            'ma120_failed': ma120_fail,
            'value_overheat': _VALUE_OVERHEAT_BY_DATE.get(date_str, []),
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

    # 거래일 목록 — _full 우선
    ohlcv_files = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'))
    full_files = [f for f in ohlcv_files if '_full' in f.stem]
    if full_files:
        ohlcv_files = full_files
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
    prod_mode = os.environ.get('PRODUCTION_MODE', '0') == '1'
    preload_start = (pd.Timestamp(todo[0]) - pd.Timedelta(days=70)).strftime('%Y%m%d')
    preloaded = preload_all_data(preload_start, end_str, trading_dates=todo,
                                 use_rev_accel=use_rev_accel,
                                 use_gross_profit=use_gross_profit,
                                 production_mode=prod_mode)
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
