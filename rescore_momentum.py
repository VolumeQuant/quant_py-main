"""
경량 모멘텀 재채점 — 캐시 전용 (API 호출 0)

기존 ranking JSON의 V/Q/G 점수 유지, 모멘텀만 6M으로 재계산.
OHLCV 캐시에서 가격 데이터 로드 → 모멘텀 재계산 → 재순위 → JSON 저장.
"""

import json
import sys
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')
STATE_DIR = Path(__file__).parent / 'state'
CACHE_DIR = Path(__file__).parent / 'data_cache'

LOOKBACK_6M = 6 * 21  # 126 거래일
VOL_FLOOR = 15.0


def load_ohlcv_for_date(base_date: str) -> pd.DataFrame:
    """해당 날짜를 포함하는 OHLCV 캐시 로드"""
    target = pd.Timestamp(base_date)
    candidates = sorted(CACHE_DIR.glob("all_ohlcv_*.parquet"))

    best = None
    for f in candidates:
        parts = f.stem.split('_')  # all_ohlcv_YYYYMMDD_YYYYMMDD
        if len(parts) >= 4:
            end_date = pd.Timestamp(parts[3])
            if end_date >= target:
                best = f
                break

    if best is None and candidates:
        best = candidates[-1]

    if best is None:
        return pd.DataFrame()

    df = pd.read_parquet(best)
    # 해당 날짜까지만 자르기
    df = df[df.index <= target]
    # 0원 행 제거
    zero_rows = (df == 0).all(axis=1)
    if zero_rows.any():
        df = df[~zero_rows]
    df = df.replace(0, np.nan)
    return df


def calc_momentum_6m(price_df: pd.DataFrame, tickers: list) -> dict:
    """6M 리스크 조정 모멘텀 계산"""
    min_required = LOOKBACK_6M + 1
    result = {}

    for ticker in tickers:
        if ticker not in price_df.columns:
            continue
        prices = price_df[ticker].dropna()
        if len(prices) < min_required:
            continue
        try:
            price_current = prices.iloc[-1]
            price_6m_ago = prices.iloc[-(LOOKBACK_6M + 1)]
            if price_6m_ago <= 0:
                continue
            ret_6m = (price_current / price_6m_ago - 1) * 100
            daily_returns = prices.iloc[-(LOOKBACK_6M + 1):].pct_change().dropna()
            annual_vol = daily_returns.std() * np.sqrt(252) * 100
            annual_vol = max(annual_vol, VOL_FLOOR)
            result[ticker] = ret_6m / annual_vol
        except (IndexError, KeyError):
            continue

    return result


def winsorized_zscore(values: dict, lower=0.025, upper=0.975) -> dict:
    """Winsorized z-score 계산"""
    if len(values) < 5:
        return {k: 0.0 for k in values}

    s = pd.Series(values)
    q_lo, q_hi = s.quantile(lower), s.quantile(upper)
    clipped = s.clip(q_lo, q_hi)
    mean_val, std_val = clipped.mean(), clipped.std()
    if std_val == 0 or pd.isna(std_val):
        return {k: 0.0 for k in values}
    z = (clipped - mean_val) / std_val
    return z.to_dict()


def renormalize(scores: dict) -> dict:
    """카테고리 재표준화 (std=1)"""
    if not scores:
        return scores
    s = pd.Series(scores)
    mean_val, std_val = s.mean(), s.std()
    if std_val > 0:
        s = (s - mean_val) / std_val
    return s.to_dict()


def rescore_date(base_date: str, price_df: pd.DataFrame):
    """한 날짜의 ranking JSON을 모멘텀 6M으로 재채점"""
    ranking_path = STATE_DIR / f'ranking_{base_date}.json'
    if not ranking_path.exists():
        print(f"  [SKIP] {base_date}: ranking 파일 없음")
        return False

    with open(ranking_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    rankings = data.get('rankings', [])
    if not rankings:
        print(f"  [SKIP] {base_date}: 빈 ranking")
        return False

    tickers = [r['ticker'] for r in rankings]

    # 1. 6M 모멘텀 재계산
    momentum_raw = calc_momentum_6m(price_df, tickers)

    # 2. Winsorized z-score
    momentum_z = winsorized_zscore(momentum_raw)

    # 3. 카테고리 재표준화
    momentum_renorm = renormalize(momentum_z)

    # 4. 각 종목 업데이트
    updated = []
    for r in rankings:
        ticker = r['ticker']
        new_m = momentum_renorm.get(ticker)

        # 기존 V, Q 유지
        v = r.get('value_s', 0)
        q = r.get('quality_s', 0)

        if new_m is None:
            continue

        # 과락 체크: 3개 중 2개 이상 < -0.5
        scores = [v, q, new_m]
        fail_count = sum(1 for s in scores if s < -0.5)
        if fail_count >= 2:
            continue

        # 가중합 (V30 + Q35 + M35)
        composite = v * 0.30 + q * 0.35 + new_m * 0.35

        r['momentum_s'] = round(new_m, 4)
        r['score'] = round(composite, 4)
        # 종가 업데이트 (캐시에서)
        if ticker in price_df.columns:
            last_price = price_df[ticker].dropna()
            if not last_price.empty:
                r['price'] = int(last_price.iloc[-1])
        updated.append(r)

    # 5. 재순위 (composite_rank + rank)
    updated.sort(key=lambda x: x['score'], reverse=True)
    for i, r in enumerate(updated, 1):
        r['composite_rank'] = i
        r['rank'] = i  # 가중순위는 send_telegram에서 재계산

    # 6. 저장
    data['rankings'] = updated
    data['generated_at'] = datetime.now(KST).isoformat()
    if 'metadata' in data:
        data['metadata']['version'] = '6.0-rescore'
        data['metadata']['scored_count'] = len(updated)

    with open(ranking_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"  [OK] {base_date}: {len(updated)}개 종목 재채점 완료")
    return True


def main():
    dates = sys.argv[1:] if len(sys.argv) > 1 else []

    if not dates:
        # 모든 ranking 파일
        files = sorted(STATE_DIR.glob('ranking_*.json'))
        dates = [f.stem.replace('ranking_', '') for f in files]

    print(f"모멘텀 6M 재채점 — {len(dates)}개 날짜")
    print(f"데이터 소스: OHLCV 캐시 (API 호출 없음)")
    print("=" * 50)

    # OHLCV 캐시 프리로드 (가장 큰 파일)
    ohlcv_files = sorted(CACHE_DIR.glob("all_ohlcv_*.parquet"))
    if not ohlcv_files:
        print("ERROR: OHLCV 캐시 없음")
        return

    success = 0
    for date_str in dates:
        price_df = load_ohlcv_for_date(date_str)
        if price_df.empty:
            print(f"  [SKIP] {date_str}: OHLCV 데이터 없음")
            continue
        if rescore_date(date_str, price_df):
            success += 1

    print("=" * 50)
    print(f"완료: {success}/{len(dates)}개 날짜 재채점")


if __name__ == '__main__':
    main()
