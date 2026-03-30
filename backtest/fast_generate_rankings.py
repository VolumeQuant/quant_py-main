"""고속 과거 ranking 생성기 — 데이터 1회 로드 + 날짜별 in-memory 처리

create_current_portfolio.py를 subprocess로 매번 호출하는 대신,
모든 데이터를 메모리에 올려놓고 날짜별로 전략 클래스를 직접 호출.

속도: ~40초/일 → ~2-3초/일 (15-20배 향상)

Usage:
    python backtest/fast_generate_rankings.py 20250102 20250320
    python backtest/fast_generate_rankings.py 20250102 20250320 --state-dir state/bt_g50_50
    python backtest/fast_generate_rankings.py 20250102 20250320 --resume
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

CACHE_DIR = PROJECT_ROOT / 'data_cache'


def preload_all_data(start_str, end_str):
    """모든 데이터 1회 로드"""
    print('=== 데이터 프리로드 ===')
    t0 = time.time()
    data = {}

    # 1. OHLCV (가장 긴 파일)
    ohlcv_files = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'))
    # 가장 이른 시작일 파일 선택
    ohlcv_files.sort(key=lambda f: f.stem.split('_')[2])
    ohlcv_file = ohlcv_files[0]
    print(f'  OHLCV: {ohlcv_file.name}')
    data['ohlcv'] = pd.read_parquet(ohlcv_file)
    print(f'    {data["ohlcv"].shape[0]}거래일 × {data["ohlcv"].shape[1]}종목')

    # 2. 날짜별 캐시 인덱스
    data['market_cap'] = {}  # date_str → DataFrame
    data['fundamentals'] = {}  # date_str → DataFrame
    data['sectors'] = {}  # date_str → dict(ticker→sector)

    from create_current_portfolio import get_broad_sector, KRX_SECTOR_MAP, EXCLUDE_KEYWORDS

    # 캐시 인덱스: end_str 이하 모든 파일 (분기별 스냅샷 커버)
    for f in sorted(CACHE_DIR.glob('market_cap_ALL_*.parquet')):
        d = f.stem.split('_')[-1]
        if d <= end_str:
            data['market_cap'][d] = f  # lazy load (경로만 저장)

    for f in sorted(CACHE_DIR.glob('fundamental_batch_ALL_*.parquet')):
        d = f.stem.split('_')[-1]
        if d <= end_str:
            data['fundamentals'][d] = f

    for f in sorted(CACHE_DIR.glob('krx_sector_*.parquet')):
        d = f.stem.split('_')[-1]
        if d <= end_str:
            data['sectors'][d] = f

    print(f'  market_cap: {len(data["market_cap"])}일')
    print(f'  fundamentals: {len(data["fundamentals"])}일')
    print(f'  sectors: {len(data["sectors"])}일')

    # 3. 재무제표 (전체 종목, 1회 로드)
    print('  재무제표 로드 중...')
    data['fs'] = {}
    for prefix in ['fs_dart_', 'fs_fnguide_']:
        for f in CACHE_DIR.glob(f'{prefix}*.parquet'):
            ticker = f.stem.replace(prefix, '')
            if ticker not in data['fs']:  # DART 우선
                try:
                    df = pd.read_parquet(f)
                    if not df.empty:
                        data['fs'][ticker] = df
                except Exception:
                    pass
    print(f'    {len(data["fs"])}종목 로드')

    # 4. 종목명 캐시 (JSON 캐시 우선 → pykrx 폴백)
    print('  종목명 빌드...')
    data['ticker_names'] = {}
    import json
    names_cache = CACHE_DIR / 'ticker_names_cache.json'
    if names_cache.exists():
        with open(names_cache, 'r', encoding='utf-8') as f:
            data['ticker_names'] = json.load(f)
        print(f'    캐시에서 {len(data["ticker_names"])}종목 로드')
    else:
        try:
            latest_mcap_file = sorted(CACHE_DIR.glob('market_cap_ALL_*.parquet'))[-1]
            latest_mcap = pd.read_parquet(latest_mcap_file)
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

    elapsed = time.time() - t0
    print(f'  프리로드 완료: {elapsed:.1f}초')
    return data


def find_nearest_cache(cache_dict, target_date, max_gap_days=120):
    """target_date 이하에서 가장 가까운 캐시 찾기

    2022-2024는 분기별 스냅샷(3개월 간격)만 있으므로 max_gap_days=120.
    """
    # 정렬된 키에서 역순 검색 (가장 가까운 과거부터)
    candidates = sorted([d for d in cache_dict.keys() if d <= target_date], reverse=True)
    if not candidates:
        return None
    best = candidates[0]
    gap = (pd.Timestamp(target_date) - pd.Timestamp(best)).days
    if gap > max_gap_days:
        return None
    return cache_dict[best]


def generate_ranking_for_date(date_str, preloaded, state_dir):
    """단일 날짜 ranking 생성 (in-memory)"""
    from fnguide_crawler import extract_magic_formula_data
    from strategy_b_multifactor import MultiFactorStrategy
    from ranking_manager import save_ranking
    from create_current_portfolio import (
        apply_ma120_filter, get_broad_sector, EXCLUDE_KEYWORDS,
        _check_data_mismatch
    )

    ohlcv = preloaded['ohlcv']
    base_ts = pd.Timestamp(date_str)

    # --- 1. Market Cap ---
    mcap_path = find_nearest_cache(preloaded['market_cap'], date_str)
    if mcap_path is None:
        return False, 'no market_cap'
    mcap_df = pd.read_parquet(mcap_path)
    mcap_df['시가총액_억'] = mcap_df['시가총액'] / 1e8

    # 시총 필터
    filtered = mcap_df[mcap_df['시가총액_억'] >= 1000].copy()

    # --- 2. 거래대금 (20일 평균, market_cap 캐시에서) ---
    from datetime import datetime, timedelta
    cutoff = (datetime.strptime(date_str, '%Y%m%d') - timedelta(days=60)).strftime('%Y%m%d')
    vol_files = []
    for d, f in sorted(preloaded['market_cap'].items()):
        if cutoff <= d <= date_str:
            vol_files.append(f)
    vol_files = vol_files[-20:]

    has_real_volume = False
    if vol_files:
        vol_dfs = []
        for f in vol_files:
            try:
                vf = pd.read_parquet(f, columns=['거래대금'])
                vol_dfs.append(vf['거래대금'])
            except Exception:
                pass
        if vol_dfs:
            combined = pd.concat(vol_dfs, axis=1)
            avg_vol = combined.mean(axis=1) / 1e8
            filtered = filtered.join(pd.DataFrame({'avg_tv': avg_vol}), how='left')
            filtered['avg_tv'] = filtered['avg_tv'].fillna(filtered['거래대금'] / 1e8)
            has_real_volume = (filtered['avg_tv'] > 0).sum() > len(filtered) * 0.1
        else:
            filtered['avg_tv'] = filtered['거래대금'] / 1e8
    else:
        filtered['avg_tv'] = filtered['거래대금'] / 1e8

    if has_real_volume:
        large = filtered[filtered['시가총액_억'] >= 10000]
        mid = filtered[filtered['시가총액_억'] < 10000]
        pass_large = large[large['avg_tv'] >= 50]
        pass_mid = mid[mid['avg_tv'] >= 20]
        filtered = pd.concat([pass_large, pass_mid])
    else:
        # 역산 파일(거래대금=0): 시가총액만으로 유동성 프록시
        # 대형(1조+) 전부 통과, 중소형(1000억~1조)은 3000억+ 통과
        large = filtered[filtered['시가총액_억'] >= 10000]
        mid = filtered[(filtered['시가총액_억'] >= 3000) & (filtered['시가총액_억'] < 10000)]
        filtered = pd.concat([large, mid])

    # --- 3. 종목명 + 금융 제외 ---
    tnames = preloaded['ticker_names']
    filtered['종목명'] = filtered.index.map(lambda t: tnames.get(t, t))
    # 금융업/지주사 제외
    exclude_mask = filtered['종목명'].apply(
        lambda n: any(kw in str(n) for kw in EXCLUDE_KEYWORDS)
    )
    filtered = filtered[~exclude_mask]
    universe_tickers = filtered.index.tolist()

    if len(universe_tickers) < 10:
        return False, f'universe too small ({len(universe_tickers)})'

    # --- 4. 재무제표 → magic_df ---
    fs_data = {t: preloaded['fs'][t] for t in universe_tickers if t in preloaded['fs']}
    magic_df = extract_magic_formula_data(fs_data, base_date=date_str, use_ttm=True)
    if magic_df.empty:
        return False, 'no financial data'

    # 시가총액 병합
    magic_df = magic_df.merge(
        filtered[['시가총액', '종목명']],
        left_on='종목코드', right_index=True, how='left'
    )
    magic_df['시가총액'] = magic_df['시가총액'] / 1e8

    # 자본잠식 제외
    if '자본' in magic_df.columns:
        magic_df = magic_df[magic_df['자본'] > 0].copy()

    # --- 5. Fundamentals — 제거됨 (PER/PBR은 DART 기반으로 strategy_b에서 계산) ---

    # --- 6. OHLCV → MA120, 모멘텀 ---
    price_df = ohlcv[ohlcv.index <= base_ts].copy()
    price_df = price_df.replace(0, np.nan)  # 거래정지 0원 → NaN

    # MA120 필터 (반환: (passed_list, failed_list))
    ma120_result = apply_ma120_filter(price_df, magic_df['종목코드'].tolist())
    ma120_pass = ma120_result[0] if isinstance(ma120_result, tuple) else ma120_result
    if not ma120_pass:
        return False, 'MA120 filter: 0 passed'
    magic_df = magic_df[magic_df['종목코드'].isin(ma120_pass)].copy()

    # --- 7. 섹터 맵 (raw 업종명, get_broad_sector는 JSON 저장 시만 적용) ---
    sector_path = find_nearest_cache(preloaded['sectors'], date_str)
    sector_map = {}
    if sector_path is not None:
        sec_df = pd.read_parquet(sector_path)
        col_code = sec_df.columns[0]  # 종목코드
        col_sector = sec_df.columns[1]  # 업종명
        for _, row in sec_df.iterrows():
            sector_map[row[col_code]] = str(row[col_sector])

    # --- 8. 전략 실행 ---
    multifactor_df = magic_df.copy()
    multifactor_df['종목명'] = multifactor_df['종목코드'].map(tnames)

    # PER/PBR: DART 재무 + 시가총액으로 strategy_b에서 직접 계산

    strategy = MultiFactorStrategy()
    os.environ['DISABLE_FWD_BONUS'] = '1'
    mom_period = os.environ.get('MOM_PERIOD', '6m')
    selected, scored = strategy.run(
        multifactor_df, price_df=price_df,
        n_stocks=len(multifactor_df), sector_map=sector_map,
        base_date=date_str, mom_period=mom_period
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
        # 팩터별 점수 (production과 동일 키명)
        for col, key in [('밸류_점수', 'value_s'), ('퀄리티_점수', 'quality_s'),
                         ('성장_점수', 'growth_s'), ('모멘텀_점수', 'momentum_s')]:
            val = row.get(col)
            if val is not None and pd.notna(val):
                item[key] = round(float(val), 4)
        # Growth 서브팩터 z-score (G-ratio 백테스트용)
        for col, key in [('매출성장률_z', 'rev_z'), ('이익변화량_z', 'oca_z')]:
            val = row.get(col)
            if val is not None and pd.notna(val):
                item[key] = round(float(val), 4)
        # 가격 (없으면 매매 불가 → 제외)
        if ticker in price_df.columns and base_ts in price_df.index:
            p = price_df.loc[base_ts, ticker]
            if pd.notna(p) and p > 0:
                item['price'] = int(p)
        if 'price' not in item:
            continue  # 상폐/거래정지 종목 제외
        rankings_list.append(item)

    # ranking JSON 직접 저장 (ranking_manager reload 대신)
    ranking_data = {
        'date': date_str,
        'generated_at': pd.Timestamp.now(tz='Asia/Seoul').isoformat(),
        'rankings': rankings_list,
        'metadata': {
            'universe_count': len(universe_tickers),
            'scored_count': len(scored),
            'generator': 'fast_generate_rankings',
        },
    }
    out_path = state_dir / f'ranking_{date_str}.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(ranking_data, f, ensure_ascii=False, indent=2)

    return True, f'{len(rankings_list)}종목'


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = [a for a in sys.argv[1:] if a.startswith('--')]

    if len(args) < 2:
        print('사용법: python backtest/fast_generate_rankings.py START END [--state-dir DIR] [--resume]')
        print('예: python backtest/fast_generate_rankings.py 20250102 20250320')
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

    # 캐시 디렉토리 오버라이드
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

    # 프리로드
    # 시작 60일 전부터 캐시 필요 (거래대금 20일 평균)
    preload_start = (pd.Timestamp(todo[0]) - pd.Timedelta(days=70)).strftime('%Y%m%d')
    preloaded = preload_all_data(preload_start, end_str)

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
            if (idx + 1) % 10 == 0 or idx == 0:
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
