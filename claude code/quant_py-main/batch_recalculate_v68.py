"""
v68 전용 고속 재계산 스크립트

핵심 차이 (vs batch_recalculate.py):
- subprocess 아님 → 메모리에 데이터 유지
- FnGuide 재무제표: 한 번만 로드
- OHLCV: 전체 캐시에서 날짜별 슬라이싱 (forward-looking bias 제거)
- market_cap/fundamental: 날짜별 캐시 활용 (없으면 pykrx API)
- 예상 시간: 날짜당 30~60초, 24일 = 12~25분
"""
import sys, io, os, json, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta

# KRX 인증
import krx_auth
krx_auth.login()

from pykrx import stock as pykrx_stock
from zoneinfo import ZoneInfo
from data_collector import DataCollector
from fnguide_crawler import get_all_financial_statements, extract_magic_formula_data, get_consensus_batch
from error_handler import ErrorTracker, ErrorCategory
from strategy_b_multifactor import MultiFactorStrategy
from ranking_manager import save_ranking, load_ranking, get_available_ranking_dates
from create_current_portfolio import (
    apply_ma120_filter, filter_universe_optimized, get_broad_sector,
    KRX_SECTOR_MAP, EXCLUDE_KEYWORDS, run_strategy_b_scoring,
    MIN_MARKET_CAP, PREFILTER_N, N_STOCKS, SKIP_PREFILTER, CACHE_DIR
)

KST = ZoneInfo('Asia/Seoul')
STATE_DIR = Path(__file__).parent / 'state'
DATA_DIR = Path(CACHE_DIR)


def get_ranking_dates():
    """재계산 대상 날짜"""
    files = sorted(STATE_DIR.glob('ranking_*.json'))
    return [f.stem.split('_')[1] for f in files]


def load_fwd_per_from_originals(dates):
    """모든 날짜의 원본 ranking에서 FwdPER 수집 (git 원본 + 이미 재계산된 것 모두)"""
    fwd_map = {}  # {date: {ticker: fwd_per}}
    for d in dates:
        data = load_ranking(d)
        if data:
            date_fwd = {}
            for r in data.get('rankings', []):
                t = r.get('ticker', '')
                if t and r.get('fwd_per') is not None:
                    date_fwd[t] = r['fwd_per']
            fwd_map[d] = date_fwd
    return fwd_map


def build_consensus_from_fwd(tickers, fwd_map, target_date):
    """FwdPER 맵에서 consensus DataFrame 생성 (CONSENSUS_FROM_JSON 대체)"""
    # target_date 이하의 날짜에서 FwdPER 탐색 (최신 우선)
    all_dates = sorted(fwd_map.keys())
    search_dates = [d for d in all_dates if d <= target_date]

    ticker_fwd = {}
    for d in reversed(search_dates):
        for t, fwd in fwd_map[d].items():
            if t not in ticker_fwd:
                ticker_fwd[t] = fwd

    rows = [{'ticker': t, 'forward_per': ticker_fwd.get(t), 'has_consensus': t in ticker_fwd}
            for t in tickers]
    return pd.DataFrame(rows)


def main():
    start_time = datetime.now()
    dates = get_ranking_dates()

    if len(sys.argv) > 1:
        dates = [d for d in dates if d in sys.argv[1:]]

    print("=" * 70)
    print(f"v68 고속 재계산 — {len(dates)}일 ({dates[0]} ~ {dates[-1]})")
    print("=" * 70)

    collector = DataCollector(start_date='20150101', end_date='20261231')

    # =========================================================================
    # Phase 1: 공통 데이터 한 번만 로드
    # =========================================================================
    print("\n[Phase 1] 공통 데이터 로드")

    # 1-1. FwdPER 전체 수집 (원본 ranking에서)
    print("  FwdPER 수집 중...")
    fwd_map = load_fwd_per_from_originals(dates)
    total_fwd = sum(len(v) for v in fwd_map.values())
    print(f"  FwdPER: {len(fwd_map)}일, 총 {total_fwd}개 엔트리")

    # 1-2. OHLCV 전체 캐시 로드
    print("  OHLCV 캐시 로드 중...")
    ohlcv_files = sorted(DATA_DIR.glob('all_ohlcv_*.parquet'))
    if not ohlcv_files:
        print("  ERROR: OHLCV 캐시 없음! 먼저 create_current_portfolio.py를 한 번 실행하세요.")
        return False

    # 가장 넓은 범위 캐시 사용
    ohlcv_file = max(ohlcv_files, key=lambda f: f.stat().st_size)
    full_price_df = pd.read_parquet(ohlcv_file)
    print(f"  OHLCV: {ohlcv_file.name} ({len(full_price_df)}거래일, {len(full_price_df.columns)}종목)")

    # 1-3. FnGuide 재무제표 (한 번만)
    # 최신 날짜 기준 유니버스로 로드 (24일간 재무제표는 동일)
    print("  FnGuide 재무제표 로드 중...")
    latest_date = dates[-1]
    market_cap_latest = collector.get_market_cap(latest_date, market='ALL')
    all_tickers = market_cap_latest.index.tolist()
    fs_data = get_all_financial_statements(all_tickers, use_cache=True)
    print(f"  FnGuide: {len(fs_data)}개 종목 로드")

    # 1-4. KRX 섹터 (한 번만)
    sector_df = collector.get_krx_sector(latest_date)
    sector_map = {}
    if not sector_df.empty:
        code_col = '종목코드' if '종목코드' in sector_df.columns else sector_df.columns[0]
        sect_col = '업종명' if '업종명' in sector_df.columns else None
        if sect_col:
            for _, row in sector_df.iterrows():
                sector_map[str(row[code_col]).zfill(6)] = str(row[sect_col])
    print(f"  섹터: {len(sector_map)}개 종목")

    # =========================================================================
    # Phase 2: 날짜별 재계산
    # =========================================================================
    print(f"\n[Phase 2] 날짜별 재계산 ({len(dates)}일)")
    results = {}

    for i, date_str in enumerate(dates):
        t0 = time.time()
        print(f"\n--- [{i+1}/{len(dates)}] {date_str} ---")

        error_tracker = ErrorTracker(log_dir=Path("logs"), name=f"recalc_{date_str}")

        # 2-1. 시가총액 (날짜별 캐시)
        market_cap_df = collector.get_market_cap(date_str, market='ALL')

        # 2-2. 유니버스 필터링
        universe_df, ticker_names = filter_universe_optimized(collector, market_cap_df, error_tracker)
        universe_tickers = universe_df.index.tolist()

        # 2-3. 재무제표 → magic_df (날짜별 base_date로 추출)
        magic_df = extract_magic_formula_data(fs_data, base_date=date_str, use_ttm=True)

        # 자본잠식 제외
        if not magic_df.empty and '자본' in magic_df.columns:
            magic_df = magic_df[magic_df['자본'] > 0].copy()

        # 유니버스와 교집합
        magic_df = magic_df[magic_df['종목코드'].isin(universe_tickers)].copy()

        # 2-4. Fundamental (PER/PBR 실시간 — 날짜별 캐시)
        fundamental_df = collector.get_market_fundamental_batch(date_str)

        # 2-5. OHLCV 슬라이싱 (forward-looking bias 제거)
        base_ts = pd.Timestamp(datetime.strptime(date_str, '%Y%m%d'))
        price_df = full_price_df[full_price_df.index <= base_ts].copy()
        # 0원 행 제거
        if not price_df.empty:
            zero_rows = (price_df == 0).all(axis=1)
            price_df = price_df[~zero_rows]
            price_df = price_df.replace(0, np.nan)

        # 2-6. MA120 필터
        if not price_df.empty and not magic_df.empty:
            ma120_tickers, ma120_failed = apply_ma120_filter(price_df, magic_df['종목코드'].tolist())
            magic_df = magic_df[magic_df['종목코드'].isin(ma120_tickers)].copy()
        else:
            ma120_failed = []

        # 2-7. 사전필터 스킵 → 전체 멀티팩터
        prefiltered = magic_df.merge(
            universe_df[['시가총액', '종목명']],
            left_on='종목코드', right_index=True, how='left'
        )
        prefiltered['시가총액'] = prefiltered['시가총액'] / 100_000_000

        # 2-8. FwdPER 준비
        prefiltered_tickers = prefiltered['종목코드'].tolist()
        consensus_df = build_consensus_from_fwd(prefiltered_tickers, fwd_map, date_str)
        has_fwd = consensus_df['forward_per'].notna().sum()
        print(f"  FwdPER: {has_fwd}/{len(consensus_df)}개")

        # 2-9. 스코어링
        scored_b = run_strategy_b_scoring(
            prefiltered, fundamental_df, price_df, ticker_names, error_tracker,
            consensus_df=consensus_df,
            sector_map=sector_map
        )

        if scored_b.empty:
            print(f"  ❌ 스코어링 실패")
            continue

        # 2-10. 가중순위 계산
        prev_dates = sorted([d for d in dates if d < date_str])
        t1_date = prev_dates[-1] if len(prev_dates) >= 1 else None
        t2_date = prev_dates[-2] if len(prev_dates) >= 2 else None
        t1_data = load_ranking(t1_date) if t1_date else None
        t2_data = load_ranking(t2_date) if t2_date else None

        PENALTY = 50
        t1_map = {}
        if t1_data:
            for item in t1_data.get('rankings', []):
                t1_map[item['ticker']] = item.get('composite_rank', item['rank'])
        t2_map = {}
        if t2_data:
            for item in t2_data.get('rankings', []):
                t2_map[item['ticker']] = item.get('composite_rank', item['rank'])

        weighted_scores = []
        for _, row in scored_b.iterrows():
            ticker = str(row.get('종목코드', '')).zfill(6)
            r0 = int(row['멀티팩터_순위'])
            r1 = t1_map.get(ticker, PENALTY)
            r2 = t2_map.get(ticker, PENALTY)
            weighted_scores.append(r0 * 0.5 + r1 * 0.3 + r2 * 0.2)

        scored_b['가중순위_점수'] = weighted_scores
        scored_b = scored_b.sort_values('가중순위_점수')
        scored_b['통합순위'] = range(1, len(scored_b) + 1)

        # 2-11. JSON 저장
        rankings_list = []
        for _, row in scored_b.iterrows():
            entry = {
                'rank': int(row.get('통합순위', 999)),
                'composite_rank': int(row.get('멀티팩터_순위', 999)),
                'ticker': str(row.get('종목코드', '')).zfill(6),
                'name': str(row.get('종목명', '')),
                'score': round(float(row.get('멀티팩터_점수', 0)), 4) if pd.notna(row.get('멀티팩터_점수')) else 0,
                'sector': get_broad_sector(sector_map.get(str(row.get('종목코드', '')).zfill(6), '')),
            }
            for col, key in [('PER', 'per'), ('PBR', 'pbr'), ('ROE', 'roe'), ('forward_per', 'fwd_per')]:
                val = row.get(col)
                if val is not None and pd.notna(val):
                    entry[key] = round(float(val), 2)
            for col, key in [('밸류_점수', 'value_s'), ('퀄리티_점수', 'quality_s'), ('성장_점수', 'growth_s'), ('모멘텀_점수', 'momentum_s')]:
                val = row.get(col)
                if val is not None and pd.notna(val):
                    entry[key] = round(float(val), 4)
            ticker = entry['ticker']
            if not price_df.empty and ticker in price_df.columns:
                last_price = price_df[ticker].dropna()
                if not last_price.empty:
                    entry['price'] = int(last_price.iloc[-1])
            rankings_list.append(entry)

        # 상관관계
        corr_60d = {}
        top30_tickers = [r['ticker'] for r in rankings_list[:30]]
        valid_tickers = [t for t in top30_tickers if t in price_df.columns]
        if len(valid_tickers) >= 2 and len(price_df) >= 20:
            rets = price_df[valid_tickers].tail(60).pct_change().dropna()
            if len(rets) >= 20:
                corr_matrix = rets.corr()
                for ii in range(len(valid_tickers)):
                    for jj in range(ii + 1, len(valid_tickers)):
                        t1t, t2t = valid_tickers[ii], valid_tickers[jj]
                        c = corr_matrix.iloc[ii, jj]
                        if not pd.isna(c):
                            corr_60d['_'.join(sorted([t1t, t2t]))] = round(float(c), 3)

        save_ranking(date_str, rankings_list, metadata={
            'total_universe': len(universe_tickers),
            'prefilter_passed': len(prefiltered),
            'scored_count': len(scored_b),
            'version': '6.8',
            'correlation_60d': corr_60d,
            'ma120_failed': ma120_failed,
        })

        elapsed = time.time() - t0
        top3 = [r['name'] for r in rankings_list[:3]]
        print(f"  ✅ scored {len(scored_b)}개, Top3: {', '.join(top3)} ({elapsed:.0f}초)")
        results[date_str] = {'scored': len(scored_b), 'top3': top3, 'time': elapsed}

    # =========================================================================
    # Phase 3: 요약
    # =========================================================================
    total_time = (datetime.now() - start_time).total_seconds()
    print(f"\n{'='*70}")
    print(f"재계산 완료: {len(results)}/{len(dates)}일, 총 {total_time/60:.1f}분")
    print(f"{'='*70}")

    for d in dates:
        r = results.get(d)
        if r:
            print(f"  {d}: scored={r['scored']}, Top3={', '.join(r['top3'])}, {r['time']:.0f}초")
        else:
            print(f"  {d}: ❌ 실패")

    return len(results) == len(dates)


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
