"""노이즈 필터 Grid Search — 턴어라운드/기저효과/극단값 테스트

Step 1: lookup 테이블 (연속흑자 + 전기매출)
Step 2: 노이즈 필터 조합 Grid Search
Step 3: Walk-Forward 검증
Step 4: OOS 검증 (bt_2020/2021)

Usage:
    python backtest/noise_filter_grid.py
"""
import sys
import os
import json
import glob
import time
from pathlib import Path
from itertools import product

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np

PROJECT = Path(__file__).parent.parent
CACHE_DIR = PROJECT / 'data_cache'


def build_lookup_table():
    """종목별 분기 ROE + 연간 매출 lookup"""
    print('=== lookup 테이블 생성 ===')
    t0 = time.time()

    # {ticker: {period_str: roe_value}}
    roe_quarterly = {}
    # {ticker: {year: revenue}}
    revenue_annual = {}

    for f in sorted(CACHE_DIR.glob('fs_dart_*.parquet')):
        tk = f.stem.replace('fs_dart_', '')
        df = pd.read_parquet(f)

        # 분기 ROE = 당기순이익 / 자본
        ni = df[(df['계정'] == '당기순이익') & (df['공시구분'] == 'q')].sort_values('기준일')
        eq = df[(df['계정'] == '자본') & (df['공시구분'] == 'q')].sort_values('기준일')

        roe_q = {}
        for _, row in ni.iterrows():
            period = str(row['기준일'])[:10]
            ni_val = row['값']
            eq_match = eq[eq['기준일'] == row['기준일']]
            if not eq_match.empty:
                eq_val = eq_match.iloc[0]['값']
                if eq_val > 0:
                    roe_q[period] = ni_val / eq_val
                else:
                    roe_q[period] = -999  # 자본잠식
        roe_quarterly[tk] = roe_q

        # 연간 매출
        rev = df[(df['계정'] == '매출액') & (df['공시구분'] == 'y')].sort_values('기준일')
        rev_y = {}
        for _, row in rev.iterrows():
            year = str(row['기준일'])[:4]
            rev_y[year] = row['값']
        revenue_annual[tk] = rev_y

    print(f'  {len(roe_quarterly)}종목, {time.time()-t0:.1f}초')
    return roe_quarterly, revenue_annual


def check_consecutive_profit(roe_quarterly, ticker, date_str, n_quarters):
    """date 기준 최근 n분기 연속 흑자 여부"""
    if n_quarters == 0:
        return True
    roe_q = roe_quarterly.get(ticker, {})
    if not roe_q:
        return True  # 데이터 없으면 통과

    # date 이전 분기 정렬
    target = pd.Timestamp(date_str)
    periods = sorted([p for p in roe_q.keys() if pd.Timestamp(p) <= target], reverse=True)

    if len(periods) < n_quarters:
        return False  # 데이터 부족 → 제외

    for p in periods[:n_quarters]:
        if roe_q[p] <= 0:
            return False
    return True


def check_revenue_base(revenue_annual, ticker, date_str, rev_percentile_cutoff, rev_percentiles):
    """전기 매출이 하위 N% 이하면 False"""
    if rev_percentile_cutoff == 0:
        return True

    rev_y = revenue_annual.get(ticker, {})
    if not rev_y:
        return True

    year = str(int(date_str[:4]) - 1)
    rev = rev_y.get(year)
    if rev is None:
        return True

    threshold = rev_percentiles.get(year, {}).get(rev_percentile_cutoff, 0)
    return rev > threshold


def load_all_rankings(years):
    """전체 랭킹 로드"""
    all_data = {}
    for year in years:
        for f in sorted(glob.glob(str(PROJECT / f'state/bt_{year}/ranking_*.json'))):
            date = os.path.basename(f).replace('ranking_', '').replace('.json', '')
            with open(f, 'r', encoding='utf-8') as fh:
                all_data[date] = json.load(fh).get('rankings', [])
    return all_data


def simulate(all_data, dates, prices, bench, v_w, q_w, g_w, m_w, g_rev, g_cap,
             ceiling, roe_quarterly, revenue_annual, consec_q, rev_cutoff, rev_pcts):
    """시뮬레이션 + 메트릭"""
    portfolio = {}
    daily_rets = []
    bench_rets = []

    for i, date in enumerate(dates):
        rankings = all_data[date]
        if not rankings:
            daily_rets.append(0)
            bench_rets.append(0)
            continue

        # 재가중 + 필터
        scored = []
        for s in rankings:
            tk = s['ticker']

            # 연속 흑자 필터
            if not check_consecutive_profit(roe_quarterly, tk, date, consec_q):
                continue

            # 전기 매출 기저 필터
            if not check_revenue_base(revenue_annual, tk, date, rev_cutoff, rev_pcts):
                continue

            v = (s.get('value_s') or 0)
            q = (s.get('quality_s') or 0)
            m = (s.get('momentum_s') or 0)
            rev_z = (s.get('rev_z') or 0)
            oca_z = (s.get('oca_z') or 0)

            # Growth ceiling
            if ceiling > 0:
                rev_z = max(-ceiling, min(ceiling, rev_z))
                oca_z = max(-ceiling, min(ceiling, oca_z))

            # Growth cap
            if g_cap < 900:
                cap_z = g_cap / 100
                rev_z = max(-cap_z, min(cap_z, rev_z))
                oca_z = max(-cap_z, min(cap_z, oca_z))

            g = g_rev * rev_z + (1 - g_rev) * oca_z
            score = v_w * v + q_w * q + g_w * g + m_w * m
            scored.append({'ticker': tk, 'price': s.get('price'), 'score': score})

        scored.sort(key=lambda x: -x['score'])
        top25 = set(r['ticker'] for r in scored[:25])
        price_map = {r['ticker']: r['price'] for r in scored if r.get('price')}

        # 매도
        for tk in list(portfolio.keys()):
            if tk not in top25:
                del portfolio[tk]

        # 매수
        for r in scored[:5]:
            tk = r['ticker']
            if tk not in portfolio and tk in price_map and len(portfolio) < 10:
                portfolio[tk] = price_map[tk]

        # 수익률
        if i + 1 < len(dates) and portfolio:
            next_ts = pd.Timestamp(dates[i + 1])
            cur_ts = pd.Timestamp(date)
            if next_ts in prices.index and cur_ts in prices.index:
                rets = []
                for tk in portfolio:
                    if tk in prices.columns:
                        c = prices.loc[next_ts, tk]
                        p = prices.loc[cur_ts, tk]
                        if pd.notna(c) and pd.notna(p) and p > 0:
                            rets.append(c / p - 1)
                daily_rets.append(np.mean(rets) if rets else 0)

                # 벤치마크
                if not bench.empty and next_ts in bench.index and cur_ts in bench.index:
                    b_c = bench.loc[next_ts].iloc[0]
                    b_p = bench.loc[cur_ts].iloc[0]
                    bench_rets.append((b_c / b_p - 1) if (pd.notna(b_c) and pd.notna(b_p) and b_p > 0) else 0)
                else:
                    bench_rets.append(0)
            else:
                daily_rets.append(0)
                bench_rets.append(0)
        else:
            daily_rets.append(0)
            bench_rets.append(0)

    return calc_metrics(daily_rets, bench_rets)


def calc_metrics(daily_rets, bench_rets):
    arr = np.array(daily_rets)
    if len(arr) == 0 or arr.std() == 0:
        return {'cagr': 0, 'sharpe': 0, 'sortino': 0, 'mdd': 0, 'total': 0, 'b_cagr': 0, 'alpha': 0}

    equity = np.cumprod(1 + arr)
    total = (equity[-1] - 1) * 100
    n = len(arr)
    cagr = (equity[-1] ** (252 / max(n, 1)) - 1) * 100
    sharpe = arr.mean() / arr.std() * np.sqrt(252)

    down = arr[arr < 0]
    down_std = down.std() if len(down) > 0 else arr.std()
    sortino = (arr.mean() / down_std * np.sqrt(252)) if down_std > 0 else sharpe

    peak = np.maximum.accumulate(np.concatenate([[1], equity]))
    dd = (np.concatenate([[1], equity]) - peak) / peak
    mdd = abs(dd.min()) * 100

    b_arr = np.array(bench_rets)
    b_equity = np.cumprod(1 + b_arr)
    b_cagr = (b_equity[-1] ** (252 / max(len(b_arr), 1)) - 1) * 100

    return {
        'cagr': round(cagr, 2), 'sharpe': round(sharpe, 3), 'sortino': round(sortino, 3),
        'mdd': round(mdd, 2), 'total': round(total, 2),
        'b_cagr': round(b_cagr, 2), 'alpha': round(cagr - b_cagr, 2),
    }


def main():
    t0 = time.time()

    # Step 1: lookup 테이블
    roe_quarterly, revenue_annual = build_lookup_table()

    # 전기 매출 percentile 계산
    rev_pcts = {}
    all_years = set()
    for tk, rev_y in revenue_annual.items():
        all_years.update(rev_y.keys())
    for year in all_years:
        vals = [rv[year] for rv in revenue_annual.values() if year in rv and rv[year] > 0]
        if vals:
            rev_pcts[year] = {
                10: np.percentile(vals, 10),
                20: np.percentile(vals, 20),
            }

    # 데이터 로드
    print('=== 데이터 로드 ===')
    prices = pd.read_parquet(sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'),
                                     key=lambda f: f.stem.split('_')[2])[0])
    prices = prices.replace(0, np.nan)

    bench_file = CACHE_DIR / 'index_benchmarks.parquet'
    bench = pd.read_parquet(bench_file) if bench_file.exists() else pd.DataFrame()

    # Phase 2 Top 5 weights
    p2_file = PROJECT / 'backtest_results' / 'grid_phase2_2022_2023_2024_2025.json'
    with open(p2_file, 'r', encoding='utf-8') as f:
        p2_results = json.load(f)
    top_weights = p2_results[:5]

    # In-Sample 데이터 (2022-2025)
    all_data_is = load_all_rankings(['2022', '2023', '2024', '2025'])
    dates_is = sorted(all_data_is.keys())
    print(f'In-Sample: {len(dates_is)}거래일')

    # Step 2: 노이즈 필터 Grid Search
    print('\n=== 노이즈 필터 Grid Search ===')
    consec_options = [0, 2, 4, 8]
    ceiling_options = [0, 1.5, 2.0]  # 0 = none
    rev_cutoff_options = [0, 10, 20]

    total = len(top_weights) * len(consec_options) * len(ceiling_options) * len(rev_cutoff_options)
    print(f'조합: {total} ({len(top_weights)}w x {len(consec_options)}q x {len(ceiling_options)}c x {len(rev_cutoff_options)}r)')

    results = []
    done = 0

    for w in top_weights:
        v_w, q_w, g_w, m_w = w['v']/100, w['q']/100, w['g']/100, w['m']/100
        g_rev, g_cap = w['g_rev'], w['g_cap']

        for consec_q, ceiling, rev_cutoff in product(consec_options, ceiling_options, rev_cutoff_options):
            metrics = simulate(all_data_is, dates_is, prices, bench,
                             v_w, q_w, g_w, m_w, g_rev, g_cap,
                             ceiling, roe_quarterly, revenue_annual,
                             consec_q, rev_cutoff, rev_pcts)

            results.append({
                'v': w['v'], 'q': w['q'], 'g': w['g'], 'm': w['m'],
                'g_rev': g_rev, 'g_cap': g_cap,
                'consec_q': consec_q, 'ceiling': ceiling, 'rev_cutoff': rev_cutoff,
                **metrics,
            })
            done += 1
            if done % 30 == 0:
                print(f'  [{done}/{total}] {time.time()-t0:.0f}초', flush=True)

    results.sort(key=lambda x: -x['sharpe'])

    # 결과 출력
    print(f'\n=== In-Sample Top 10 (Sharpe) ===')
    print(f'{"V":>2}{"Q":>3}{"G":>3}{"M":>3} {"Qrt":>3} {"Ceil":>4} {"Rev":>3} | {"CAGR":>6} {"Shrp":>5} {"Sort":>5} {"MDD":>5} {"Alpha":>6}')
    print('-' * 60)
    for r in results[:10]:
        ceil = 'none' if r['ceiling'] == 0 else f'{r["ceiling"]}'
        rev = 'none' if r['rev_cutoff'] == 0 else f'{r["rev_cutoff"]}%'
        print(f'{r["v"]:2d}{r["q"]:3d}{r["g"]:3d}{r["m"]:3d} {r["consec_q"]:3d} {ceil:>4} {rev:>4} | '
              f'{r["cagr"]:5.1f}% {r["sharpe"]:5.3f} {r["sortino"]:5.3f} {r["mdd"]:4.1f}% {r["alpha"]:+5.1f}%')

    # 필터 효과 비교 (같은 weight에서 필터 없음 vs 있음)
    print(f'\n=== 필터 효과 비교 (Top 1 weight) ===')
    w = top_weights[0]
    baseline = [r for r in results if r['v']==w['v'] and r['q']==w['q'] and r['g']==w['g'] and r['m']==w['m']
                and r['consec_q']==0 and r['ceiling']==0 and r['rev_cutoff']==0]
    if baseline:
        b = baseline[0]
        print(f'필터 없음: CAGR={b["cagr"]}% Sharpe={b["sharpe"]} MDD={b["mdd"]}%')

    best = results[0]
    print(f'최적필터: CAGR={best["cagr"]}% Sharpe={best["sharpe"]} MDD={best["mdd"]}%')
    print(f'  연속흑자={best["consec_q"]}분기, ceiling={best["ceiling"]}, 기저={best["rev_cutoff"]}%')

    # Step 3: Walk-Forward
    print(f'\n=== Walk-Forward 검증 ===')
    best_params = best

    wf_windows = [
        (['2022'], ['2023'], '2022->2023(횡보)'),
        (['2022', '2023'], ['2024'], '22-23->2024(강세)'),
        (['2022', '2023', '2024'], ['2025'], '22-24->2025-26'),
    ]

    for train_yrs, test_yrs, label in wf_windows:
        test_data = load_all_rankings(test_yrs)
        test_dates = sorted(test_data.keys())
        if not test_dates:
            continue
        m = simulate(test_data, test_dates, prices, bench,
                    best_params['v']/100, best_params['q']/100, best_params['g']/100, best_params['m']/100,
                    best_params['g_rev'], best_params['g_cap'], best_params['ceiling'],
                    roe_quarterly, revenue_annual, best_params['consec_q'], best_params['rev_cutoff'], rev_pcts)
        print(f'  {label}: CAGR={m["cagr"]}% Sharpe={m["sharpe"]} Sortino={m["sortino"]} Alpha={m["alpha"]:+.1f}%')

    # Step 4: OOS
    print(f'\n=== Out-of-Sample (bt_2020/2021) ===')
    for year in ['2020', '2021']:
        oos_data = load_all_rankings([year])
        oos_dates = sorted(oos_data.keys())
        if not oos_dates:
            continue
        m = simulate(oos_data, oos_dates, prices, bench,
                    best_params['v']/100, best_params['q']/100, best_params['g']/100, best_params['m']/100,
                    best_params['g_rev'], best_params['g_cap'], best_params['ceiling'],
                    roe_quarterly, revenue_annual, best_params['consec_q'], best_params['rev_cutoff'], rev_pcts)
        print(f'  bt_{year}: CAGR={m["cagr"]}% Sharpe={m["sharpe"]} Sortino={m["sortino"]} Alpha={m["alpha"]:+.1f}%')

    # 저장
    out_path = PROJECT / 'backtest_results' / 'noise_filter_grid.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    elapsed = time.time() - t0
    print(f'\n=== 완료: {elapsed:.0f}초 ===')


if __name__ == '__main__':
    main()
