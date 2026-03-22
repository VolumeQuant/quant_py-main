"""한국 주식 퀀트 전략 비교 백테스트 프레임워크

ranking JSON + OHLCV 데이터 기반으로 현행 전략과 개선안을 A/B 비교.
반드시 "현행 전략(기준선) vs 개선안" 구조로 비교.

Usage:
    python backtest/backtest_compare.py              # 프리셋 목록 출력
    python backtest/backtest_compare.py baseline      # 현행 전략 단독
    python backtest/backtest_compare.py sizing        # 동일비중 vs 역변동성
    python backtest/backtest_compare.py stop_loss     # 손절 방식 비교
    python backtest/backtest_compare.py all           # 전체 프리셋 실행
"""
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent
STATE_DIR = PROJECT_ROOT / 'state'


# ── 공통 유틸 ──

def _fmt_date(d):
    """YYYYMMDD → YYYY-MM-DD"""
    return f'{d[:4]}-{d[4:6]}-{d[6:]}'


def calc_ticker_vol(price_history, ticker, lookback=10):
    """종목의 최근 N일 일간수익률 표준편차 (일간%, 연환산X)

    역변동성 비중 계산용. 변동성이 클수록 비중을 줄인다.
    """
    hist = price_history.get(ticker, [])
    if len(hist) < 3:
        return None
    prices = hist[-(lookback + 1):] if len(hist) >= lookback + 1 else hist
    rets = []
    for j in range(1, len(prices)):
        if prices[j - 1] > 0:
            rets.append((prices[j] - prices[j - 1]) / prices[j - 1] * 100)
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) if var > 0 else None


def _calc_inverse_vol_return(tk_rets, price_history, vol_lookback):
    """역변동성 비중 일간 수익률

    변동성 높은 종목 → 낮은 비중, 변동성 낮은 종목 → 높은 비중.
    vol 계산 불가 종목은 동일비중 fallback.
    """
    inv_vols = {}
    for tk in tk_rets:
        vol = calc_ticker_vol(price_history, tk, vol_lookback)
        inv_vols[tk] = 1.0 / vol if vol and vol > 0 else None

    has_vol = {tk: iv for tk, iv in inv_vols.items() if iv is not None}
    no_vol = [tk for tk, iv in inv_vols.items() if iv is None]

    if not has_vol:
        return sum(tk_rets.values()) / len(tk_rets)

    total_inv = sum(has_vol.values())
    if no_vol:
        n_total = len(tk_rets)
        no_vol_weight = 1.0 / n_total
        remaining = 1.0 - no_vol_weight * len(no_vol)
        weights = {tk: no_vol_weight for tk in no_vol}
        for tk, iv in has_vol.items():
            weights[tk] = (iv / total_inv) * remaining
    else:
        weights = {tk: iv / total_inv for tk, iv in has_vol.items()}

    return sum(tk_rets[tk] * weights[tk] for tk in tk_rets)


# ── 데이터 로드 ──

def load_data(state_dir=None, state_dirs=None):
    """ranking JSON + OHLCV 1회 로드

    Args:
        state_dir: ranking JSON 디렉토리 (None이면 기본 STATE_DIR)
        state_dirs: 여러 디렉토리 리스트 (state_dir보다 우선)

    Returns:
        dict with keys: ranking_dates, rankings, rank_maps, score_maps,
                        item_maps, all_prices, ohlcv_df
    """
    # 1. 랭킹 JSON 로드 (다중 디렉토리 지원)
    if state_dirs:
        rdirs = [Path(d) for d in state_dirs]
    else:
        rdirs = [Path(state_dir) if state_dir else STATE_DIR]

    rankings = {}
    for rdir in rdirs:
        if not rdir.exists():
            print(f'경고: {rdir} 없음, 스킵')
            continue
        for f in sorted(rdir.glob('ranking_*.json')):
            date_str = f.stem.replace('ranking_', '')
            if len(date_str) == 8 and date_str.isdigit():
                with open(f, 'r', encoding='utf-8') as fp:
                    rankings[date_str] = json.load(fp)

    ranking_dates = sorted(rankings.keys())
    if not ranking_dates:
        raise ValueError('랭킹 데이터 없음')
    print(f'랭킹: {len(ranking_dates)}거래일 ({ranking_dates[0]}~{ranking_dates[-1]})')

    # 2. 사전 빌드: 순위/점수/종목 맵
    rank_maps = {}   # {date: {ticker: composite_rank}}
    score_maps = {}  # {date: {ticker: raw_score}}
    item_maps = {}   # {date: {ticker: full_item_dict}}
    for d, data in rankings.items():
        rlist = data.get('rankings', [])
        rank_maps[d] = {r['ticker']: r.get('composite_rank', r['rank']) for r in rlist}
        score_maps[d] = {r['ticker']: r.get('score', 0) for r in rlist}
        item_maps[d] = {r['ticker']: r for r in rlist}

    # 3. OHLCV 로드 (가장 긴 기간 파일 — 시작일이 가장 이른 것 선택)
    ohlcv_files = list((PROJECT_ROOT / 'data_cache').glob('all_ohlcv_*.parquet'))
    if not ohlcv_files:
        raise FileNotFoundError('OHLCV 파일 없음')
    ohlcv_files.sort(key=lambda f: f.stem.split('_')[2])  # 시작일 기준 정렬
    ohlcv_df = pd.read_parquet(ohlcv_files[0])  # 가장 이른 시작일
    ohlcv_date_map = {dt.strftime('%Y%m%d'): dt for dt in ohlcv_df.index}
    print(f'OHLCV: {ohlcv_df.shape[0]}거래일, {ohlcv_df.shape[1]}종목')

    # 4. 가격 맵 빌드 (랭킹 날짜 기준)
    #    OHLCV 우선, 없으면 랭킹 JSON의 price 필드 fallback
    all_prices = {}
    for d in ranking_dates:
        prices = {}
        if d in ohlcv_date_map:
            row = ohlcv_df.loc[ohlcv_date_map[d]]
            for tk, p in row.items():
                if pd.notna(p) and p > 0:
                    prices[tk] = float(p)
        # 랭킹 JSON fallback (OHLCV에 없는 종목 보완)
        for item in rankings[d].get('rankings', []):
            tk = item['ticker']
            if tk not in prices and item.get('price') and item['price'] > 0:
                prices[tk] = float(item['price'])
        all_prices[d] = prices

    # 5. OHLCV 전체 가격 맵 (역변동성 히스토리용)
    ohlcv_prices = {}
    for dt in ohlcv_df.index:
        d = dt.strftime('%Y%m%d')
        row = ohlcv_df.loc[dt]
        ohlcv_prices[d] = {tk: float(p) for tk, p in row.items() if pd.notna(p) and p > 0}
    ohlcv_trading_days = sorted(ohlcv_prices.keys())

    # 6. 벤치마크: 일간수익률 (랭킹 날짜 기준)
    ohlcv_clean = ohlcv_df.replace(0, float('nan'))
    daily_pct = ohlcv_clean.pct_change(fill_method=None) * 100
    daily_pct = daily_pct.clip(-50, 50)  # 극단값 제거

    # (a) 전체 유니버스 동일가중
    market_daily = daily_pct.mean(axis=1)
    benchmark_rets = {}
    for dt in ohlcv_df.index:
        d = dt.strftime('%Y%m%d')
        val = market_daily.loc[dt]
        if pd.notna(val):
            benchmark_rets[d] = float(val)

    # (b) KOSPI/KOSDAQ 실제 지수 (yfinance로 사전 수집)
    idx_file = PROJECT_ROOT / 'data_cache' / 'index_benchmarks.parquet'
    kospi_rets = {}
    kosdaq_rets = {}
    if idx_file.exists():
        idx_df = pd.read_parquet(idx_file)
        for col, target in [('kospi', kospi_rets), ('kosdaq', kosdaq_rets)]:
            if col in idx_df.columns:
                s = idx_df[col].dropna()
                pct = s.pct_change() * 100
                pct = pct.clip(-15, 15)
                for dt in pct.index:
                    d = dt.strftime('%Y%m%d')
                    if pd.notna(pct.loc[dt]):
                        target[d] = float(pct.loc[dt])

    return {
        'ranking_dates': ranking_dates,
        'rankings': rankings,
        'rank_maps': rank_maps,
        'score_maps': score_maps,
        'item_maps': item_maps,
        'all_prices': all_prices,
        'ohlcv_prices': ohlcv_prices,
        'ohlcv_trading_days': ohlcv_trading_days,
        'benchmark_rets': benchmark_rets,
        'kospi_rets': kospi_rets,
        'kosdaq_rets': kosdaq_rets,
    }


# ── G-ratio 재스코어링 ──

def apply_g_ratio(db, rev_weight):
    """G-ratio 재스코어링: growth = rev_z * w + oca_z * (1-w)

    ranking JSON에 저장된 rev_z/oca_z 서브팩터 z-score를 가중합산하여
    growth_s를 재계산하고, 전체 점수와 순위를 업데이트한다.

    Args:
        db: load_data() 결과
        rev_weight: 매출성장률 가중치 (0.0~1.0, 나머지=이익변화량)

    Returns:
        새로운 db dict (rank_maps, score_maps, item_maps만 교체)
    """
    W = 0.25  # 4팩터 동일가중
    oca_weight = 1.0 - rev_weight

    new_db = dict(db)  # shallow copy
    new_rank_maps = {}
    new_score_maps = {}
    new_item_maps = {}

    for d in db['ranking_dates']:
        old_items = db['item_maps'][d]

        # 1. 새 growth raw 계산
        growth_raw = {}
        for tk, item in old_items.items():
            rv = item.get('rev_z')
            ov = item.get('oca_z')
            if rv is not None and ov is not None:
                growth_raw[tk] = rv * rev_weight + ov * oca_weight

        if not growth_raw:
            # rev_z/oca_z 없으면 원본 유지
            new_rank_maps[d] = db['rank_maps'][d]
            new_score_maps[d] = db['score_maps'][d]
            new_item_maps[d] = old_items
            continue

        # 2. 재표준화: (raw - mean) / std → std=1
        vals = list(growth_raw.values())
        n = len(vals)
        mean_g = sum(vals) / n
        var_g = sum((v - mean_g) ** 2 for v in vals) / (n - 1) if n > 1 else 0
        std_g = math.sqrt(var_g) if var_g > 0 else 1.0

        # 3. 새 점수 계산 + 순위
        scored = []
        new_items = {}
        for tk, item in old_items.items():
            new_item = dict(item)  # shallow copy
            if tk in growth_raw:
                new_gs = (growth_raw[tk] - mean_g) / std_g
            else:
                new_gs = item.get('growth_s', 0)

            v = item.get('value_s', 0)
            q = item.get('quality_s', 0)
            m = item.get('momentum_s', 0)
            new_score = (v + q + new_gs + m) * W

            new_item['growth_s'] = new_gs
            new_item['score'] = new_score
            scored.append((tk, new_score))
            new_items[tk] = new_item

        # 점수 내림차순 정렬 → 순위 부여
        scored.sort(key=lambda x: -x[1])
        new_rm = {}
        new_sm = {}
        for rank, (tk, score) in enumerate(scored, 1):
            new_rm[tk] = rank
            new_sm[tk] = score
            new_items[tk]['composite_rank'] = rank
            new_items[tk]['rank'] = rank

        new_rank_maps[d] = new_rm
        new_score_maps[d] = new_sm
        new_item_maps[d] = new_items

    new_db['rank_maps'] = new_rank_maps
    new_db['score_maps'] = new_score_maps
    new_db['item_maps'] = new_item_maps
    return new_db


# ── 백테스트 엔진 ──

def run_backtest(db, config):
    """전략 변형 백테스트 실행

    config keys:
        label: str            — 전략 이름 (표시용)
        top_n: int            — 진입 순위 기준 (weighted_rank <= top_n, default 20)
        exit_rank: int        — 이탈 순위 기준 (weighted_rank > exit_rank, default 20)
        entry_score: float    — 진입 시 score_100 최소 기준 (default 72)
        exit_score: float     — 이탈 시 score_100 기준 (미만이면 이탈, default 68)
        exit_mode: str        — 'both' (순위+점수, 기본), 'rank_only', 'score_only'
        max_positions: int    — 최대 동시 보유 종목수 (default 20)
        require_3day: bool    — 3일 교집합 필요 여부 (default True)
        fixed_stop: float     — 고정 손절선 (%, 진입가 대비, e.g. -10, None=미사용)
        trailing_stop: float  — 트레일링스탑 (%, 고점 대비, e.g. -8, None=미사용)
        sizing: str           — 'equal' (동일비중) or 'inverse_vol' (역변동성)
        vol_lookback: int     — 역변동성 계산 기간 (default 5)
        max_per_sector: int   — 섹터당 최대 종목수 (None=무제한)
        max_dd_cash: float    — 포트폴리오 MDD 초과 시 전량 현금화 (e.g. -20, None=미사용)
        exclude_tickers: list — 제외할 종목 (LOO 테스트용, e.g. ['000660'])

    Returns:
        (daily_returns, trade_log, portfolio, bench_daily, kospi_daily, kosdaq_daily)
    """
    ranking_dates = db['ranking_dates']
    rank_maps = db['rank_maps']
    score_maps = db['score_maps']
    all_prices = db['all_prices']
    ohlcv_prices = db['ohlcv_prices']
    ohlcv_trading_days = db['ohlcv_trading_days']
    benchmark_rets = db.get('benchmark_rets', {})
    kospi_rets = db.get('kospi_rets', {})
    kosdaq_rets = db.get('kosdaq_rets', {})

    # Config 파라미터
    top_n = config.get('top_n', 20)
    exit_rank = config.get('exit_rank', 20)
    entry_score = config.get('entry_score', 72)
    exit_score = config.get('exit_score', 68)
    max_pos = config.get('max_positions', 20)
    require_3day = config.get('require_3day', True)
    fixed_stop = config.get('fixed_stop', None)
    trailing_stop = config.get('trailing_stop', None)
    sizing = config.get('sizing', 'equal')
    vol_lookback = config.get('vol_lookback', 5)
    max_per_sector = config.get('max_per_sector', None)
    exit_mode = config.get('exit_mode', 'both')  # 'both', 'rank_only', 'score_only'
    max_dd_cash = config.get('max_dd_cash', None)
    exclude_tickers = set(config.get('exclude_tickers', []))

    item_maps = db['item_maps']

    if len(ranking_dates) < 3:
        print('랭킹 데이터 3일 미만 — 백테스트 불가')
        return [], [], {}, [], [], []

    # 역변동성용 가격 히스토리 (랭킹 시작 전 OHLCV 데이터)
    price_history = defaultdict(list)
    start_date = ranking_dates[2]  # 3일 데이터 필요
    for d in ohlcv_trading_days:
        if d >= start_date:
            break
        for tk, p in ohlcv_prices.get(d, {}).items():
            price_history[tk].append(p)

    portfolio = {}   # {ticker: {entry_date, entry_price, peak_price, sector}}
    trade_log = []
    daily_returns = []

    # MDD 현금화 상태
    in_cash = False       # max_dd_cash 트리거 시 True
    cash_cooldown = 0     # 현금화 후 쿨다운 카운터
    CASH_COOLDOWN = 10    # 현금화 후 10거래일 쿨다운
    port_cum = 1.0        # 포트폴리오 누적 NAV
    port_peak = 1.0       # 포트폴리오 고점

    # 백테스트 기간: 3번째 랭킹 날짜부터
    bt_dates = ranking_dates[2:]
    prev_date = ranking_dates[1]  # 수익률 계산용 전일
    date_idx = {d: i for i, d in enumerate(ranking_dates)}

    for day in bt_dates:
        prices = all_prices.get(day, {})
        prev_prices = all_prices.get(prev_date, {})

        # ── 1. 일간 수익률 (거래 전, 기존 포지션 기준) ──
        if portfolio and prev_prices and not in_cash:
            tk_rets = {}
            for tk in portfolio:
                cur = prices.get(tk)
                prev = prev_prices.get(tk)
                if cur and prev and prev > 0:
                    tk_rets[tk] = (cur - prev) / prev * 100

            if not tk_rets:
                daily_ret = 0
            elif sizing == 'inverse_vol' and len(tk_rets) > 1:
                daily_ret = _calc_inverse_vol_return(tk_rets, price_history, vol_lookback)
            else:
                daily_ret = sum(tk_rets.values()) / len(tk_rets)
        else:
            daily_ret = 0

        daily_returns.append(daily_ret)

        # MDD 현금화 체크
        port_cum *= (1 + daily_ret / 100)
        if port_cum > port_peak:
            port_peak = port_cum
        port_dd = (port_cum - port_peak) / port_peak * 100

        if max_dd_cash is not None:
            if not in_cash and port_dd <= max_dd_cash:
                # 전량 청산 → 현금 전환 + 쿨다운 시작
                in_cash = True
                cash_cooldown = CASH_COOLDOWN
                for tk in list(portfolio.keys()):
                    cur = prices.get(tk, portfolio[tk]['entry_price'])
                    ret = (cur - portfolio[tk]['entry_price']) / portfolio[tk]['entry_price'] * 100
                    trade_log.append({
                        'ticker': tk, 'entry_date': _fmt_date(portfolio[tk]['entry_date']),
                        'exit_date': _fmt_date(day),
                        'entry_price': portfolio[tk]['entry_price'],
                        'exit_price': cur, 'return': ret, 'reason': 'MDD현금화',
                    })
                portfolio.clear()
            elif in_cash:
                cash_cooldown -= 1
                if cash_cooldown <= 0:
                    # 쿨다운 완료 → 재진입 허용, 고점 리셋
                    in_cash = False
                    port_peak = port_cum  # 새 기준점에서 시작

        # ── 2. 가격 히스토리 갱신 (역변동성용) ──
        for tk, p in prices.items():
            price_history[tk].append(p)

        # ── 3. 고점 갱신 (트레일링스탑용) ──
        for tk in portfolio:
            cur = prices.get(tk)
            if cur and cur > portfolio[tk]['peak_price']:
                portfolio[tk]['peak_price'] = cur

        # ── 4. 이탈 체크: 손절선 (매일 체크) ──
        stop_exits = []
        for tk in list(portfolio.keys()):
            cur = prices.get(tk)
            if cur is None:
                stop_exits.append((tk, '가격없음'))
                continue
            entry_p = portfolio[tk]['entry_price']
            peak_p = portfolio[tk]['peak_price']
            ret_from_entry = (cur - entry_p) / entry_p * 100
            ret_from_peak = (cur - peak_p) / peak_p * 100

            if trailing_stop is not None and ret_from_peak <= trailing_stop:
                stop_exits.append((tk, f'트레일링{trailing_stop}%'))
            elif fixed_stop is not None and ret_from_entry <= fixed_stop:
                stop_exits.append((tk, '손절'))

        stopped_tickers = set()
        for tk, reason in stop_exits:
            cur = prices.get(tk, portfolio[tk]['entry_price'])
            ret = (cur - portfolio[tk]['entry_price']) / portfolio[tk]['entry_price'] * 100
            trade_log.append({
                'ticker': tk, 'entry_date': _fmt_date(portfolio[tk]['entry_date']),
                'exit_date': _fmt_date(day),
                'entry_price': portfolio[tk]['entry_price'],
                'exit_price': cur, 'return': ret, 'reason': reason,
            })
            stopped_tickers.add(tk)
            del portfolio[tk]

        # ── 5. 이탈 체크: 순위/점수 기반 (랭킹 날짜만) ──
        rd_idx = date_idx[day]
        r_t0 = ranking_dates[rd_idx]
        r_t1 = ranking_dates[rd_idx - 1] if rd_idx >= 1 else None
        r_t2 = ranking_dates[rd_idx - 2] if rd_idx >= 2 else None

        # 가중순위 & score_100 계산
        all_tickers_today = set(rank_maps[r_t0].keys())
        weighted_ranks = {}
        scores_100 = {}

        for tk in all_tickers_today:
            # 가중순위: T0×0.5 + T1×0.3 + T2×0.2
            rk0 = rank_maps[r_t0].get(tk, 999)
            rk1 = rank_maps.get(r_t1, {}).get(tk, 999) if r_t1 else 999
            rk2 = rank_maps.get(r_t2, {}).get(tk, 999) if r_t2 else 999
            weighted_ranks[tk] = rk0 * 0.5 + rk1 * 0.3 + rk2 * 0.2

            # score_100: (weighted_score + 0.7) / 2.4 × 100
            s0 = score_maps[r_t0].get(tk, 0)
            s1 = score_maps.get(r_t1, {}).get(tk, 0) if r_t1 else 0
            s2 = score_maps.get(r_t2, {}).get(tk, 0) if r_t2 else 0
            ws = s0 * 0.5 + s1 * 0.3 + s2 * 0.2
            scores_100[tk] = max(0.0, min(100.0, (ws + 0.7) / 2.4 * 100))

        # 순위/점수 기반 이탈 (exit_mode: both/rank_only/score_only)
        rank_exits = []
        for tk in list(portfolio.keys()):
            if tk in stopped_tickers:
                continue  # 이미 손절로 이탈
            wr = weighted_ranks.get(tk, 999)
            sc = scores_100.get(tk, 0)
            if exit_mode in ('both', 'rank_only') and wr > exit_rank:
                rank_exits.append((tk, '순위밀림'))
            elif exit_mode in ('both', 'score_only') and sc < exit_score:
                rank_exits.append((tk, '점수하락'))

        for tk, reason in rank_exits:
            cur = prices.get(tk, portfolio[tk]['entry_price'])
            ret = (cur - portfolio[tk]['entry_price']) / portfolio[tk]['entry_price'] * 100
            trade_log.append({
                'ticker': tk, 'entry_date': _fmt_date(portfolio[tk]['entry_date']),
                'exit_date': _fmt_date(day),
                'entry_price': portfolio[tk]['entry_price'],
                'exit_price': cur, 'return': ret, 'reason': reason,
            })
            del portfolio[tk]

        # ── 6. 진입 (현금화 상태면 스킵) ──
        if in_cash:
            prev_date = day
            continue

        slots = max_pos - len(portfolio)
        if slots > 0:
            # 3일 교집합 (score_only 모드면 순위 필터 없이 전체 유니버스)
            if exit_mode == 'score_only':
                # 점수 기반만: 전체 유니버스에서 score 기준 진입
                if require_3day and r_t1 and r_t2:
                    # 3일 모두 존재하는 종목
                    set_t0 = set(rank_maps[r_t0].keys())
                    set_t1 = set(rank_maps.get(r_t1, {}).keys())
                    set_t2 = set(rank_maps.get(r_t2, {}).keys())
                    intersection = set_t0 & set_t1 & set_t2
                else:
                    intersection = set(rank_maps[r_t0].keys())
            else:
                if require_3day and r_t1 and r_t2:
                    top_t0 = {tk for tk, rk in rank_maps[r_t0].items() if rk <= top_n}
                    top_t1 = {tk for tk, rk in rank_maps.get(r_t1, {}).items() if rk <= top_n}
                    top_t2 = {tk for tk, rk in rank_maps.get(r_t2, {}).items() if rk <= top_n}
                    intersection = top_t0 & top_t1 & top_t2
                else:
                    intersection = {tk for tk, rk in rank_maps[r_t0].items() if rk <= top_n}

            # 섹터별 현재 보유 수 계산
            sector_count = defaultdict(int)
            for tk_held in portfolio:
                sec = portfolio[tk_held].get('sector', '')
                sector_count[sec] += 1

            # 후보: 교집합 내 + 조건 충족 + 미보유 + 제외 아닌 것
            candidates = []
            for tk in intersection:
                if tk in portfolio or tk in exclude_tickers:
                    continue
                # rank_only: 순위만 체크, score_only: 점수만 체크, both: 둘 다
                if exit_mode != 'rank_only' and scores_100.get(tk, 0) < entry_score:
                    continue
                if exit_mode == 'rank_only' and weighted_ranks.get(tk, 999) > top_n:
                    continue
                candidates.append((tk, weighted_ranks.get(tk, 999)))

            candidates.sort(key=lambda x: x[1])  # 가중순위 좋은 순

            entered = 0
            for tk, wr in candidates:
                if entered >= slots:
                    break
                cur = prices.get(tk)
                if not cur or cur <= 0:
                    continue
                # 섹터 집중도 제한
                tk_sector = item_maps.get(r_t0, {}).get(tk, {}).get('sector', '')
                if max_per_sector and tk_sector:
                    if sector_count[tk_sector] >= max_per_sector:
                        continue
                portfolio[tk] = {
                    'entry_date': day,
                    'entry_price': cur,
                    'peak_price': cur,
                    'sector': tk_sector,
                }
                sector_count[tk_sector] += 1
                entered += 1

        prev_date = day

    # 벤치마크 수익률 (백테스트 기간과 동일 날짜)
    bench_daily = []
    kospi_daily = []
    kosdaq_daily = []
    for day in bt_dates:
        bench_daily.append(benchmark_rets.get(day, 0))
        kospi_daily.append(kospi_rets.get(day, 0))
        kosdaq_daily.append(kosdaq_rets.get(day, 0))

    return daily_returns, trade_log, portfolio, bench_daily, kospi_daily, kosdaq_daily


# ── 출력 ──

def print_trades(trade_log, portfolio, all_prices, last_date, label):
    """거래 내역 + 미청산 + 이탈사유 요약"""
    print(f'\n--- {label} ---')
    for t in trade_log:
        status = '✅' if t['return'] > 0 else '❌'
        print(f"  {status} {t['ticker']:6s} {t['entry_date']}→{t['exit_date']} "
              f"{t['return']:+.1f}% [{t['reason']}]")

    if portfolio:
        last_prices = all_prices.get(last_date, {})
        parts = []
        for tk, pos in portfolio.items():
            cur = last_prices.get(tk, pos['entry_price'])
            ret = (cur - pos['entry_price']) / pos['entry_price'] * 100
            parts.append(f'{tk}({ret:+.1f}%)')
        print(f'  미청산: {", ".join(parts)}')

    if trade_log:
        reasons = defaultdict(list)
        for t in trade_log:
            reasons[t['reason']].append(t['return'])
        parts = [f'{r} {len(v)}건({sum(v)/len(v):+.1f}%)'
                 for r, v in sorted(reasons.items())]
        print(f'  이탈사유: {" | ".join(parts)}')


# ── 전략 프리셋 ──

# 현행 전략 기준선 (v69)
_BASELINE = {
    'label': '현행 전략',
    'top_n': 20,
    'exit_rank': 20,
    'entry_score': 72,
    'exit_score': 68,
    'max_positions': 20,
    'require_3day': True,
    'fixed_stop': None,
    'trailing_stop': None,
    'sizing': 'equal',
    'vol_lookback': 5,
}


def _cfg(**overrides):
    """기준선에 오버라이드 적용"""
    c = _BASELINE.copy()
    c.update(overrides)
    return c


PRESETS = {
    # === 현행 전략 단독 ===
    'baseline': [
        _BASELINE,
    ],

    # === 포지션 사이징 비교 ===
    'sizing': [
        _cfg(label='동일비중'),
        _cfg(label='역변동성(5일)', sizing='inverse_vol', vol_lookback=5),
        _cfg(label='역변동성(10일)', sizing='inverse_vol', vol_lookback=10),
        _cfg(label='역변동성(20일)', sizing='inverse_vol', vol_lookback=20),
    ],

    # === 손절 방식 비교 ===
    'stop_loss': [
        _cfg(label='현행(순위이탈)'),
        _cfg(label='트레일링-8%', trailing_stop=-8),
        _cfg(label='트레일링-12%', trailing_stop=-12),
        _cfg(label='트레일링-15%', trailing_stop=-15),
    ],

    # === 진입/이탈 기준 비교 ===
    'threshold': [
        _cfg(label='현행(72/68)'),
        _cfg(label='74/68', entry_score=74),
        _cfg(label='72/65', exit_score=65),
        _cfg(label='70/65', entry_score=70, exit_score=65),
    ],

    # === Top N 변형 ===
    'top_n': [
        _cfg(label='Top10(10/10)', top_n=10, exit_rank=10, max_positions=10),
        _cfg(label='Top15(15/15)', top_n=15, exit_rank=15, max_positions=15),
        _cfg(label='Top20(현행)', top_n=20, exit_rank=20, max_positions=20),
        _cfg(label='Top30(30/30)', top_n=30, exit_rank=30, max_positions=30),
    ],

    # === 진입/이탈 그리드 (확장) ===
    'score_grid': [
        _cfg(label='76/70', entry_score=76, exit_score=70),
        _cfg(label='74/70', entry_score=74, exit_score=70),
        _cfg(label='74/68', entry_score=74, exit_score=68),
        _cfg(label='72/68(현행)', entry_score=72, exit_score=68),
        _cfg(label='72/65', entry_score=72, exit_score=65),
        _cfg(label='70/65', entry_score=70, exit_score=65),
        _cfg(label='68/62', entry_score=68, exit_score=62),
    ],

    # === 3일 교집합 효과 ===
    'slow_in': [
        _cfg(label='3일교집합(현행)', require_3day=True),
        _cfg(label='즉시진입', require_3day=False),
    ],

    # === 섹터 집중도 제한 (Step 7) ===
    'sector': [
        _cfg(label='무제한(현행)'),
        _cfg(label='섹터당3개', max_per_sector=3),
        _cfg(label='섹터당2개', max_per_sector=2),
        _cfg(label='섹터당1개', max_per_sector=1),
    ],

    # === MDD 현금화 (Step 6) ===
    'dd_limit': [
        _cfg(label='무제한(현행)'),
        _cfg(label='MDD-15%현금화', max_dd_cash=-15),
        _cfg(label='MDD-20%현금화', max_dd_cash=-20),
        _cfg(label='MDD-25%현금화', max_dd_cash=-25),
    ],

    # === SK하이닉스 LOO (Leave-One-Out) ===
    'loo_skhynix': [
        _cfg(label='현행(전체)'),
        _cfg(label='현행(SK하닉제외)', exclude_tickers=['000660']),
        _cfg(label='+역변(전체)', sizing='inverse_vol', vol_lookback=5),
        _cfg(label='+역변(SK하닉제외)', sizing='inverse_vol', vol_lookback=5,
             exclude_tickers=['000660']),
        _cfg(label='+역변+74(전체)', sizing='inverse_vol', vol_lookback=5, entry_score=74),
        _cfg(label='+역변+74(SK하닉제외)', sizing='inverse_vol', vol_lookback=5,
             entry_score=74, exclude_tickers=['000660']),
    ],

    # === 집중 포트폴리오 (Top 3~20) ===
    'concentration': [
        _cfg(label='Top3(3/3)', top_n=3, exit_rank=3, max_positions=3),
        _cfg(label='Top4(4/4)', top_n=4, exit_rank=4, max_positions=4),
        _cfg(label='Top5(5/5)', top_n=5, exit_rank=5, max_positions=5),
        _cfg(label='Top10(10/10)', top_n=10, exit_rank=10, max_positions=10),
        _cfg(label='Top20(현행)', top_n=20, exit_rank=20, max_positions=20),
    ],

    # === 이탈 모드 비교: 순위 vs 점수 vs 둘다 ===
    'exit_mode': [
        _cfg(label='순위+점수(현행)', exit_mode='both'),
        _cfg(label='순위만', exit_mode='rank_only'),
        _cfg(label='점수만', exit_mode='score_only', max_positions=10),
        _cfg(label='점수만(74/68)', exit_mode='score_only', entry_score=74, max_positions=10),
        _cfg(label='점수만(76/70)', exit_mode='score_only', entry_score=76, exit_score=70, max_positions=10),
    ],

    # === 집중+점수기반 (Top3~5가 고정되는 패턴 검증) ===
    'focus': [
        _cfg(label='Top5+순위이탈', top_n=5, exit_rank=5, max_positions=5),
        _cfg(label='Top5+점수이탈', top_n=5, exit_rank=999, max_positions=5,
             exit_mode='score_only'),
        _cfg(label='Top3+순위이탈', top_n=3, exit_rank=3, max_positions=3),
        _cfg(label='Top3+점수이탈', top_n=3, exit_rank=999, max_positions=3,
             exit_mode='score_only'),
        _cfg(label='Top20(현행)'),
    ],

    # === 종합 최적 조합 (US 결과 참고) ===
    'best': [
        _cfg(label='현행(동일비중)'),
        _cfg(label='+역변동성', sizing='inverse_vol', vol_lookback=5),
        _cfg(label='+역변+섹터3', sizing='inverse_vol', vol_lookback=5, max_per_sector=3),
        _cfg(label='+역변+74진입', sizing='inverse_vol', vol_lookback=5, entry_score=74),
        _cfg(label='+역변+MDD-20%', sizing='inverse_vol', vol_lookback=5, max_dd_cash=-20),
        _cfg(label='+역변+섹터3+74', sizing='inverse_vol', vol_lookback=5,
             max_per_sector=3, entry_score=74),
    ],

    # === G-ratio 비교: 매출TTM vs 이익변화량 가중 비율 ===
    'g_ratio': [
        _cfg(label='G rev100:oca0', g_rev_weight=1.0),
        _cfg(label='G rev70:oca30', g_rev_weight=0.7),
        _cfg(label='G rev50:oca50', g_rev_weight=0.5),
        _cfg(label='G rev30:oca70', g_rev_weight=0.3),
        _cfg(label='G rev0:oca100', g_rev_weight=0.0),
    ],
}


def main():
    sys.path.insert(0, str(Path(__file__).parent))
    from bt_metrics import compare, report

    # CLI 인자 파싱
    args = sys.argv[1:]
    preset_name = None
    years = None

    for arg in args:
        if arg.startswith('--years='):
            years = arg.split('=')[1].split(',')
        elif not arg.startswith('--'):
            preset_name = arg

    # 데이터 로딩 (--years 지정 시 bt_YYYY 디렉토리에서)
    print('데이터 로딩...')
    if years:
        state_dirs = [STATE_DIR / f'bt_{y}' for y in years]
        # 프로덕션 state/ 디렉토리도 포함 (2026 등)
        if any(not d.exists() for d in state_dirs):
            missing = [str(d) for d in state_dirs if not d.exists()]
            print(f'경고: 누락 디렉토리: {", ".join(missing)}')
        db = load_data(state_dirs=[d for d in state_dirs if d.exists()])
    else:
        db = load_data()
    dates = db['ranking_dates']

    # 프리셋 선택
    if preset_name is None:
        print(f'\n사용 가능한 프리셋: {", ".join(PRESETS.keys())}, all')
        print('사용법: python backtest/backtest_compare.py [preset] [--years=2022,2023,...]')
        return

    if preset_name == 'all':
        presets_to_run = list(PRESETS.items())
    elif preset_name in PRESETS:
        presets_to_run = [(preset_name, PRESETS[preset_name])]
    else:
        print(f'알 수 없는 프리셋: {preset_name}')
        print(f'사용 가능: {", ".join(PRESETS.keys())}, all')
        return

    for name, strategies in presets_to_run:
        print(f'\n{"="*80}')
        print(f'  비교: {name}')
        print(f'{"="*80}')

        results = []
        bench_daily = None
        kospi_daily = None
        kosdaq_daily = None
        for cfg in strategies:
            # G-ratio 재스코어링: g_rev_weight가 설정된 경우 적용
            g_w = cfg.get('g_rev_weight')
            run_db = apply_g_ratio(db, g_w) if g_w is not None else db

            daily_rets, trades, port, bd, kd, kqd = run_backtest(run_db, cfg)
            results.append((cfg['label'], daily_rets, trades))
            print_trades(trades, port, run_db['all_prices'], dates[-1], cfg['label'])
            if bench_daily is None:
                bench_daily = bd
                kospi_daily = kd
                kosdaq_daily = kqd

        # 벤치마크 추가 (KOSPI + KOSDAQ)
        if kospi_daily:
            results.append(('BM:KOSPI', kospi_daily, None))
        if kosdaq_daily:
            results.append(('BM:KOSDAQ', kosdaq_daily, None))

        compare(results)

        # 각 전략 상세 리포트 (벤치마크 제외)
        for label, daily_rets, trades in results:
            if label.startswith('BM:'):
                continue
            report(daily_rets, trades, label=label)


if __name__ == '__main__':
    main()
