#!/usr/bin/env python3
"""
Comprehensive Parameter Tuning Simulation for Score-Based Entry/Exit Strategy
Korean Quant System - v59 Strategy v6.5
"""

import json
import os
import sys
import io
import warnings
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
import itertools

# Fix Windows cp949 encoding - use flush for real-time output

import pandas as pd
import numpy as np

warnings.filterwarnings('ignore')

# ============================================================
# Configuration
# ============================================================
STATE_DIR = Path(__file__).parent / 'state'
ENTRY_THRESHOLDS = [64, 66, 68, 70, 72, 74, 76, 78, 80]
EXIT_THRESHOLDS  = [58, 60, 62, 64, 66, 68, 70, 72, 74, 76]

# ============================================================
# 1. Load all ranking data
# ============================================================
def load_all_rankings():
    """Load all ranking JSON files into a dict keyed by date string."""
    files = sorted(STATE_DIR.glob('ranking_*.json'))
    all_rankings = {}
    for f in files:
        with open(f, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        date_str = f.stem.replace('ranking_', '')  # e.g. '20260209'
        stocks = data.get('rankings', [])
        all_rankings[date_str] = stocks
    return all_rankings


def raw_to_score100(raw_score):
    """Convert raw multifactor score to 100-point scale (single day)."""
    return max(0.0, min(100.0, (raw_score + 3.0) / 6.0 * 100))


def weighted_score100(ticker, t0_stocks, t1_stocks, t2_stocks):
    """3-day weighted score_100: T0*0.5 + T1*0.3 + T2*0.2."""
    DEFAULT_MISSING_RANK = 50

    def _build_map(stocks):
        if not stocks:
            return {}, 0
        ticker_map = {s['ticker']: s['score'] for s in stocks}
        rank_map = {s.get('composite_rank', s['rank']): s['score'] for s in stocks}
        fallback = rank_map.get(DEFAULT_MISSING_RANK, 0)
        return ticker_map, fallback

    t0_map, _ = _build_map(t0_stocks)
    t1_map, t1_fb = _build_map(t1_stocks)
    t2_map, t2_fb = _build_map(t2_stocks)

    s0 = t0_map.get(ticker, 0)
    s1 = t1_map.get(ticker, t1_fb)
    s2 = t2_map.get(ticker, t2_fb)
    ws = s0 * 0.5 + s1 * 0.3 + s2 * 0.2
    return max(0.0, min(100.0, (ws + 3.0) / 6.0 * 100))


# ============================================================
# 2. Fetch price data via pykrx
# ============================================================
def _fetch_one_ticker(ticker, start_date, end_date):
    """Fetch a single ticker with timeout protection."""
    from pykrx import stock
    import threading

    result = [None]
    error = [None]

    def _fetch():
        try:
            df = stock.get_market_ohlcv(start_date, end_date, ticker)
            result[0] = df
        except Exception as e:
            error[0] = e

    t = threading.Thread(target=_fetch)
    t.daemon = True
    t.start()
    t.join(timeout=10)  # 10 second timeout per ticker

    if t.is_alive():
        return None, f"timeout"
    if error[0]:
        return None, str(error[0])
    return result[0], None


def fetch_all_prices(all_rankings, start_date='20260207', end_date='20260312'):
    """Fetch daily close prices for all tickers that appear in any ranking file."""
    from pykrx import stock

    # Collect all unique tickers
    all_tickers = set()
    for date_str, stocks in all_rankings.items():
        for s in stocks:
            all_tickers.add(s['ticker'])

    print(f"Fetching prices for {len(all_tickers)} unique tickers from {start_date} to {end_date}...", flush=True)

    # Fetch KOSPI proxy via KODEX 200 ETF (069500) -- pykrx index API has a bug
    print("  Fetching KOSPI proxy (KODEX 200 ETF)...", flush=True)
    try:
        kospi = stock.get_market_ohlcv(start_date, end_date, "069500")
        kospi_close = kospi['종가']
        kospi_close.name = 'KOSPI'
        print(f"  KOSPI proxy: {len(kospi_close)} data points", flush=True)
    except Exception as e:
        print(f"  WARNING: KOSPI proxy fetch failed: {e}", flush=True)
        kospi_close = pd.Series(dtype=float, name='KOSPI')

    # Per-ticker fetch with timeout protection
    print("  Fetching individual stock prices (with 10s timeout per ticker)...", flush=True)
    price_dict = {}
    failed_tickers = []
    timeout_tickers = []
    tickers_list = sorted(all_tickers)
    total = len(tickers_list)

    for i, ticker in enumerate(tickers_list):
        df, err = _fetch_one_ticker(ticker, start_date, end_date)

        if err:
            if 'timeout' in str(err):
                timeout_tickers.append(ticker)
            else:
                failed_tickers.append(ticker)
        elif df is not None and len(df) > 0:
            close = df['종가']
            close = close.replace(0, np.nan)
            if close.notna().sum() > 0:
                price_dict[ticker] = close
            else:
                failed_tickers.append(ticker)
        else:
            failed_tickers.append(ticker)

        if (i + 1) % 30 == 0 or i == total - 1:
            print(f"    Progress: {i+1}/{total} ({(i+1)/total*100:.0f}%) "
                  f"[OK:{len(price_dict)}, Fail:{len(failed_tickers)}, Timeout:{len(timeout_tickers)}]", flush=True)

    if failed_tickers:
        print(f"  Failed tickers ({len(failed_tickers)}): {failed_tickers[:20]}", flush=True)
    if timeout_tickers:
        print(f"  Timeout tickers ({len(timeout_tickers)}): {timeout_tickers[:20]}", flush=True)

    prices_df = pd.DataFrame(price_dict)
    prices_df.index = pd.to_datetime(prices_df.index)

    return prices_df, kospi_close, failed_tickers + timeout_tickers


# ============================================================
# 3. Build score_100 matrix (dates x tickers)
# ============================================================
def build_score100_matrix(all_rankings):
    """Build a DataFrame of weighted score_100 for each ticker on each date."""
    dates = sorted(all_rankings.keys())
    all_tickers = set()
    for stocks in all_rankings.values():
        for s in stocks:
            all_tickers.add(s['ticker'])

    # Build ticker->name mapping
    ticker_names = {}
    for stocks in all_rankings.values():
        for s in stocks:
            ticker_names[s['ticker']] = s.get('name', s['ticker'])

    score_matrix = {}
    rank_matrix = {}

    for i, date_str in enumerate(dates):
        t0 = all_rankings[date_str]
        t1 = all_rankings[dates[i-1]] if i >= 1 else None
        t2 = all_rankings[dates[i-2]] if i >= 2 else None

        day_scores = {}
        day_ranks = {}
        for ticker in all_tickers:
            s100 = weighted_score100(ticker, t0, t1, t2)
            day_scores[ticker] = s100
            # Get composite rank
            for s in t0:
                if s['ticker'] == ticker:
                    day_ranks[ticker] = s.get('composite_rank', s['rank'])
                    break

        score_matrix[date_str] = day_scores
        rank_matrix[date_str] = day_ranks

    score_df = pd.DataFrame(score_matrix).T
    score_df.index.name = 'date'
    rank_df = pd.DataFrame(rank_matrix).T
    rank_df.index.name = 'date'

    return score_df, rank_df, ticker_names


def build_consecutive_days(all_rankings):
    """For each date, compute how many consecutive ranking days each ticker has appeared."""
    dates = sorted(all_rankings.keys())
    # Build presence map
    presence = {}
    for date_str in dates:
        tickers_today = {s['ticker'] for s in all_rankings[date_str]}
        presence[date_str] = tickers_today

    consec = {}  # {date_str: {ticker: consecutive_days}}
    for i, date_str in enumerate(dates):
        consec[date_str] = {}
        for ticker in presence[date_str]:
            if i == 0:
                consec[date_str][ticker] = 1
            else:
                prev_date = dates[i-1]
                if ticker in consec.get(prev_date, {}):
                    consec[date_str][ticker] = consec[prev_date][ticker] + 1
                else:
                    consec[date_str][ticker] = 1
    return consec


# ============================================================
# 4. Simulation engine
# ============================================================
def simulate_score_strategy(score_df, prices_df, consec_days, entry_thresh, exit_thresh,
                             use_3day_verify=True, cold_start_days=3):
    """
    Simulate a score-based entry/exit strategy.

    Returns: dict with performance metrics and trade log.
    """
    dates = sorted(score_df.index.tolist())

    # Map ranking dates to trading dates (prices_df index)
    # Ranking dates are YYYYMMDD strings, prices index are datetime
    price_dates = sorted(prices_df.index.tolist())
    price_date_strs = [d.strftime('%Y%m%d') for d in price_dates]

    # Daily returns
    returns_df = prices_df.pct_change()

    # Portfolio state
    portfolio = set()  # tickers currently held
    daily_returns = []
    daily_positions = []
    trade_log = []  # (date, ticker, action, score, return_if_sell)
    holding_returns = {}  # ticker -> cumulative return while held

    # Track entry prices for trade return calculation
    entry_info = {}  # ticker -> {'date': str, 'price': float}

    for i, rank_date in enumerate(dates):
        # Find the next trading date AFTER rank_date for execution
        # Rankings generated at 06:00 KST, so we execute on the same trading day
        # We need the close price on rank_date and the close on next day for return

        # Find rank_date in price_date_strs
        if rank_date not in price_date_strs:
            continue

        price_idx = price_date_strs.index(rank_date)
        trade_date = price_dates[price_idx]

        # Get next trading day for return calculation
        if price_idx + 1 >= len(price_dates):
            continue  # No next day to calculate return

        next_date = price_dates[price_idx + 1]

        # Current scores
        day_scores = score_df.loc[rank_date]

        # Determine eligible tickers (3-day verification)
        eligible = set()
        for ticker in day_scores.index:
            if pd.isna(day_scores[ticker]):
                continue
            score = day_scores[ticker]
            if score >= entry_thresh:
                if use_3day_verify and i >= cold_start_days:
                    # Must have appeared in rankings for 3+ consecutive days
                    cd = consec_days.get(rank_date, {}).get(ticker, 0)
                    if cd >= 3:
                        eligible.add(ticker)
                else:
                    eligible.add(ticker)

        # Determine which current holdings to SELL (score < exit_threshold)
        sells = set()
        for ticker in portfolio:
            score = day_scores.get(ticker, 0)
            if pd.isna(score) or score < exit_thresh:
                sells.add(ticker)

        # Determine which to BUY (newly eligible, not already held)
        buys = eligible - portfolio

        # Execute sells
        for ticker in sells:
            if ticker in prices_df.columns:
                sell_price = prices_df.loc[trade_date, ticker] if trade_date in prices_df.index else np.nan
                entry = entry_info.get(ticker, {})
                entry_price = entry.get('price', np.nan)
                trade_return = (sell_price / entry_price - 1) if not np.isnan(entry_price) and entry_price > 0 else 0
                trade_log.append({
                    'date': rank_date, 'ticker': ticker, 'action': 'SELL',
                    'score': day_scores.get(ticker, 0),
                    'trade_return': trade_return,
                    'entry_date': entry.get('date', ''),
                })
                if ticker in entry_info:
                    del entry_info[ticker]

        portfolio -= sells

        # Execute buys
        for ticker in buys:
            if ticker in prices_df.columns:
                buy_price = prices_df.loc[trade_date, ticker] if trade_date in prices_df.index else np.nan
                if not np.isnan(buy_price) and buy_price > 0:
                    trade_log.append({
                        'date': rank_date, 'ticker': ticker, 'action': 'BUY',
                        'score': day_scores.get(ticker, 0),
                        'trade_return': 0,
                        'entry_date': rank_date,
                    })
                    entry_info[ticker] = {'date': rank_date, 'price': buy_price}
                    portfolio.add(ticker)

        # Calculate daily return (equal-weighted)
        if portfolio:
            port_tickers = [t for t in portfolio if t in returns_df.columns]
            if port_tickers and next_date in returns_df.index:
                day_rets = returns_df.loc[next_date, port_tickers]
                port_ret = day_rets.mean()
                if np.isnan(port_ret):
                    port_ret = 0.0
            else:
                port_ret = 0.0
        else:
            port_ret = 0.0

        daily_returns.append({'date': rank_date, 'return': port_ret, 'n_positions': len(portfolio)})
        daily_positions.append(len(portfolio))

    return _calc_metrics(daily_returns, trade_log, daily_positions, entry_thresh, exit_thresh)


def simulate_baseline_top5_rank(all_rankings, prices_df, consec_days):
    """Baseline A: Current strategy - Top 5 by composite_rank, exit when rank > 30."""
    dates = sorted(all_rankings.keys())
    price_dates = sorted(prices_df.index.tolist())
    price_date_strs = [d.strftime('%Y%m%d') for d in price_dates]
    returns_df = prices_df.pct_change()

    portfolio = set()
    daily_returns = []
    daily_positions = []
    trade_log = []
    entry_info = {}

    for i, rank_date in enumerate(dates):
        if rank_date not in price_date_strs:
            continue
        price_idx = price_date_strs.index(rank_date)
        trade_date = price_dates[price_idx]
        if price_idx + 1 >= len(price_dates):
            continue
        next_date = price_dates[price_idx + 1]

        stocks = all_rankings[rank_date]
        rank_map = {s['ticker']: s.get('composite_rank', s['rank']) for s in stocks}

        # 3-day verified stocks (top 5 by composite_rank among those with 3+ consecutive days)
        verified = set()
        for s in stocks:
            ticker = s['ticker']
            if i >= 3:
                cd = consec_days.get(rank_date, {}).get(ticker, 0)
                if cd >= 3 and s.get('composite_rank', s['rank']) <= 5:
                    verified.add(ticker)
            else:
                if s.get('composite_rank', s['rank']) <= 5:
                    verified.add(ticker)

        # Sell: rank > 30 or not in rankings
        sells = set()
        for ticker in portfolio:
            r = rank_map.get(ticker, 999)
            if r > 30:
                sells.add(ticker)

        for ticker in sells:
            if ticker in prices_df.columns:
                sell_price = prices_df.loc[trade_date, ticker] if trade_date in prices_df.index else np.nan
                entry = entry_info.get(ticker, {})
                entry_price = entry.get('price', np.nan)
                trade_return = (sell_price / entry_price - 1) if not np.isnan(entry_price) and entry_price > 0 else 0
                trade_log.append({
                    'date': rank_date, 'ticker': ticker, 'action': 'SELL',
                    'score': 0, 'trade_return': trade_return, 'entry_date': entry.get('date', ''),
                })
                if ticker in entry_info:
                    del entry_info[ticker]

        portfolio -= sells

        # Buy: top 5 verified not already held
        buys = verified - portfolio
        for ticker in buys:
            if ticker in prices_df.columns:
                buy_price = prices_df.loc[trade_date, ticker] if trade_date in prices_df.index else np.nan
                if not np.isnan(buy_price) and buy_price > 0:
                    trade_log.append({
                        'date': rank_date, 'ticker': ticker, 'action': 'BUY',
                        'score': 0, 'trade_return': 0, 'entry_date': rank_date,
                    })
                    entry_info[ticker] = {'date': rank_date, 'price': buy_price}
                    portfolio.add(ticker)

        # Daily return
        if portfolio:
            port_tickers = [t for t in portfolio if t in returns_df.columns]
            if port_tickers and next_date in returns_df.index:
                day_rets = returns_df.loc[next_date, port_tickers]
                port_ret = day_rets.mean()
                if np.isnan(port_ret):
                    port_ret = 0.0
            else:
                port_ret = 0.0
        else:
            port_ret = 0.0

        daily_returns.append({'date': rank_date, 'return': port_ret, 'n_positions': len(portfolio)})
        daily_positions.append(len(portfolio))

    return _calc_metrics(daily_returns, trade_log, daily_positions, 'Top5Rank', 'Rank>30')


def simulate_baseline_buyhold_top5(all_rankings, prices_df):
    """Baseline B: Buy & hold Top 5 from day 1."""
    dates = sorted(all_rankings.keys())
    price_dates = sorted(prices_df.index.tolist())
    price_date_strs = [d.strftime('%Y%m%d') for d in price_dates]
    returns_df = prices_df.pct_change()

    # Top 5 from first day
    first_stocks = all_rankings[dates[0]]
    first_stocks_sorted = sorted(first_stocks, key=lambda s: s.get('composite_rank', s['rank']))
    top5 = [s['ticker'] for s in first_stocks_sorted[:5]]
    top5 = [t for t in top5 if t in prices_df.columns]

    daily_returns = []
    daily_positions = []
    trade_log = [{'date': dates[0], 'ticker': t, 'action': 'BUY', 'score': 0, 'trade_return': 0, 'entry_date': dates[0]} for t in top5]

    for rank_date in dates:
        if rank_date not in price_date_strs:
            continue
        price_idx = price_date_strs.index(rank_date)
        if price_idx + 1 >= len(price_dates):
            continue
        next_date = price_dates[price_idx + 1]

        if top5 and next_date in returns_df.index:
            day_rets = returns_df.loc[next_date, top5]
            port_ret = day_rets.mean()
            if np.isnan(port_ret):
                port_ret = 0.0
        else:
            port_ret = 0.0

        daily_returns.append({'date': rank_date, 'return': port_ret, 'n_positions': len(top5)})
        daily_positions.append(len(top5))

    return _calc_metrics(daily_returns, trade_log, daily_positions, 'BuyHold', 'Never')


def simulate_baseline_kospi(kospi_close, all_rankings):
    """Baseline C: KOSPI index buy & hold."""
    dates = sorted(all_rankings.keys())
    kospi_rets = kospi_close.pct_change()

    daily_returns = []
    price_date_strs = [d.strftime('%Y%m%d') for d in kospi_close.index]

    for rank_date in dates:
        if rank_date not in price_date_strs:
            continue
        price_idx = price_date_strs.index(rank_date)
        if price_idx + 1 >= len(price_date_strs):
            continue
        next_date = kospi_close.index[price_idx + 1]

        if next_date in kospi_rets.index:
            ret = kospi_rets.loc[next_date]
            if np.isnan(ret):
                ret = 0.0
        else:
            ret = 0.0

        daily_returns.append({'date': rank_date, 'return': ret, 'n_positions': 1})

    return _calc_metrics(daily_returns, [], [1]*len(daily_returns), 'KOSPI', 'Index')


# ============================================================
# 5. Metrics calculation
# ============================================================
def _calc_metrics(daily_returns, trade_log, daily_positions, entry_label, exit_label):
    """Calculate comprehensive performance metrics."""
    if not daily_returns:
        return {
            'entry': entry_label, 'exit': exit_label,
            'cum_return': 0, 'sharpe': 0, 'max_dd': 0,
            'n_trades': 0, 'avg_positions': 0, 'turnover': 0,
            'win_rate': 0, 'avg_trade_return': 0, 'calmar': 0,
            'daily_returns': [], 'trade_log': [], 'daily_positions': [],
        }

    rets = [d['return'] for d in daily_returns]
    rets_arr = np.array(rets)

    # Cumulative return
    cum_return = (1 + rets_arr).prod() - 1

    # Annualized Sharpe (0% risk-free)
    if len(rets_arr) > 1 and rets_arr.std() > 0:
        sharpe = (rets_arr.mean() / rets_arr.std()) * np.sqrt(252)
    else:
        sharpe = 0.0

    # Max drawdown
    cum_vals = (1 + rets_arr).cumprod()
    running_max = np.maximum.accumulate(cum_vals)
    drawdowns = cum_vals / running_max - 1
    max_dd = drawdowns.min()

    # Trade stats
    sells = [t for t in trade_log if t['action'] == 'SELL']
    buys = [t for t in trade_log if t['action'] == 'BUY']
    n_trades = len(buys) + len(sells)

    # Win rate (based on completed trades - sells)
    if sells:
        wins = [t for t in sells if t.get('trade_return', 0) > 0]
        win_rate = len(wins) / len(sells) * 100
        avg_trade_return = np.mean([t.get('trade_return', 0) for t in sells]) * 100
    else:
        win_rate = 0
        avg_trade_return = 0

    # Average positions
    avg_pos = np.mean(daily_positions) if daily_positions else 0
    min_pos = min(daily_positions) if daily_positions else 0
    max_pos = max(daily_positions) if daily_positions else 0

    # Turnover (changes / avg positions)
    changes = len(buys) + len(sells)
    n_days = len(daily_returns)
    turnover = changes / n_days if n_days > 0 else 0

    # Calmar ratio
    ann_return = cum_return * (252 / n_days) if n_days > 0 else 0
    calmar = abs(ann_return / max_dd) if max_dd != 0 else 0

    return {
        'entry': entry_label, 'exit': exit_label,
        'buffer': (entry_label - exit_label) if isinstance(entry_label, (int, float)) and isinstance(exit_label, (int, float)) else 'N/A',
        'cum_return': cum_return * 100,
        'sharpe': sharpe,
        'max_dd': max_dd * 100,
        'n_trades': n_trades,
        'avg_positions': avg_pos,
        'min_positions': min_pos,
        'max_positions': max_pos,
        'turnover': turnover,
        'win_rate': win_rate,
        'avg_trade_return': avg_trade_return,
        'calmar': calmar,
        'daily_returns': daily_returns,
        'trade_log': trade_log,
        'daily_positions': daily_positions,
    }


# ============================================================
# 6. Print results
# ============================================================
def print_divider(title):
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}")


def print_results_table(results, sort_key, title, top_n=20):
    """Print a formatted table of results."""
    print_divider(title)
    sorted_results = sorted(results, key=lambda x: x.get(sort_key, 0), reverse=True)[:top_n]

    header = f"{'#':>3} {'Entry':>6} {'Exit':>5} {'Buf':>4} {'CumRet%':>8} {'Sharpe':>7} {'MaxDD%':>7} {'Calmar':>7} {'Trades':>7} {'AvgPos':>7} {'Turnov':>7} {'Win%':>6} {'AvgTrdRet%':>11}"
    print(header)
    print('-' * len(header))

    for idx, r in enumerate(sorted_results, 1):
        entry = r['entry']
        exit_ = r['exit']
        buf = r.get('buffer', 'N/A')
        buf_str = f"{buf}" if isinstance(buf, (int, float)) else buf
        print(f"{idx:>3} {entry:>6} {exit_:>5} {buf_str:>4} "
              f"{r['cum_return']:>8.2f} {r['sharpe']:>7.2f} {r['max_dd']:>7.2f} "
              f"{r['calmar']:>7.2f} {r['n_trades']:>7} {r['avg_positions']:>7.1f} "
              f"{r['turnover']:>7.2f} {r['win_rate']:>6.1f} {r['avg_trade_return']:>11.2f}")


def print_sensitivity_analysis(results):
    """Analyze sensitivity to entry and exit thresholds."""
    print_divider("SENSITIVITY ANALYSIS")

    # Filter to only score-based strategies
    score_results = [r for r in results if isinstance(r['entry'], (int, float))]

    # Best exit for each entry
    print("\n--- Best EXIT threshold for each ENTRY threshold ---")
    print(f"{'Entry':>6} {'BestExit':>8} {'CumRet%':>8} {'Sharpe':>7} {'MaxDD%':>7}")
    for entry in ENTRY_THRESHOLDS:
        candidates = [r for r in score_results if r['entry'] == entry]
        if candidates:
            best = max(candidates, key=lambda x: x['sharpe'])
            print(f"{entry:>6} {best['exit']:>8} {best['cum_return']:>8.2f} {best['sharpe']:>7.2f} {best['max_dd']:>7.2f}")

    # Best entry for each exit
    print(f"\n--- Best ENTRY threshold for each EXIT threshold ---")
    print(f"{'Exit':>6} {'BestEntry':>9} {'CumRet%':>8} {'Sharpe':>7} {'MaxDD%':>7}")
    for exit_ in EXIT_THRESHOLDS:
        candidates = [r for r in score_results if r['exit'] == exit_]
        if candidates:
            best = max(candidates, key=lambda x: x['sharpe'])
            print(f"{exit_:>6} {best['entry']:>9} {best['cum_return']:>8.2f} {best['sharpe']:>7.2f} {best['max_dd']:>7.2f}")

    # Buffer analysis
    print(f"\n--- Buffer Size Analysis (entry - exit) ---")
    buffer_results = defaultdict(list)
    for r in score_results:
        buf = r.get('buffer')
        if isinstance(buf, (int, float)):
            buffer_results[buf].append(r)

    print(f"{'Buffer':>6} {'Count':>6} {'AvgCumRet%':>11} {'AvgSharpe':>10} {'AvgMaxDD%':>10} {'BestSharpe':>11}")
    for buf in sorted(buffer_results.keys()):
        rlist = buffer_results[buf]
        avg_cum = np.mean([r['cum_return'] for r in rlist])
        avg_sharpe = np.mean([r['sharpe'] for r in rlist])
        avg_dd = np.mean([r['max_dd'] for r in rlist])
        best_sharpe = max(r['sharpe'] for r in rlist)
        print(f"{buf:>6} {len(rlist):>6} {avg_cum:>11.2f} {avg_sharpe:>10.2f} {avg_dd:>10.2f} {best_sharpe:>11.2f}")


def print_baseline_comparison(results, baselines):
    """Compare top strategies with baselines."""
    print_divider("BASELINE COMPARISON: Top 3 Score Strategies vs Baselines")

    score_results = [r for r in results if isinstance(r['entry'], (int, float))]
    top3 = sorted(score_results, key=lambda x: x['sharpe'], reverse=True)[:3]

    all_compare = top3 + baselines

    header = f"{'Strategy':>25} {'CumRet%':>8} {'Sharpe':>7} {'MaxDD%':>7} {'Calmar':>7} {'Trades':>7} {'AvgPos':>7} {'Win%':>6}"
    print(header)
    print('-' * len(header))

    for r in all_compare:
        if isinstance(r['entry'], (int, float)):
            name = f"Score {r['entry']}/{r['exit']}"
        else:
            name = f"{r['entry']}"
        print(f"{name:>25} {r['cum_return']:>8.2f} {r['sharpe']:>7.2f} {r['max_dd']:>7.2f} "
              f"{r['calmar']:>7.2f} {r['n_trades']:>7} {r['avg_positions']:>7.1f} {r['win_rate']:>6.1f}")


def print_position_analysis(results, top_n=10):
    """Detailed position count analysis."""
    print_divider("POSITION COUNT ANALYSIS (Top 10 by Sharpe)")

    score_results = [r for r in results if isinstance(r['entry'], (int, float))]
    top = sorted(score_results, key=lambda x: x['sharpe'], reverse=True)[:top_n]

    header = f"{'Entry':>6} {'Exit':>5} {'AvgPos':>7} {'MinPos':>7} {'MaxPos':>7} {'Days0':>6}"
    print(header)
    print('-' * len(header))

    for r in top:
        days_empty = sum(1 for p in r['daily_positions'] if p == 0)
        print(f"{r['entry']:>6} {r['exit']:>5} {r['avg_positions']:>7.1f} "
              f"{r['min_positions']:>7} {r['max_positions']:>7} {days_empty:>6}")


def print_risk_adjusted(results, baselines):
    """Risk-adjusted comparison."""
    print_divider("RISK-ADJUSTED COMPARISON")

    score_results = [r for r in results if isinstance(r['entry'], (int, float))]
    top5 = sorted(score_results, key=lambda x: x['sharpe'], reverse=True)[:5]
    all_compare = top5 + baselines

    header = f"{'Strategy':>25} {'Sharpe':>7} {'Calmar':>7} {'MaxDD%':>7} {'CumRet%':>8} {'AnnRet%':>8} {'Volatility%':>12}"
    print(header)
    print('-' * len(header))

    for r in all_compare:
        if isinstance(r['entry'], (int, float)):
            name = f"Score {r['entry']}/{r['exit']}"
        else:
            name = f"{r['entry']}"

        rets = [d['return'] for d in r['daily_returns']]
        if rets:
            vol = np.std(rets) * np.sqrt(252) * 100
            n_days = len(rets)
            ann_ret = r['cum_return'] * (252 / n_days)
        else:
            vol = 0
            ann_ret = 0

        print(f"{name:>25} {r['sharpe']:>7.2f} {r['calmar']:>7.2f} {r['max_dd']:>7.2f} "
              f"{r['cum_return']:>8.2f} {ann_ret:>8.2f} {vol:>12.2f}")


def print_trade_analysis(results, ticker_names, top_n=5):
    """Detailed trade log for top strategies."""
    print_divider("TRADE ANALYSIS (Top 5 by Sharpe)")

    score_results = [r for r in results if isinstance(r['entry'], (int, float))]
    top = sorted(score_results, key=lambda x: x['sharpe'], reverse=True)[:top_n]

    for r in top:
        print(f"\n--- Strategy: Entry={r['entry']}, Exit={r['exit']} (Buffer={r['buffer']}) ---")
        print(f"    CumReturn={r['cum_return']:.2f}%, Sharpe={r['sharpe']:.2f}, MaxDD={r['max_dd']:.2f}%")
        print(f"    Trades: {r['n_trades']}, AvgPositions: {r['avg_positions']:.1f}")
        print()

        if r['trade_log']:
            print(f"    {'Date':>10} {'Action':>6} {'Ticker':>8} {'Name':>20} {'Score':>7} {'TradeRet%':>10}")
            print(f"    {'-'*70}")
            for t in r['trade_log']:
                name = ticker_names.get(t['ticker'], t['ticker'])
                # Truncate name
                if len(name) > 18:
                    name = name[:18] + '..'
                score_str = f"{t['score']:.1f}" if isinstance(t['score'], float) else str(t['score'])
                ret_str = f"{t['trade_return']*100:.2f}" if t['action'] == 'SELL' else '-'
                print(f"    {t['date']:>10} {t['action']:>6} {t['ticker']:>8} {name:>20} {score_str:>7} {ret_str:>10}")
        else:
            print("    No trades recorded.")


def print_daily_equity_curves(results, baselines, top_n=3):
    """Print daily equity curve for top strategies and baselines."""
    print_divider("DAILY EQUITY CURVES (Top 3 + Baselines)")

    score_results = [r for r in results if isinstance(r['entry'], (int, float))]
    top = sorted(score_results, key=lambda x: x['sharpe'], reverse=True)[:top_n]
    all_strats = top + baselines

    # Build equity curves
    curves = {}
    all_dates = set()
    for r in all_strats:
        if isinstance(r['entry'], (int, float)):
            name = f"E{r['entry']}/X{r['exit']}"
        else:
            name = str(r['entry'])

        eq = 100.0
        curve = {}
        for d in r['daily_returns']:
            eq *= (1 + d['return'])
            curve[d['date']] = eq
            all_dates.add(d['date'])
        curves[name] = curve

    all_dates = sorted(all_dates)
    names = list(curves.keys())

    header = f"{'Date':>10} " + " ".join(f"{n:>12}" for n in names)
    print(header)
    print('-' * len(header))

    for date in all_dates:
        vals = []
        for n in names:
            v = curves[n].get(date, None)
            vals.append(f"{v:>12.2f}" if v is not None else f"{'N/A':>12}")
        print(f"{date:>10} " + " ".join(vals))


def print_full_grid(results):
    """Print the complete parameter grid as a matrix."""
    print_divider("FULL PARAMETER GRID -- Cumulative Return (%)")

    score_results = [r for r in results if isinstance(r['entry'], (int, float))]
    grid = {}
    for r in score_results:
        grid[(r['entry'], r['exit'])] = r

    # Print as matrix
    print(f"{'':>12}", end='')
    for exit_ in EXIT_THRESHOLDS:
        print(f"{'Exit='+str(exit_):>10}", end='')
    print()

    for entry in ENTRY_THRESHOLDS:
        print(f"{'Entry='+str(entry):>12}", end='')
        for exit_ in EXIT_THRESHOLDS:
            if entry > exit_ and (entry, exit_) in grid:
                val = grid[(entry, exit_)]['cum_return']
                print(f"{val:>10.2f}", end='')
            else:
                print(f"{'---':>10}", end='')
        print()

    print(f"\n{'':>12}", end='')
    for exit_ in EXIT_THRESHOLDS:
        print(f"{'Exit='+str(exit_):>10}", end='')
    print("\nSharpe Ratio:")

    for entry in ENTRY_THRESHOLDS:
        print(f"{'Entry='+str(entry):>12}", end='')
        for exit_ in EXIT_THRESHOLDS:
            if entry > exit_ and (entry, exit_) in grid:
                val = grid[(entry, exit_)]['sharpe']
                print(f"{val:>10.2f}", end='')
            else:
                print(f"{'---':>10}", end='')
        print()

    print(f"\n{'':>12}", end='')
    for exit_ in EXIT_THRESHOLDS:
        print(f"{'Exit='+str(exit_):>10}", end='')
    print("\nMax Drawdown (%):")

    for entry in ENTRY_THRESHOLDS:
        print(f"{'Entry='+str(entry):>12}", end='')
        for exit_ in EXIT_THRESHOLDS:
            if entry > exit_ and (entry, exit_) in grid:
                val = grid[(entry, exit_)]['max_dd']
                print(f"{val:>10.2f}", end='')
            else:
                print(f"{'---':>10}", end='')
        print()


# ============================================================
# 7. Main
# ============================================================
def main():
    print("=" * 80)
    print("  PARAMETER TUNING SIMULATION")
    print("  Korean Quant System v59 -- Strategy v6.5 'Slow In, Fast Out'")
    print("  Period: 2026-02-09 ~ 2026-03-11 (19 ranking days)")
    print("=" * 80)

    # Load rankings
    print("\n[1/5] Loading ranking data...")
    all_rankings = load_all_rankings()
    dates = sorted(all_rankings.keys())
    print(f"  Loaded {len(all_rankings)} ranking files: {dates[0]} ~ {dates[-1]}")
    for d in dates:
        print(f"    {d}: {len(all_rankings[d])} stocks")

    # Build score_100 matrix
    print("\n[2/5] Building score_100 matrix (3-day weighted)...")
    score_df, rank_df, ticker_names = build_score100_matrix(all_rankings)
    print(f"  Score matrix shape: {score_df.shape}")

    # Print score distribution
    print("\n  Score_100 distribution by date:")
    for date in dates:
        if date in score_df.index:
            scores = score_df.loc[date].dropna()
            scores = scores[scores > 0]
            if len(scores) > 0:
                above70 = (scores >= 70).sum()
                above66 = (scores >= 66).sum()
                above60 = (scores >= 60).sum()
                print(f"    {date}: mean={scores.mean():.1f}, max={scores.max():.1f}, "
                      f">=70:{above70}, >=66:{above66}, >=60:{above60}")

    # Build consecutive days map
    consec_days = build_consecutive_days(all_rankings)

    # Fetch prices
    print("\n[3/5] Fetching price data via pykrx...")
    prices_df, kospi_close, failed_tickers = fetch_all_prices(all_rankings, '20260207', '20260312')
    print(f"  Price data shape: {prices_df.shape}")
    print(f"  Price date range: {prices_df.index[0]} ~ {prices_df.index[-1]}")
    print(f"  KOSPI data points: {len(kospi_close)}")
    if failed_tickers:
        print(f"  Failed tickers ({len(failed_tickers)}): {failed_tickers[:30]}")

    # Run simulations
    print("\n[4/5] Running parameter grid simulations...")
    results = []
    total_combos = sum(1 for e in ENTRY_THRESHOLDS for x in EXIT_THRESHOLDS if e > x)
    done = 0

    for entry in ENTRY_THRESHOLDS:
        for exit_ in EXIT_THRESHOLDS:
            if entry <= exit_:
                continue
            done += 1
            result = simulate_score_strategy(score_df, prices_df, consec_days, entry, exit_)
            results.append(result)
            if done % 5 == 0:
                print(f"  Progress: {done}/{total_combos}")

    print(f"  Completed {done} parameter combinations")

    # Run baselines
    print("\n[5/5] Running baseline simulations...")
    baseline_a = simulate_baseline_top5_rank(all_rankings, prices_df, consec_days)
    baseline_b = simulate_baseline_buyhold_top5(all_rankings, prices_df)
    baseline_c = simulate_baseline_kospi(kospi_close, all_rankings)
    baselines = [baseline_a, baseline_b, baseline_c]
    print("  Baselines complete")

    # ============================================================
    # Print all results
    # ============================================================
    print("\n" + "#" * 80)
    print("#" + " " * 28 + "SIMULATION RESULTS" + " " * 28 + " #")
    print("#" * 80)

    # 0. Full parameter grid
    print_full_grid(results)

    # 1. Top 20 by Sharpe
    print_results_table(results, 'sharpe', "TOP 20 BY SHARPE RATIO", 20)

    # 2. Top 20 by Cumulative Return
    print_results_table(results, 'cum_return', "TOP 20 BY CUMULATIVE RETURN", 20)

    # 3. Sensitivity analysis
    print_sensitivity_analysis(results)

    # 4. Baseline comparison
    print_baseline_comparison(results, baselines)

    # 5. Position analysis
    print_position_analysis(results, 10)

    # 6. Risk-adjusted comparison
    print_risk_adjusted(results, baselines)

    # 7. Trade analysis
    print_trade_analysis(results, ticker_names, 5)

    # 8. Daily equity curves
    print_daily_equity_curves(results, baselines, 3)

    # ============================================================
    # Summary
    # ============================================================
    print_divider("EXECUTIVE SUMMARY")

    score_results = [r for r in results if isinstance(r['entry'], (int, float))]
    best_sharpe = max(score_results, key=lambda x: x['sharpe'])
    best_return = max(score_results, key=lambda x: x['cum_return'])
    best_calmar = max(score_results, key=lambda x: x['calmar'])

    print(f"\n  Best by Sharpe:     Entry={best_sharpe['entry']}, Exit={best_sharpe['exit']} "
          f"(Buffer={best_sharpe['buffer']}) -> Sharpe={best_sharpe['sharpe']:.2f}, "
          f"Return={best_sharpe['cum_return']:.2f}%, MaxDD={best_sharpe['max_dd']:.2f}%")

    print(f"  Best by Return:     Entry={best_return['entry']}, Exit={best_return['exit']} "
          f"(Buffer={best_return['buffer']}) -> Return={best_return['cum_return']:.2f}%, "
          f"Sharpe={best_return['sharpe']:.2f}, MaxDD={best_return['max_dd']:.2f}%")

    print(f"  Best by Calmar:     Entry={best_calmar['entry']}, Exit={best_calmar['exit']} "
          f"(Buffer={best_calmar['buffer']}) -> Calmar={best_calmar['calmar']:.2f}, "
          f"Return={best_calmar['cum_return']:.2f}%, MaxDD={best_calmar['max_dd']:.2f}%")

    print(f"\n  Baseline A (Top5 Rank): Return={baseline_a['cum_return']:.2f}%, "
          f"Sharpe={baseline_a['sharpe']:.2f}, MaxDD={baseline_a['max_dd']:.2f}%")
    print(f"  Baseline B (Buy&Hold):  Return={baseline_b['cum_return']:.2f}%, "
          f"Sharpe={baseline_b['sharpe']:.2f}, MaxDD={baseline_b['max_dd']:.2f}%")
    print(f"  Baseline C (KOSPI):     Return={baseline_c['cum_return']:.2f}%, "
          f"Sharpe={baseline_c['sharpe']:.2f}, MaxDD={baseline_c['max_dd']:.2f}%")

    # Key insight
    outperform = [r for r in score_results if r['sharpe'] > baseline_a['sharpe']]
    print(f"\n  Combos outperforming Baseline A (Sharpe): {len(outperform)} / {len(score_results)}")

    outperform_ret = [r for r in score_results if r['cum_return'] > baseline_a['cum_return']]
    print(f"  Combos outperforming Baseline A (Return): {len(outperform_ret)} / {len(score_results)}")

    # Buffer recommendation
    buffer_perf = defaultdict(list)
    for r in score_results:
        buf = r.get('buffer')
        if isinstance(buf, (int, float)):
            buffer_perf[buf].append(r['sharpe'])

    print(f"\n  Buffer size -> Average Sharpe:")
    for buf in sorted(buffer_perf.keys()):
        avg = np.mean(buffer_perf[buf])
        print(f"    Buffer {buf}: avg Sharpe = {avg:.2f}")

    print(f"\n{'='*80}")
    print("  Simulation complete.")
    print(f"{'='*80}")


if __name__ == '__main__':
    main()
