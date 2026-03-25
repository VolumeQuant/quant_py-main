"""Phase 2: 팩터비율 + G비율 + Growth캡 Grid Search

기존 ranking JSON의 서브팩터 점수를 재가중하여 시뮬레이션.
API 호출 없음 — JSON 읽기 + 계산만.

Usage:
    python backtest/master_grid_search.py --years 2022,2023
    python backtest/master_grid_search.py --years 2022,2023,2024,2025
"""
import sys
import os
import json
import glob
import argparse
import time
from pathlib import Path
from itertools import product

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent
CACHE_DIR = PROJECT_ROOT / 'data_cache'


def load_rankings(years):
    """bt_YYYY 랭킹 JSON 전체 로드"""
    all_data = {}
    for year in years:
        bt_dir = PROJECT_ROOT / 'state' / f'bt_{year}'
        for f in sorted(bt_dir.glob('ranking_*.json')):
            date = f.stem.replace('ranking_', '')
            with open(f, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            all_data[date] = data.get('rankings', [])
    dates = sorted(all_data.keys())
    print(f'랭킹 로드: {len(dates)}거래일 ({dates[0]}~{dates[-1]})')
    return all_data, dates


def load_prices():
    """all_ohlcv 가격 데이터 로드"""
    f = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'),
               key=lambda x: x.stem.split('_')[2])[0]
    df = pd.read_parquet(f)
    df = df.replace(0, np.nan)
    print(f'가격 로드: {df.shape[0]}거래일 x {df.shape[1]}종목')
    return df


def reweight_and_rank(rankings, v_w, q_w, g_w, m_w, g_rev_ratio, growth_cap):
    """서브팩터 재가중 → 새 composite score → 순위"""
    results = []
    for stock in rankings:
        v = stock.get('value_s', 0) or 0
        q = stock.get('quality_s', 0) or 0
        m = stock.get('momentum_s', 0) or 0
        rev = stock.get('rev_z', 0) or 0
        oca = stock.get('oca_z', 0) or 0

        # Growth 캡 적용
        if growth_cap < 900:
            cap_z = growth_cap / 100  # 대략적 z-score 환산
            rev = max(-cap_z, min(cap_z, rev))
            oca = max(-cap_z, min(cap_z, oca))

        # G 재가중
        g = g_rev_ratio * rev + (1 - g_rev_ratio) * oca

        # 최종 점수
        score = v_w * v + q_w * q + g_w * g + m_w * m
        results.append({
            'ticker': stock['ticker'],
            'price': stock.get('price'),
            'score': score,
        })

    results.sort(key=lambda x: -x['score'])
    return results


def simulate_topn(all_data, dates, prices, v_w, q_w, g_w, m_w,
                  g_rev_ratio, growth_cap, top_buy=5, top_sell=20):
    """Top N 고정 규칙 시뮬레이션 → 수익률 계산"""
    portfolio = {}  # ticker → entry_price
    daily_returns = []

    for i, date in enumerate(dates):
        rankings = all_data[date]
        if not rankings:
            daily_returns.append(0)
            continue

        reweighted = reweight_and_rank(rankings, v_w, q_w, g_w, m_w,
                                        g_rev_ratio, growth_cap)
        top_tickers = set(r['ticker'] for r in reweighted[:top_sell])
        buy_tickers = set(r['ticker'] for r in reweighted[:top_buy])
        price_map = {r['ticker']: r['price'] for r in reweighted if r.get('price')}

        # 매도: top_sell 밖
        for tk in list(portfolio.keys()):
            if tk not in top_tickers:
                del portfolio[tk]

        # 매수: top_buy 안 + 빈 슬롯
        for tk in [r['ticker'] for r in reweighted[:top_buy]]:
            if tk not in portfolio and tk in price_map:
                portfolio[tk] = price_map[tk]

        # 일간 수익률 계산 (다음 날 가격)
        if i + 1 < len(dates):
            next_date = dates[i + 1]
            next_ts = pd.Timestamp(next_date)
            if next_ts in prices.index and portfolio:
                returns = []
                for tk in portfolio:
                    if tk in prices.columns:
                        cur = prices.loc[next_ts, tk]
                        prev_date_ts = pd.Timestamp(date)
                        if prev_date_ts in prices.index:
                            prev = prices.loc[prev_date_ts, tk]
                            if pd.notna(cur) and pd.notna(prev) and prev > 0:
                                returns.append(cur / prev - 1)
                if returns:
                    daily_returns.append(np.mean(returns))
                else:
                    daily_returns.append(0)
            else:
                daily_returns.append(0)

    return daily_returns


def calc_metrics(daily_returns):
    """수익률 → CAGR, Sharpe, MDD"""
    if not daily_returns or all(r == 0 for r in daily_returns):
        return {'cagr': 0, 'sharpe': 0, 'mdd': 0, 'total_ret': 0}

    equity = [1.0]
    for r in daily_returns:
        equity.append(equity[-1] * (1 + r))

    total = equity[-1] / equity[0] - 1
    n_days = len(daily_returns)
    cagr = (equity[-1] ** (252 / max(n_days, 1)) - 1) * 100

    arr = np.array(daily_returns)
    sharpe = (arr.mean() / arr.std() * np.sqrt(252)) if arr.std() > 0 else 0

    peak = np.maximum.accumulate(equity)
    dd = (np.array(equity) - peak) / peak
    mdd = abs(dd.min()) * 100

    return {'cagr': round(cagr, 2), 'sharpe': round(sharpe, 3),
            'mdd': round(mdd, 2), 'total_ret': round(total * 100, 2)}


def generate_weight_grid(step=5, min_w=10, max_w=40):
    """V/Q/G/M 가중치 조합 생성 (합=100)"""
    combos = []
    for v in range(min_w, max_w + 1, step):
        for q in range(min_w, max_w + 1, step):
            for g in range(min_w, max_w + 1, step):
                m = 100 - v - q - g
                if min_w <= m <= max_w:
                    combos.append((v / 100, q / 100, g / 100, m / 100))
    return combos


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--years', default='2022,2023', help='백테스트 연도 (콤마 구분)')
    args = parser.parse_args()
    years = [y.strip() for y in args.years.split(',')]

    print(f'=== Phase 2 Grid Search ({",".join(years)}) ===')
    t0 = time.time()

    all_data, dates = load_rankings(years)
    prices = load_prices()

    # Grid 정의
    weight_combos = generate_weight_grid(step=5, min_w=10, max_w=40)
    g_rev_ratios = [0.3, 0.4, 0.5, 0.6, 0.7]
    growth_caps = [50, 100, 200, 999]

    total = len(weight_combos) * len(g_rev_ratios) * len(growth_caps)
    print(f'Weight 조합: {len(weight_combos)}, G비율: {len(g_rev_ratios)}, Growth캡: {len(growth_caps)}')
    print(f'총 {total} 조합 테스트')
    print()

    results = []
    done = 0

    for (v_w, q_w, g_w, m_w), g_rev, g_cap in product(weight_combos, g_rev_ratios, growth_caps):
        daily_ret = simulate_topn(all_data, dates, prices,
                                   v_w, q_w, g_w, m_w, g_rev, g_cap)
        metrics = calc_metrics(daily_ret)
        results.append({
            'v': int(v_w * 100), 'q': int(q_w * 100),
            'g': int(g_w * 100), 'm': int(m_w * 100),
            'g_rev': g_rev, 'g_cap': g_cap,
            **metrics
        })
        done += 1
        if done % 200 == 0:
            elapsed = time.time() - t0
            print(f'  [{done}/{total}] {elapsed:.0f}초', flush=True)

    # 정렬 (Sharpe 기준)
    results.sort(key=lambda x: -x['sharpe'])

    elapsed = time.time() - t0
    print(f'\n=== 완료: {elapsed:.0f}초 ({total}조합) ===')
    print()

    # Top 20 출력
    print(f'{"V":>3} {"Q":>3} {"G":>3} {"M":>3} {"Grev":>4} {"Gcap":>4} | {"CAGR":>7} {"Sharpe":>7} {"MDD":>6} {"Total":>7}')
    print('-' * 65)
    for r in results[:20]:
        gcap = 'none' if r['g_cap'] >= 900 else str(r['g_cap'])
        print(f'{r["v"]:3d} {r["q"]:3d} {r["g"]:3d} {r["m"]:3d} {r["g_rev"]:4.1f} {gcap:>4} | '
              f'{r["cagr"]:7.1f}% {r["sharpe"]:7.3f} {r["mdd"]:5.1f}% {r["total_ret"]:6.1f}%')

    # 결과 저장
    out_path = PROJECT_ROOT / 'backtest_results' / f'grid_phase2_{"_".join(years)}.json'
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f'\n결과 저장: {out_path}')


if __name__ == '__main__':
    main()
