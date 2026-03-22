"""
V/Q/G/M Weight Optimization -- 3-Year Historical Backtest (2023~2026)

Monthly rebalancing, pykrx + FnGuide cache.

Factors:
- Value: PER + PBR + DIV (pykrx, 3 factors)
- Quality: ROE + GPA + CFO/Assets (FnGuide, 3 factors -- matches real strategy)
- Growth: Revenue YoY (FnGuide, replaces Forward PER)
- Momentum: (12M-1M) / vol (monthly snapshot prices)
"""
import sys
import json
import statistics
import time
import pickle
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

# KRX auth
import krx_auth
krx_auth.login()

from pykrx import stock

CACHE_DIR = Path(__file__).parent / 'data_cache'
BACKTEST_CACHE = Path(__file__).parent / 'backtest_cache'
BACKTEST_CACHE.mkdir(exist_ok=True)

MIN_MARKET_CAP = 3000_0000_0000  # 3000B KRW
TOP_N = 30
MAX_PICKS = 5


def flush_print(*args, **kwargs):
    print(*args, **kwargs)
    sys.stdout.flush()


# ============================================================
# FnGuide Financial Data
# ============================================================

def load_fnguide_financials():
    """Load all FnGuide cache files and extract key metrics."""
    flush_print("  Loading FnGuide cache files...")
    fs_files = sorted(CACHE_DIR.glob('fs_fnguide_*.parquet'))
    flush_print(f"  {len(fs_files)} files found")

    # {ticker: [(period_end, gross_profit, total_assets, cfo, revenue), ...]}
    financials = {}
    loaded = 0

    for f in fs_files:
        ticker = f.stem.replace('fs_fnguide_', '')
        try:
            df = pd.read_parquet(f)
        except Exception:
            continue

        # Use annual data only (more reliable for backtesting)
        yearly = df[df['공시구분'] == 'y']
        if yearly.empty:
            continue

        records = []
        for d in sorted(yearly['기준일'].unique()):
            subset = yearly[yearly['기준일'] == d]
            acct = dict(zip(subset['계정'], subset['값']))

            gp = acct.get('매출총이익')
            assets = acct.get('자산')
            cfo = acct.get('영업활동으로인한현금흐름')
            revenue = acct.get('매출액')
            eps = acct.get('당기순이익')  # for ROE
            equity = acct.get('자본')

            records.append({
                'date': pd.Timestamp(d),
                'gross_profit': gp,
                'total_assets': assets,
                'cfo': cfo,
                'revenue': revenue,
                'net_income': eps,
                'equity': equity,
            })

        if records:
            financials[ticker] = records
            loaded += 1

    flush_print(f"  Loaded financials for {loaded} stocks")
    return financials


def get_financials_at_date(financials, ticker, target_date):
    """Get most recent annual financials available before target_date.

    Returns dict with GPA, CFO/A, ROE, revenue_yoy or None values.
    Financial data is typically available ~3 months after fiscal year end.
    """
    if ticker not in financials:
        return None

    records = financials[ticker]
    target_ts = pd.Timestamp(target_date)

    # Find most recent annual data available before target_date
    # Assume 3-month reporting lag: 2023-12-31 data available from ~2024-03
    available = [r for r in records
                 if r['date'] + pd.Timedelta(days=90) <= target_ts]

    if not available:
        # Fallback: use oldest data if nothing is "available" yet
        available = [r for r in records if r['date'] < target_ts]

    if not available:
        return None

    # Most recent
    curr = max(available, key=lambda r: r['date'])

    result = {}

    # GPA = Gross Profit / Total Assets
    if curr['gross_profit'] and curr['total_assets'] and curr['total_assets'] > 0:
        result['gpa'] = curr['gross_profit'] / curr['total_assets']
    else:
        result['gpa'] = None

    # CFO / Assets
    if curr['cfo'] and curr['total_assets'] and curr['total_assets'] > 0:
        result['cfo_a'] = curr['cfo'] / curr['total_assets']
    else:
        result['cfo_a'] = None

    # ROE = Net Income / Equity
    if curr['net_income'] and curr['equity'] and curr['equity'] > 0:
        result['roe'] = curr['net_income'] / curr['equity']
    else:
        result['roe'] = None

    # Revenue YoY: need previous year
    prev_records = [r for r in records if r['date'] < curr['date']]
    if prev_records:
        prev = max(prev_records, key=lambda r: r['date'])
        if (curr['revenue'] is not None and prev['revenue'] is not None
                and prev['revenue'] != 0 and abs(prev['revenue']) > 0):
            result['rev_yoy'] = (curr['revenue'] - prev['revenue']) / abs(prev['revenue'])
        else:
            result['rev_yoy'] = None
    else:
        result['rev_yoy'] = None

    return result


# ============================================================
# Monthly Dates & Snapshots (cached from previous run)
# ============================================================

def get_monthly_trading_dates(start='20230101', end='20260305'):
    monthly_dates = []
    current = datetime.strptime(start, '%Y%m%d')
    end_dt = datetime.strptime(end, '%Y%m%d')

    while current <= end_dt:
        for day in range(1, 16):
            try:
                d = current.replace(day=day)
                if d > end_dt:
                    break
                d_str = d.strftime('%Y%m%d')
                tickers = stock.get_market_ticker_list(d_str, market='KOSPI')
                if len(tickers) > 0:
                    monthly_dates.append(d_str)
                    break
            except Exception:
                continue
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1, day=1)
        else:
            current = current.replace(month=current.month + 1, day=1)
    return monthly_dates


def collect_snapshot(date_str):
    cache_file = BACKTEST_CACHE / f'snapshot_{date_str}.pkl'
    if cache_file.exists():
        with open(cache_file, 'rb') as f:
            return pickle.load(f)

    flush_print(f'  [{date_str}] Collecting market data...')
    try:
        df_cap = stock.get_market_cap(date_str)
        time.sleep(0.5)
    except Exception as e:
        flush_print(f'    market_cap failed: {e}')
        return None

    try:
        df_fund = stock.get_market_fundamental(date_str)
        time.sleep(0.5)
    except Exception as e:
        flush_print(f'    fundamental failed: {e}')
        return None

    df = df_cap.join(df_fund, how='inner')

    with open(cache_file, 'wb') as f:
        pickle.dump(df, f)
    return df


# ============================================================
# Price History & Momentum
# ============================================================

def build_price_history(monthly_dates, snapshots):
    price_history = {}
    for d in monthly_dates:
        snap = snapshots.get(d)
        if snap is None:
            continue
        for ticker in snap.index:
            close = snap.loc[ticker, '종가'] if '종가' in snap.columns else 0
            if close > 0:
                if ticker not in price_history:
                    price_history[ticker] = {}
                price_history[ticker][d] = close
    return price_history


def calc_momentum_from_snapshots(ticker, current_date, price_history, monthly_dates):
    if ticker not in price_history:
        return np.nan

    ph = price_history[ticker]
    current_idx = monthly_dates.index(current_date) if current_date in monthly_dates else -1
    if current_idx < 12:
        return np.nan

    p_now = ph.get(current_date)
    if not p_now or p_now <= 0:
        return np.nan

    d_12m = monthly_dates[current_idx - 12]
    p_12m = ph.get(d_12m)
    if not p_12m or p_12m <= 0:
        return np.nan

    d_1m = monthly_dates[current_idx - 1]
    p_1m = ph.get(d_1m)
    if not p_1m or p_1m <= 0:
        return np.nan

    ret_12m = (p_now - p_12m) / p_12m
    ret_1m = (p_now - p_1m) / p_1m

    if ret_12m <= 0:
        return np.nan

    monthly_rets = []
    for i in range(current_idx - 11, current_idx + 1):
        if i < 1:
            continue
        d_curr = monthly_dates[i]
        d_prev = monthly_dates[i - 1]
        p_c = ph.get(d_curr)
        p_p = ph.get(d_prev)
        if p_c and p_p and p_c > 0 and p_p > 0:
            monthly_rets.append((p_c - p_p) / p_p)

    if len(monthly_rets) < 6:
        return np.nan

    vol = np.std(monthly_rets)
    vol = max(vol, 0.15 / (12 ** 0.5))
    return (ret_12m - ret_1m) / vol


# ============================================================
# Factor Calculation
# ============================================================

def zscore(series):
    valid = series.dropna()
    if len(valid) < 5 or valid.std() == 0:
        return series * 0
    return (series - valid.mean()) / valid.std()


def calc_factors(snapshot, current_date, price_history, monthly_dates, financials):
    df = snapshot.copy()
    df = df[df['시가총액'] >= MIN_MARKET_CAP]
    df = df[df['종가'] > 0]

    df.loc[df['PER'] <= 0, 'PER'] = np.nan
    df.loc[df['PBR'] <= 0, 'PBR'] = np.nan

    # === Value: PER + PBR + DIV (pykrx) ===
    df['v_per'] = zscore(-df['PER'].clip(upper=df['PER'].quantile(0.95)))
    df['v_pbr'] = zscore(-df['PBR'].clip(upper=df['PBR'].quantile(0.95)))
    df['v_div'] = zscore(df['DIV'])
    df['value_s'] = zscore((df['v_per'].fillna(0) + df['v_pbr'].fillna(0) +
                            df['v_div'].fillna(0)) / 3)

    # === Quality: ROE + GPA + CFO/Assets (FnGuide) ===
    roe_vals = {}
    gpa_vals = {}
    cfo_vals = {}
    rev_yoy_vals = {}

    for ticker in df.index:
        fin = get_financials_at_date(financials, ticker, current_date)
        if fin:
            roe_vals[ticker] = fin.get('roe')
            gpa_vals[ticker] = fin.get('gpa')
            cfo_vals[ticker] = fin.get('cfo_a')
            rev_yoy_vals[ticker] = fin.get('rev_yoy')

    df['roe_fn'] = pd.Series(roe_vals)
    df['gpa_fn'] = pd.Series(gpa_vals)
    df['cfo_fn'] = pd.Series(cfo_vals)

    q_roe = zscore(df['roe_fn'])
    q_gpa = zscore(df['gpa_fn'])
    q_cfo = zscore(df['cfo_fn'])
    df['quality_s'] = zscore((q_roe.fillna(0) + q_gpa.fillna(0) + q_cfo.fillna(0)) / 3)

    # === Growth: Revenue YoY (FnGuide) ===
    df['rev_yoy'] = pd.Series(rev_yoy_vals)
    df['growth_s'] = zscore(df['rev_yoy'])

    # === Momentum: (12M-1M)/vol ===
    mom_values = {}
    for ticker in df.index:
        mom_values[ticker] = calc_momentum_from_snapshots(
            ticker, current_date, price_history, monthly_dates
        )
    df['momentum_raw'] = pd.Series(mom_values)
    df['momentum_s'] = zscore(df['momentum_raw'])

    factor_cols = ['value_s', 'quality_s', 'growth_s', 'momentum_s']
    df[factor_cols] = df[factor_cols].fillna(0)

    return df


# ============================================================
# Backtest Engine
# ============================================================

def rank_and_select(df, v_w, q_w, g_w, m_w, max_picks=MAX_PICKS):
    df = df.copy()
    df['score'] = (df['value_s'] * v_w + df['quality_s'] * q_w +
                   df['growth_s'] * g_w + df['momentum_s'] * m_w)
    df = df.sort_values('score', ascending=False)
    df['composite_rank'] = range(1, len(df) + 1)
    return df.head(max_picks).index.tolist(), df


def run_historical_backtest(monthly_dates, snapshots, price_history, financials,
                            v_pct, q_pct, g_pct, m_pct):
    v_w = v_pct / 100
    q_w = q_pct / 100
    g_w = g_pct / 100
    m_w = m_pct / 100

    monthly_returns = []

    for i in range(len(monthly_dates) - 1):
        signal_date = monthly_dates[i]
        next_date = monthly_dates[i + 1]

        snapshot = snapshots.get(signal_date)
        if snapshot is None:
            monthly_returns.append(0.0)
            continue

        df = calc_factors(snapshot, signal_date, price_history, monthly_dates, financials)
        if len(df) < 10:
            monthly_returns.append(0.0)
            continue

        top_tickers, _ = rank_and_select(df, v_w, q_w, g_w, m_w)

        next_snapshot = snapshots.get(next_date)
        if next_snapshot is None:
            monthly_returns.append(0.0)
            continue

        rets = []
        for ticker in top_tickers:
            if ticker in snapshot.index and ticker in next_snapshot.index:
                p_buy = snapshot.loc[ticker, '종가']
                p_sell = next_snapshot.loc[ticker, '종가']
                if p_buy > 0 and p_sell > 0:
                    rets.append((p_sell - p_buy) / p_buy)

        monthly_returns.append(sum(rets) / len(rets) if rets else 0.0)

    if not monthly_returns:
        return None

    cumulative = 1.0
    peak = 1.0
    max_dd = 0.0
    equity = [1.0]

    for r in monthly_returns:
        cumulative *= (1 + r)
        equity.append(cumulative)
        if cumulative > peak:
            peak = cumulative
        dd = (peak - cumulative) / peak
        if dd > max_dd:
            max_dd = dd

    total_return = (cumulative - 1) * 100
    n_years = len(monthly_returns) / 12

    if len(monthly_returns) >= 2:
        mean_r = statistics.mean(monthly_returns)
        std_r = statistics.stdev(monthly_returns)
        sharpe = (mean_r / std_r) * (12 ** 0.5) if std_r > 0 else 0.0
    else:
        sharpe = 0.0

    cagr = (cumulative ** (1 / n_years) - 1) * 100 if n_years > 0 and cumulative > 0 else 0.0

    return {
        'total_return': total_return,
        'cagr': cagr,
        'sharpe': sharpe,
        'mdd': max_dd * 100,
        'monthly_returns': monthly_returns,
        'equity_curve': equity,
        'n_months': len(monthly_returns),
    }


def run_kospi_benchmark(monthly_dates, snapshots):
    """Cap-weighted benchmark (KOSPI proxy)."""
    monthly_returns = []
    for i in range(len(monthly_dates) - 1):
        d0 = monthly_dates[i]
        d1 = monthly_dates[i + 1]
        s0 = snapshots.get(d0)
        s1 = snapshots.get(d1)
        if s0 is None or s1 is None:
            monthly_returns.append(0.0)
            continue
        common = s0.index.intersection(s1.index)
        big = s0.loc[common]
        big = big[big['시가총액'] >= MIN_MARKET_CAP]
        big = big[big['종가'] > 0]
        # Filter: next month price also > 0
        valid_next = s1.loc[big.index, '종가'] > 0
        big = big[valid_next]
        if len(big) == 0:
            monthly_returns.append(0.0)
            continue
        rets = (s1.loc[big.index, '종가'] - big['종가']) / big['종가']
        weights = big['시가총액'] / big['시가총액'].sum()
        monthly_returns.append(float((rets * weights).sum()))
    return monthly_returns


def generate_weight_grid(step=5, min_w=10, max_w=40):
    combos = []
    for v in range(min_w, max_w + 1, step):
        for q in range(min_w, max_w + 1, step):
            for g in range(min_w, max_w + 1, step):
                m = 100 - v - q - g
                if min_w <= m <= max_w:
                    combos.append((v, q, g, m))
    return combos


def calc_benchmark_metrics(monthly_returns):
    cumulative = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in monthly_returns:
        cumulative *= (1 + r)
        if cumulative > peak:
            peak = cumulative
        dd = (peak - cumulative) / peak
        if dd > max_dd:
            max_dd = dd
    total = (cumulative - 1) * 100
    n_years = len(monthly_returns) / 12
    cagr = (cumulative ** (1 / n_years) - 1) * 100 if n_years > 0 and cumulative > 0 else 0
    if len(monthly_returns) >= 2:
        sharpe = (statistics.mean(monthly_returns) / statistics.stdev(monthly_returns)) * (12**0.5) if statistics.stdev(monthly_returns) > 0 else 0
    else:
        sharpe = 0
    return total, cagr, sharpe, max_dd * 100


# ============================================================
# Main
# ============================================================

def main():
    flush_print("=" * 70)
    flush_print("  Historical Backtest v2 -- FnGuide Quality/Growth")
    flush_print("  Monthly Rebalancing, 2023-01 ~ 2026-03")
    flush_print("=" * 70)
    flush_print()
    flush_print("  Factors:")
    flush_print("    Value:    PER + PBR + DIV (pykrx)")
    flush_print("    Quality:  ROE + GPA + CFO/A (FnGuide)")
    flush_print("    Growth:   Revenue YoY (FnGuide)")
    flush_print("    Momentum: (12M-1M)/vol (monthly snapshots)")
    flush_print()

    # 1. FnGuide financials
    flush_print("[1] Loading FnGuide financial data...")
    fn_cache = BACKTEST_CACHE / 'fnguide_financials.pkl'
    if fn_cache.exists():
        with open(fn_cache, 'rb') as f:
            financials = pickle.load(f)
        flush_print(f"  Loaded from cache: {len(financials)} stocks")
    else:
        financials = load_fnguide_financials()
        with open(fn_cache, 'wb') as f:
            pickle.dump(financials, f)
    flush_print()

    # 2. Monthly trading dates
    flush_print("[2] Finding monthly trading dates...")
    dates_cache = BACKTEST_CACHE / 'monthly_dates.json'
    if dates_cache.exists():
        with open(dates_cache, 'r') as f:
            monthly_dates = json.load(f)
        flush_print(f"  Loaded from cache: {len(monthly_dates)} dates")
    else:
        monthly_dates = get_monthly_trading_dates('20230101', '20260305')
        with open(dates_cache, 'w') as f:
            json.dump(monthly_dates, f)
    flush_print(f"  Period: {monthly_dates[0]} ~ {monthly_dates[-1]}")
    flush_print()

    # 3. Collect snapshots
    flush_print("[3] Collecting market snapshots...")
    snapshots = {}
    for d in monthly_dates:
        snap = collect_snapshot(d)
        if snap is not None:
            snapshots[d] = snap
            flush_print(f'  {d}: {len(snap)} stocks')
        else:
            flush_print(f'  {d}: FAILED')
    flush_print(f"  Collected: {len(snapshots)}/{len(monthly_dates)}")
    flush_print()

    # 4. Price history
    flush_print("[4] Building price history from snapshots...")
    price_history = build_price_history(monthly_dates, snapshots)
    flush_print(f"  {len(price_history)} tickers")
    flush_print()

    # 5. KOSPI benchmark
    flush_print("[5] Computing KOSPI benchmark...")
    kospi_monthly = run_kospi_benchmark(monthly_dates, snapshots)
    k_total, k_cagr, k_sharpe, k_mdd = calc_benchmark_metrics(kospi_monthly)
    flush_print(f"  KOSPI: Total={k_total:.1f}%, CAGR={k_cagr:.1f}%, "
                f"Sharpe={k_sharpe:.2f}, MDD={k_mdd:.1f}%")
    flush_print()

    # 6. Weight grid backtest
    flush_print("[6] Running weight optimization...")
    combos = generate_weight_grid(step=5)
    flush_print(f"  Testing {len(combos)} weight combinations")
    flush_print()

    results = []
    for idx, (v, q, g, m) in enumerate(combos):
        result = run_historical_backtest(
            monthly_dates, snapshots, price_history, financials, v, q, g, m
        )
        if result:
            results.append({
                'label': f"V{v}/Q{q}/G{g}/M{m}",
                'v': v, 'q': q, 'g': g, 'm': m,
                **result,
            })
        if (idx + 1) % 50 == 0:
            flush_print(f"  {idx + 1}/{len(combos)} done...")

    flush_print(f"\n  Completed: {len(results)} valid results")
    flush_print()

    # =========================================================
    # Results
    # =========================================================

    flush_print("=" * 80)
    flush_print("  SHARPE RATIO TOP 20")
    flush_print("=" * 80)
    by_sharpe = sorted(results, key=lambda x: -x['sharpe'])
    flush_print(f"{'Rank':>4} {'Weights':<20} {'CAGR':>8} {'Total':>8} "
                f"{'Sharpe':>8} {'MDD':>8} {'Months':>6}")
    flush_print("-" * 70)
    for i, r in enumerate(by_sharpe[:20]):
        marker = " <-- CURRENT" if r['label'] == 'V30/Q25/G25/M20' else ""
        flush_print(f"{i+1:>4} {r['label']:<20} {r['cagr']:>7.1f}% "
                    f"{r['total_return']:>7.1f}% {r['sharpe']:>8.2f} "
                    f"{r['mdd']:>7.1f}% {r['n_months']:>5}{marker}")

    # Current strategy
    flush_print()
    current = next((r for r in results if r['label'] == 'V30/Q25/G25/M20'), None)
    if current:
        sharpe_rank = by_sharpe.index(current) + 1
        ret_sorted = sorted(results, key=lambda x: -x['total_return'])
        ret_rank = ret_sorted.index(current) + 1
        mdd_sorted = sorted(results, key=lambda x: x['mdd'])
        mdd_rank = mdd_sorted.index(current) + 1
        flush_print(f"--- CURRENT: V30/Q25/G25/M20 ---")
        flush_print(f"  CAGR:    {current['cagr']:>7.1f}%  (rank {ret_rank}/{len(results)})")
        flush_print(f"  Total:   {current['total_return']:>7.1f}%")
        flush_print(f"  Sharpe:  {current['sharpe']:>7.2f}   (rank {sharpe_rank}/{len(results)})")
        flush_print(f"  MDD:     {current['mdd']:>7.1f}%  (rank {mdd_rank}/{len(results)})")

    # Benchmark
    flush_print()
    flush_print(f"--- BENCHMARK: KOSPI (cap-weighted) ---")
    flush_print(f"  CAGR:    {k_cagr:>7.1f}%")
    flush_print(f"  Total:   {k_total:>7.1f}%")
    flush_print(f"  Sharpe:  {k_sharpe:>7.2f}")
    flush_print(f"  MDD:     {k_mdd:>7.1f}%")

    # Return TOP 10
    flush_print()
    flush_print("=" * 80)
    flush_print("  RETURN TOP 10")
    flush_print("=" * 80)
    by_return = sorted(results, key=lambda x: -x['total_return'])
    for i, r in enumerate(by_return[:10]):
        flush_print(f"{i+1:>4} {r['label']:<20} CAGR={r['cagr']:>6.1f}% "
                    f"Total={r['total_return']:>7.1f}% Sharpe={r['sharpe']:>5.2f} "
                    f"MDD={r['mdd']:>5.1f}%")

    # MDD TOP 10
    flush_print()
    flush_print("=" * 80)
    flush_print("  MDD TOP 10 (lowest drawdown)")
    flush_print("=" * 80)
    by_mdd = sorted(results, key=lambda x: x['mdd'])
    for i, r in enumerate(by_mdd[:10]):
        flush_print(f"{i+1:>4} {r['label']:<20} CAGR={r['cagr']:>6.1f}% "
                    f"Total={r['total_return']:>7.1f}% Sharpe={r['sharpe']:>5.2f} "
                    f"MDD={r['mdd']:>5.1f}%")

    # Composite
    flush_print()
    flush_print("=" * 80)
    flush_print("  COMPOSITE TOP 10 (Return + Sharpe + MDD rank sum)")
    flush_print("=" * 80)
    ret_sorted = sorted(results, key=lambda x: -x['total_return'])
    sharpe_sorted = sorted(results, key=lambda x: -x['sharpe'])
    mdd_sorted = sorted(results, key=lambda x: x['mdd'])
    for r in results:
        r['ret_rank'] = ret_sorted.index(r) + 1
        r['sharpe_rank'] = sharpe_sorted.index(r) + 1
        r['mdd_rank'] = mdd_sorted.index(r) + 1
        r['composite'] = r['ret_rank'] + r['sharpe_rank'] + r['mdd_rank']

    by_composite = sorted(results, key=lambda x: x['composite'])
    for i, r in enumerate(by_composite[:10]):
        marker = " <-- CURRENT" if r['label'] == 'V30/Q25/G25/M20' else ""
        flush_print(f"{i+1:>4} {r['label']:<20} CAGR={r['cagr']:>6.1f}% "
                    f"Sharpe={r['sharpe']:>5.2f} MDD={r['mdd']:>5.1f}% "
                    f"(R:{r['ret_rank']} S:{r['sharpe_rank']} M:{r['mdd_rank']} "
                    f"sum:{r['composite']}){marker}")

    # Factor sensitivity
    flush_print()
    flush_print("=" * 80)
    flush_print("  FACTOR SENSITIVITY")
    flush_print("=" * 80)
    for factor, key in [('Value', 'v'), ('Quality', 'q'),
                        ('Growth', 'g'), ('Momentum', 'm')]:
        flush_print(f"\n  {factor}:")
        levels = sorted(set(r[key] for r in results))
        for level in levels:
            subset = [r for r in results if r[key] == level]
            avg_cagr = statistics.mean([r['cagr'] for r in subset])
            avg_sharpe = statistics.mean([r['sharpe'] for r in subset])
            avg_mdd = statistics.mean([r['mdd'] for r in subset])
            flush_print(f"    {level:>2}%: CAGR={avg_cagr:>6.1f}%  "
                        f"sharpe={avg_sharpe:>5.2f}  mdd={avg_mdd:>5.1f}%")

    # vs KOSPI alpha
    flush_print()
    flush_print("=" * 80)
    flush_print("  ALPHA vs KOSPI (strategy CAGR - KOSPI CAGR)")
    flush_print("=" * 80)
    for i, r in enumerate(by_composite[:10]):
        alpha = r['cagr'] - k_cagr
        flush_print(f"  {r['label']:<20} alpha={alpha:>+6.1f}%")

    # Save
    results_file = BACKTEST_CACHE / 'backtest_results_v2.json'
    save_data = [{k: v for k, v in r.items()
                  if k not in ('monthly_returns', 'equity_curve')}
                 for r in results]
    with open(results_file, 'w', encoding='utf-8') as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2)
    flush_print(f"\nResults saved to {results_file}")


if __name__ == '__main__':
    main()
