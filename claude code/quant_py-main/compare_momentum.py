"""
모멘텀 A/B 비교 — 기존 순위 데이터 재채점 + OHLCV 캐시 활용

비교 대상:
  A (현재): Value 45% + Quality 25% + Growth 10% + Momentum 20%
  B (제안): Value 50% + Quality 30% + Growth 20% + Momentum 0%

방법:
  1. 기존 ranking JSON에서 팩터별 점수 로드
  2. 두 가중치로 재채점 → 순위 비교
  3. OHLCV 캐시에서 과거 구간 수익률 비교
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import json
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta

STATE_DIR = Path(__file__).parent / 'state'
CACHE_DIR = Path(__file__).parent / 'data_cache'

CURRENT_W = {'V': 0.45, 'Q': 0.25, 'G': 0.10, 'M': 0.20}
PROPOSED_W = {'V': 0.50, 'Q': 0.30, 'G': 0.20, 'M': 0.00}


def load_rankings(date_str):
    path = STATE_DIR / f'ranking_{date_str}.json'
    if not path.exists():
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def rescore(rankings, weights):
    """팩터 점수로 재채점 + 재순위"""
    results = []
    for item in rankings:
        v = item.get('value_s') or 0
        q = item.get('quality_s') or 0
        g = item.get('growth_s') or 0
        m = item.get('momentum_s') or 0

        score = v * weights['V'] + q * weights['Q'] + g * weights['G'] + m * weights.get('M', 0)
        results.append({**item, 'new_score': score})

    results.sort(key=lambda x: x['new_score'], reverse=True)
    for i, r in enumerate(results):
        r['new_rank'] = i + 1
    return results


def compare_rankings(date_str):
    """한 날짜에 대해 두 가중치 비교"""
    data = load_rankings(date_str)
    if not data:
        return None

    rankings = data['rankings']
    current = rescore(rankings, CURRENT_W)
    proposed = rescore(rankings, PROPOSED_W)

    # Top 30 비교
    cur_top30 = {r['ticker']: r for r in current if r['new_rank'] <= 30}
    pro_top30 = {r['ticker']: r for r in proposed if r['new_rank'] <= 30}

    cur_set = set(cur_top30.keys())
    pro_set = set(pro_top30.keys())

    only_cur = cur_set - pro_set  # 현재에만 있는 종목 (모멘텀 덕분에 진입)
    only_pro = pro_set - cur_set  # 제안에만 있는 종목 (모멘텀 없으면 진입)
    common = cur_set & pro_set

    return {
        'date': date_str,
        'current': current,
        'proposed': proposed,
        'cur_top30': cur_top30,
        'pro_top30': pro_top30,
        'only_cur': only_cur,
        'only_pro': only_pro,
        'common': common,
    }


def compute_top_n_stats(scored, n=30):
    """Top N 종목의 평균 지표"""
    top = [r for r in scored if r['new_rank'] <= n]
    if not top:
        return {}

    def safe_mean(key):
        vals = [r.get(key) for r in top if r.get(key) is not None]
        return np.mean(vals) if vals else None

    return {
        'avg_per': safe_mean('per'),
        'avg_pbr': safe_mean('pbr'),
        'avg_roe': safe_mean('roe'),
        'avg_fwd_per': safe_mean('fwd_per'),
        'avg_value_s': safe_mean('value_s'),
        'avg_quality_s': safe_mean('quality_s'),
        'avg_growth_s': safe_mean('growth_s'),
        'avg_momentum_s': safe_mean('momentum_s'),
    }


def forward_returns(price_df, tickers, start_date, days=5):
    """OHLCV 캐시에서 N거래일 후 수익률 계산"""
    start_ts = pd.Timestamp(datetime.strptime(start_date, '%Y%m%d'))

    # start_date 이후 가장 가까운 거래일 찾기
    future = price_df[price_df.index >= start_ts]
    if len(future) < days + 1:
        return None

    returns = {}
    for ticker in tickers:
        if ticker not in price_df.columns:
            continue
        p0 = future[ticker].iloc[0]
        p1 = future[ticker].iloc[min(days, len(future) - 1)]
        if p0 > 0 and p1 > 0:
            returns[ticker] = (p1 / p0 - 1) * 100

    if not returns:
        return None
    return np.mean(list(returns.values()))


def main():
    # 사용 가능한 날짜 확인
    dates = sorted([f.stem.replace('ranking_', '') for f in STATE_DIR.glob('ranking_*.json')])
    print(f"사용 가능한 순위 데이터: {dates}")
    print()

    # OHLCV 캐시 로드 (수익률 비교용)
    ohlcv_files = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'))
    price_df = pd.DataFrame()
    if ohlcv_files:
        price_df = pd.read_parquet(ohlcv_files[-1])
        print(f"OHLCV 캐시: {ohlcv_files[-1].name}")
        print(f"  기간: {price_df.index[0].strftime('%Y-%m-%d')} ~ {price_df.index[-1].strftime('%Y-%m-%d')}")
        print(f"  종목 수: {len(price_df.columns)}")
    print()

    print("=" * 70)
    print("모멘텀 A/B 비교")
    print(f"  A (현재): V{CURRENT_W['V']:.0%} Q{CURRENT_W['Q']:.0%} G{CURRENT_W['G']:.0%} M{CURRENT_W['M']:.0%}")
    print(f"  B (제안): V{PROPOSED_W['V']:.0%} Q{PROPOSED_W['Q']:.0%} G{PROPOSED_W['G']:.0%} M{PROPOSED_W['M']:.0%}")
    print("=" * 70)

    all_rank_changes = []
    all_stats_cur = []
    all_stats_pro = []

    for date_str in dates:
        result = compare_rankings(date_str)
        if not result:
            continue

        cur = result['current']
        pro = result['proposed']

        # Top 10 비교
        print(f"\n{'─' * 70}")
        print(f"📅 {date_str}")
        print(f"{'─' * 70}")
        print(f"{'순위':>4} {'현재 Top10':<24} {'제안 Top10':<24} {'변동'}")
        print(f"{'─' * 70}")

        for i in range(10):
            c = cur[i]
            p = pro[i]

            # 현재→제안 순위 변동
            c_name = c['name']
            p_name = p['name']
            # 제안에서 현재 Top10 종목의 순위 찾기
            c_in_pro = next((r['new_rank'] for r in pro if r['ticker'] == c['ticker']), '?')
            p_in_cur = next((r['new_rank'] for r in cur if r['ticker'] == p['ticker']), '?')

            print(f"  {i+1:>2}  {c_name:<12} ({c['new_score']:+.3f})  {p_name:<12} ({p['new_score']:+.3f})")

        # Top 30 차이
        only_cur = result['only_cur']
        only_pro = result['only_pro']

        if only_cur or only_pro:
            print(f"\n  Top30 변동:")
            if only_cur:
                names = [result['cur_top30'][t]['name'] for t in only_cur]
                print(f"    모멘텀 있을 때만 Top30: {', '.join(sorted(names))}")
            if only_pro:
                names = [result['pro_top30'][t]['name'] for t in only_pro]
                print(f"    모멘텀 없을 때만 Top30: {', '.join(sorted(names))}")
            print(f"    공통: {len(result['common'])}개 / 변동: {len(only_cur)}개 교체")

        # Top 30 평균 지표 비교
        stats_cur = compute_top_n_stats(cur, 30)
        stats_pro = compute_top_n_stats(pro, 30)
        all_stats_cur.append(stats_cur)
        all_stats_pro.append(stats_pro)

        print(f"\n  Top30 평균 지표:")
        print(f"    {'':>16} {'현재':>10} {'제안':>10} {'차이':>10}")
        for key, label in [('avg_per', 'PER'), ('avg_roe', 'ROE(%)'), ('avg_fwd_per', 'Fwd PER'),
                           ('avg_value_s', 'Value점수'), ('avg_quality_s', 'Quality점수'),
                           ('avg_growth_s', 'Growth점수'), ('avg_momentum_s', 'Momentum점수')]:
            cv = stats_cur.get(key)
            pv = stats_pro.get(key)
            if cv is not None and pv is not None:
                diff = pv - cv
                print(f"    {label:>16} {cv:>10.2f} {pv:>10.2f} {diff:>+10.2f}")

        # 순위 변동 통계
        rank_changes = []
        for r in cur:
            pro_rank = next((p['new_rank'] for p in pro if p['ticker'] == r['ticker']), None)
            if pro_rank:
                rank_changes.append(pro_rank - r['new_rank'])
        all_rank_changes.extend(rank_changes)

    # 전체 요약
    print(f"\n{'=' * 70}")
    print("전체 요약")
    print(f"{'=' * 70}")

    if all_rank_changes:
        changes = np.array(all_rank_changes)
        print(f"\n순위 변동 통계 (모멘텀 제거 시):")
        print(f"  평균 변동: {np.mean(changes):+.1f}위")
        print(f"  중앙값: {np.median(changes):+.1f}위")
        print(f"  최대 상승: {np.min(changes):+d}위 (모멘텀 없을 때 더 높아짐)")
        print(f"  최대 하락: {np.max(changes):+d}위 (모멘텀 없을 때 더 낮아짐)")

        big_up = sum(1 for c in changes if c <= -5)
        big_down = sum(1 for c in changes if c >= 5)
        print(f"  5위 이상 상승: {big_up}개 종목")
        print(f"  5위 이상 하락: {big_down}개 종목")

    # 전체 기간 평균 지표
    if all_stats_cur and all_stats_pro:
        print(f"\n전체 기간 Top30 평균 지표:")
        print(f"  {'':>16} {'현재':>10} {'제안':>10} {'차이':>10}")
        for key, label in [('avg_per', 'PER'), ('avg_roe', 'ROE(%)'), ('avg_fwd_per', 'Fwd PER'),
                           ('avg_value_s', 'Value점수'), ('avg_quality_s', 'Quality점수'),
                           ('avg_growth_s', 'Growth점수')]:
            cvs = [s.get(key) for s in all_stats_cur if s.get(key) is not None]
            pvs = [s.get(key) for s in all_stats_pro if s.get(key) is not None]
            if cvs and pvs:
                cv = np.mean(cvs)
                pv = np.mean(pvs)
                diff = pv - cv
                print(f"  {label:>16} {cv:>10.2f} {pv:>10.2f} {diff:>+10.2f}")

    # OHLCV 기반 수익률 비교 (과거 구간)
    if not price_df.empty:
        print(f"\n{'─' * 70}")
        print("과거 구간 수익률 비교 (OHLCV 캐시 기반)")
        print(f"{'─' * 70}")

        # OHLCV 캐시 내 분기 시작점 찾기
        test_dates = ['20250103', '20250401', '20250701', '20251001']

        for test_date in test_dates:
            ts = pd.Timestamp(datetime.strptime(test_date, '%Y%m%d'))
            if ts < price_df.index[0] or ts > price_df.index[-1]:
                continue

            # 해당 시점 근처의 ranking이 없으므로, 가장 가까운 ranking 데이터 사용
            # → 이 부분은 ranking 기반이 아니라 실제 점수 재계산이 필요
            # → 여기서는 ranking JSON 활용 불가 (날짜 불일치)
            # → 대신 가용한 ranking 날짜에서 Top N의 forward return을 비교

        # 가용 ranking 날짜에서 forward return 비교
        for date_str in dates:
            result = compare_rankings(date_str)
            if not result:
                continue

            cur_top5 = [r['ticker'] for r in result['current'][:5]]
            pro_top5 = [r['ticker'] for r in result['proposed'][:5]]

            for days, label in [(1, '1일'), (3, '3일'), (5, '5일')]:
                ret_cur = forward_returns(price_df, cur_top5, date_str, days)
                ret_pro = forward_returns(price_df, pro_top5, date_str, days)

                if ret_cur is not None and ret_pro is not None:
                    diff = ret_pro - ret_cur
                    print(f"  {date_str} Top5 {label} 수익률: 현재 {ret_cur:+.2f}% | 제안 {ret_pro:+.2f}% | 차이 {diff:+.2f}%")

    print(f"\n{'=' * 70}")
    print("참고: 이 비교는 기존 순위 데이터 재채점 기반입니다.")
    print("모멘텀 제거 시 새로 포함되는 종목(기존 모멘텀 부재로 제외된 종목)은 반영되지 않습니다.")
    print(f"{'=' * 70}")


if __name__ == '__main__':
    main()
