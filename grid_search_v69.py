#!/usr/bin/env python3
"""
v69 Grid Search — Entry/Exit/Slots 최적화
OHLCV 캐시 사용 (pykrx API 호출 없음, 빠름)
"""
import json, sys, io, warnings
import pandas as pd
import numpy as np
from pathlib import Path
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
warnings.filterwarnings('ignore')

STATE_DIR = Path(__file__).parent / 'state'
CACHE_DIR = Path(__file__).parent / 'data_cache'

# Grid parameters
ENTRY_THRESHOLDS = [66, 68, 70, 72, 74, 76, 78, 80]
EXIT_THRESHOLDS  = [58, 60, 62, 64, 66, 68, 70, 72, 74]
MAX_SLOTS_LIST   = [0, 3, 4, 5, 7, 10]  # 0 = unlimited
TOP_N_PURE       = [3, 4, 5, 7, 10, 15, 20]


def load_all_rankings():
    files = sorted(STATE_DIR.glob('ranking_*.json'))
    all_rankings = {}
    for f in files:
        with open(f, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        date_str = f.stem.replace('ranking_', '')
        all_rankings[date_str] = data.get('rankings', [])
    return all_rankings


def load_ohlcv_cache():
    """OHLCV parquet 캐시 로드 (가장 큰 파일)"""
    files = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'))
    if not files:
        raise FileNotFoundError("OHLCV cache not found")
    f = max(files, key=lambda x: x.stat().st_size)
    df = pd.read_parquet(f)
    print(f"OHLCV: {f.name} ({len(df)}일, {len(df.columns)}종목)")
    return df


def weighted_score100(ticker, t0, t1, t2):
    """3일 가중 score_100"""
    def _get(stocks, tk):
        if not stocks:
            return 0
        for s in stocks:
            if s['ticker'] == tk:
                return s['score']
        return 0

    s0 = _get(t0, ticker)
    s1 = _get(t1, ticker)
    s2 = _get(t2, ticker)
    ws = s0 * 0.5 + s1 * 0.3 + s2 * 0.2
    return max(0.0, min(100.0, (ws + 0.7) / 2.4 * 100))


def weighted_rank(ticker, t0, t1, t2, penalty=50):
    """3일 가중 순위"""
    def _get_rank(stocks, tk):
        if not stocks:
            return penalty
        for s in stocks:
            if s['ticker'] == tk:
                return s.get('composite_rank', s['rank'])
        return penalty

    r0 = _get_rank(t0, ticker)
    r1 = _get_rank(t1, ticker)
    r2 = _get_rank(t2, ticker)
    return r0 * 0.5 + r1 * 0.3 + r2 * 0.2


def build_daily_data(all_rankings):
    """날짜별 score_100, weighted_rank, 3일연속 여부 계산"""
    dates = sorted(all_rankings.keys())
    daily = {}

    # 연속 출현일
    prev_tickers = set()
    prev2_tickers = set()
    consec = {}

    for i, d in enumerate(dates):
        stocks = all_rankings[d]
        t0 = stocks
        t1 = all_rankings[dates[i-1]] if i >= 1 else None
        t2 = all_rankings[dates[i-2]] if i >= 2 else None

        current_tickers = {s['ticker'] for s in stocks}

        # 3일 연속 = 오늘 + 어제 + 그제 모두 출현
        verified = current_tickers & prev_tickers & prev2_tickers if i >= 2 else set()

        ticker_data = {}
        for s in stocks:
            tk = s['ticker']
            sc100 = weighted_score100(tk, t0, t1, t2)
            wr = weighted_rank(tk, t0, t1, t2)
            ticker_data[tk] = {
                'score_100': sc100,
                'weighted_rank': wr,
                'composite_rank': s.get('composite_rank', s['rank']),
                'verified': tk in verified,
                'name': s.get('name', tk),
            }

        daily[d] = ticker_data
        prev2_tickers = prev_tickers
        prev_tickers = current_tickers

    return daily, dates


def simulate_score(daily, dates, prices_df, entry_thr, exit_thr, max_slots=0):
    """Score-based 전략 시뮬레이션"""
    price_dates = sorted(prices_df.index)
    price_strs = [d.strftime('%Y%m%d') for d in price_dates]
    returns_df = prices_df.pct_change()

    portfolio = set()
    daily_returns = []
    all_trades = []
    entry_prices = {}

    for rank_date in dates:
        if rank_date not in price_strs:
            continue
        pidx = price_strs.index(rank_date)
        if pidx + 1 >= len(price_dates):
            continue
        trade_date = price_dates[pidx]
        next_date = price_dates[pidx + 1]
        td = daily[rank_date]

        # SELL: score < exit
        sells = set()
        for tk in portfolio:
            info = td.get(tk)
            if not info or info['score_100'] < exit_thr:
                sells.add(tk)

        for tk in sells:
            if tk in prices_df.columns and trade_date in prices_df.index:
                sell_p = prices_df.loc[trade_date, tk]
                buy_p = entry_prices.get(tk, sell_p)
                ret = (sell_p / buy_p - 1) if buy_p > 0 else 0
                all_trades.append(ret)
            if tk in entry_prices:
                del entry_prices[tk]
        portfolio -= sells

        # BUY: verified + score >= entry
        candidates = []
        for tk, info in td.items():
            if info['verified'] and info['score_100'] >= entry_thr and tk not in portfolio:
                if tk in prices_df.columns:
                    candidates.append((info['score_100'], tk))

        candidates.sort(reverse=True)  # 높은 점수 우선

        available_slots = (max_slots - len(portfolio)) if max_slots > 0 else len(candidates)
        buys = [tk for _, tk in candidates[:max(0, available_slots)]]

        for tk in buys:
            if trade_date in prices_df.index:
                p = prices_df.loc[trade_date, tk]
                if not np.isnan(p) and p > 0:
                    entry_prices[tk] = p
                    portfolio.add(tk)

        # Daily return
        if portfolio:
            port_tks = [t for t in portfolio if t in returns_df.columns]
            if port_tks and next_date in returns_df.index:
                day_ret = returns_df.loc[next_date, port_tks].mean()
                if np.isnan(day_ret):
                    day_ret = 0.0
            else:
                day_ret = 0.0
        else:
            day_ret = 0.0

        daily_returns.append({'date': rank_date, 'ret': day_ret, 'n': len(portfolio)})

    return calc_metrics(daily_returns, all_trades)


def simulate_topn(daily, dates, prices_df, n):
    """Top-N pure 전략: composite_rank <= N, 3일 검증, 이탈 시 제거"""
    price_dates = sorted(prices_df.index)
    price_strs = [d.strftime('%Y%m%d') for d in price_dates]
    returns_df = prices_df.pct_change()

    portfolio = set()
    daily_returns = []
    all_trades = []
    entry_prices = {}

    for rank_date in dates:
        if rank_date not in price_strs:
            continue
        pidx = price_strs.index(rank_date)
        if pidx + 1 >= len(price_dates):
            continue
        trade_date = price_dates[pidx]
        next_date = price_dates[pidx + 1]
        td = daily[rank_date]

        # 오늘의 Top-N
        topn_tickers = set()
        for tk, info in td.items():
            if info['weighted_rank'] <= n:
                topn_tickers.add(tk)

        # SELL: Top-N 이탈
        sells = portfolio - topn_tickers
        for tk in sells:
            if tk in prices_df.columns and trade_date in prices_df.index:
                sell_p = prices_df.loc[trade_date, tk]
                buy_p = entry_prices.get(tk, sell_p)
                ret = (sell_p / buy_p - 1) if buy_p > 0 else 0
                all_trades.append(ret)
            if tk in entry_prices:
                del entry_prices[tk]
        portfolio -= sells

        # BUY: verified + Top-N + not held
        for tk in topn_tickers:
            info = td.get(tk)
            if info and info['verified'] and tk not in portfolio and tk in prices_df.columns:
                if trade_date in prices_df.index:
                    p = prices_df.loc[trade_date, tk]
                    if not np.isnan(p) and p > 0:
                        entry_prices[tk] = p
                        portfolio.add(tk)

        # Daily return
        if portfolio:
            port_tks = [t for t in portfolio if t in returns_df.columns]
            if port_tks and next_date in returns_df.index:
                day_ret = returns_df.loc[next_date, port_tks].mean()
                if np.isnan(day_ret):
                    day_ret = 0.0
            else:
                day_ret = 0.0
        else:
            day_ret = 0.0

        daily_returns.append({'date': rank_date, 'ret': day_ret, 'n': len(portfolio)})

    return calc_metrics(daily_returns, all_trades)


def calc_metrics(daily_returns, trades):
    if not daily_returns:
        return {'cum': 0, 'sharpe': 0, 'mdd': 0, 'avg_pos': 0, 'max_pos': 0, 'n_trades': 0, 'win_rate': 0}

    rets = np.array([d['ret'] for d in daily_returns])
    positions = [d['n'] for d in daily_returns]

    cum = (1 + rets).prod() - 1
    sharpe = (rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else 0

    cum_vals = (1 + rets).cumprod()
    mdd = (cum_vals / np.maximum.accumulate(cum_vals) - 1).min()

    wins = [t for t in trades if t > 0]
    win_rate = len(wins) / len(trades) * 100 if trades else 0

    return {
        'cum': cum * 100,
        'sharpe': sharpe,
        'mdd': mdd * 100,
        'avg_pos': np.mean(positions),
        'max_pos': max(positions),
        'n_trades': len(trades),
        'win_rate': win_rate,
        'daily': daily_returns,
    }


def main():
    print("=" * 80)
    print("  v69 Grid Search — Entry/Exit/Slots")
    print("=" * 80)

    # 1. Load data
    all_rankings = load_all_rankings()
    prices_df = load_ohlcv_cache()
    # 0원 제거
    prices_df = prices_df.replace(0, np.nan)
    zero_rows = (prices_df.isna()).all(axis=1)
    prices_df = prices_df[~zero_rows]

    daily, dates = build_daily_data(all_rankings)
    print(f"Ranking: {len(dates)}일 ({dates[0]}~{dates[-1]})")

    # KOSPI proxy (KODEX 200)
    kospi_tk = '069500'
    if kospi_tk in prices_df.columns:
        kospi_rets = prices_df[kospi_tk].pct_change()
    else:
        kospi_rets = None

    # 2. Top-N Pure
    print(f"\n[Top-N Pure Strategies]")
    print(f"{'N':>4} {'Return%':>9} {'Sharpe':>8} {'MDD%':>8} {'AvgPos':>8} {'MaxPos':>8}")
    print("-" * 50)

    topn_results = {}
    for n in TOP_N_PURE:
        m = simulate_topn(daily, dates, prices_df, n)
        topn_results[n] = m
        print(f"{n:>4} {m['cum']:>9.2f} {m['sharpe']:>8.2f} {m['mdd']:>8.2f} {m['avg_pos']:>8.1f} {m['max_pos']:>8}")

    # 3. Score Grid (entry × exit × slots)
    print(f"\n[Score Grid Search] {len(ENTRY_THRESHOLDS)}×{len(EXIT_THRESHOLDS)}×{len(MAX_SLOTS_LIST)} = "
          f"{sum(1 for e in ENTRY_THRESHOLDS for x in EXIT_THRESHOLDS for s in MAX_SLOTS_LIST if e > x)} combos")

    all_results = []
    for entry in ENTRY_THRESHOLDS:
        for exit_ in EXIT_THRESHOLDS:
            if entry <= exit_:
                continue
            for max_s in MAX_SLOTS_LIST:
                m = simulate_score(daily, dates, prices_df, entry, exit_, max_s)
                m['entry'] = entry
                m['exit'] = exit_
                m['slots'] = max_s
                all_results.append(m)

    # 4. Top 30 by Sharpe
    print(f"\n{'='*90}")
    print(f"  TOP 30 BY SHARPE")
    print(f"{'='*90}")
    print(f"{'#':>3} {'Entry':>6} {'Exit':>5} {'Slots':>6} {'Return%':>9} {'Sharpe':>8} {'MDD%':>8} {'AvgPos':>8} {'MaxPos':>8} {'Win%':>7}")
    print("-" * 90)

    top30 = sorted(all_results, key=lambda x: x['sharpe'], reverse=True)[:30]
    for i, r in enumerate(top30, 1):
        slots_str = 'unlim' if r['slots'] == 0 else str(r['slots'])
        print(f"{i:>3} {r['entry']:>6} {r['exit']:>5} {slots_str:>6} "
              f"{r['cum']:>9.2f} {r['sharpe']:>8.2f} {r['mdd']:>8.2f} "
              f"{r['avg_pos']:>8.1f} {r['max_pos']:>8} {r['win_rate']:>7.1f}")

    # 5. Top 30 by Return
    print(f"\n{'='*90}")
    print(f"  TOP 30 BY CUMULATIVE RETURN")
    print(f"{'='*90}")
    print(f"{'#':>3} {'Entry':>6} {'Exit':>5} {'Slots':>6} {'Return%':>9} {'Sharpe':>8} {'MDD%':>8} {'AvgPos':>8} {'MaxPos':>8} {'Win%':>7}")
    print("-" * 90)

    top30_ret = sorted(all_results, key=lambda x: x['cum'], reverse=True)[:30]
    for i, r in enumerate(top30_ret, 1):
        slots_str = 'unlim' if r['slots'] == 0 else str(r['slots'])
        print(f"{i:>3} {r['entry']:>6} {r['exit']:>5} {slots_str:>6} "
              f"{r['cum']:>9.2f} {r['sharpe']:>8.2f} {r['mdd']:>8.2f} "
              f"{r['avg_pos']:>8.1f} {r['max_pos']:>8} {r['win_rate']:>7.1f}")

    # 6. Cumulative Return Grid (unlimited slots)
    print(f"\n{'='*90}")
    print(f"  CUMULATIVE RETURN GRID (slots=unlimited)")
    print(f"{'='*90}")
    unlim = {(r['entry'], r['exit']): r for r in all_results if r['slots'] == 0}

    print(f"{'':>12}", end='')
    for x in EXIT_THRESHOLDS:
        print(f"{'X='+str(x):>9}", end='')
    print()

    for e in ENTRY_THRESHOLDS:
        print(f"{'E='+str(e):>12}", end='')
        for x in EXIT_THRESHOLDS:
            if e > x and (e, x) in unlim:
                print(f"{unlim[(e,x)]['cum']:>9.1f}", end='')
            else:
                print(f"{'---':>9}", end='')
        print()

    # 7. Sharpe Grid (unlimited slots)
    print(f"\n  SHARPE GRID (slots=unlimited)")
    print(f"{'':>12}", end='')
    for x in EXIT_THRESHOLDS:
        print(f"{'X='+str(x):>9}", end='')
    print()

    for e in ENTRY_THRESHOLDS:
        print(f"{'E='+str(e):>12}", end='')
        for x in EXIT_THRESHOLDS:
            if e > x and (e, x) in unlim:
                print(f"{unlim[(e,x)]['sharpe']:>9.2f}", end='')
            else:
                print(f"{'---':>9}", end='')
        print()

    # 8. Slot effect for best entry/exit
    best_unlim = max([r for r in all_results if r['slots'] == 0], key=lambda x: x['sharpe'])
    best_e, best_x = best_unlim['entry'], best_unlim['exit']
    print(f"\n  SLOT EFFECT for best combo E={best_e}/X={best_x}:")
    print(f"{'Slots':>8} {'Return%':>9} {'Sharpe':>8} {'MDD%':>8} {'AvgPos':>8}")
    print("-" * 45)
    for s in MAX_SLOTS_LIST:
        r = next((r for r in all_results if r['entry'] == best_e and r['exit'] == best_x and r['slots'] == s), None)
        if r:
            slots_str = 'unlim' if s == 0 else str(s)
            print(f"{slots_str:>8} {r['cum']:>9.2f} {r['sharpe']:>8.2f} {r['mdd']:>8.2f} {r['avg_pos']:>8.1f}")

    # 9. 74/68 현행 vs 최적
    print(f"\n{'='*90}")
    print(f"  현행(74/68) vs 최적 비교")
    print(f"{'='*90}")
    current_unlim = unlim.get((74, 68))
    best = top30[0]
    best_topn = max(topn_results.items(), key=lambda x: x[1]['sharpe'])

    # KOSPI benchmark
    kospi_cum = 0
    if kospi_rets is not None:
        price_strs = [d.strftime('%Y%m%d') for d in prices_df.index]
        k_rets = []
        for d in dates:
            if d in price_strs:
                pidx = price_strs.index(d)
                if pidx + 1 < len(prices_df.index):
                    nd = prices_df.index[pidx + 1]
                    if nd in kospi_rets.index:
                        kr = kospi_rets.loc[nd]
                        if not np.isnan(kr):
                            k_rets.append(kr)
        if k_rets:
            kospi_cum = ((1 + np.array(k_rets)).prod() - 1) * 100

    print(f"{'Strategy':>30} {'Return%':>9} {'Sharpe':>8} {'MDD%':>8} {'AvgPos':>8}")
    print("-" * 70)
    if current_unlim:
        print(f"{'현행 74/68 unlimited':>30} {current_unlim['cum']:>9.2f} {current_unlim['sharpe']:>8.2f} {current_unlim['mdd']:>8.2f} {current_unlim['avg_pos']:>8.1f}")

    # 74/68 with slot limits
    for s in [3, 4, 5]:
        r = next((r for r in all_results if r['entry'] == 74 and r['exit'] == 68 and r['slots'] == s), None)
        if r:
            print(f"{f'현행 74/68 slots={s}':>30} {r['cum']:>9.2f} {r['sharpe']:>8.2f} {r['mdd']:>8.2f} {r['avg_pos']:>8.1f}")

    slots_str = 'unlim' if best['slots'] == 0 else str(best['slots'])
    best_label = f"optimal {best['entry']}/{best['exit']} slots={slots_str}"
    print(f"{best_label:>30} {best['cum']:>9.2f} {best['sharpe']:>8.2f} {best['mdd']:>8.2f} {best['avg_pos']:>8.1f}")
    print(f"{f'Top-{best_topn[0]} pure':>30} {best_topn[1]['cum']:>9.2f} {best_topn[1]['sharpe']:>8.2f} {best_topn[1]['mdd']:>8.2f} {best_topn[1]['avg_pos']:>8.1f}")
    print(f"{'KOSPI (KODEX200)':>30} {kospi_cum:>9.2f}")

    print(f"\n{'='*90}")
    print("  Grid Search 완료")
    print(f"{'='*90}")


if __name__ == '__main__':
    main()
