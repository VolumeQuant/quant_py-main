"""High-performance portfolio simulator — numpy array indexing, zero pandas in hot loop

Drop-in replacement for CachedSimulator.run_fast() with 30x+ speedup.
All pandas DataFrame.loc calls replaced with pre-indexed numpy array lookups.
Cache building uses vectorized numpy operations instead of per-dict Python loops.

Architecture:
  1. One-time setup: convert prices DataFrame + all_rankings → numpy arrays
  2. _ensure_cache: vectorized reweight + status computation (numpy-native)
  3. run_fast: pure Python + numpy array[int, int] indexing (no pandas at all)

Usage:
    from fast_simulator import FastSimulator
    fsim = FastSimulator(all_rankings, dates, prices, bench)
    result = fsim.run_fast(v_w, q_w, g_w, m_w, g_rev,
                           entry_param=5, exit_param=10.0, max_slots=5)
"""
import numpy as np
import pandas as pd
from math import isnan

# Status enum (avoid string comparisons in hot loop)
_ST_VERIFIED = 0
_ST_PENDING = 1
_ST_NEW = 2
_ST_OUTSIDE = 3

_STATUS_MAP = {'verified': _ST_VERIFIED, 'pending': _ST_PENDING,
               'new': _ST_NEW, 'outside': _ST_OUTSIDE}


def _calc_metrics(daily_rets, bench_rets, holdings_count):
    """Identical to ProductionSimulator._calc_metrics but standalone."""
    arr = np.asarray(daily_rets, dtype=np.float64)
    n = len(arr)
    if n == 0 or arr.std() == 0:
        return {'cagr': 0, 'sharpe': 0, 'sortino': 0, 'calmar': 0,
                'mdd': 0, 'total': 0, 'b_cagr': 0, 'alpha': 0, 'avg_holdings': 0}

    equity = np.cumprod(1 + arr)
    total = (equity[-1] - 1) * 100
    cagr = (equity[-1] ** (252 / max(n, 1)) - 1) * 100
    mean_r = arr.mean()
    std_r = arr.std()
    sharpe = mean_r / std_r * np.sqrt(252)

    down = arr[arr < 0]
    down_std = down.std() if len(down) > 0 else std_r
    sortino = (mean_r / down_std * np.sqrt(252)) if down_std > 0 else sharpe

    eq_with_1 = np.empty(n + 1)
    eq_with_1[0] = 1.0
    eq_with_1[1:] = equity
    peak = np.maximum.accumulate(eq_with_1)
    dd = (eq_with_1 - peak) / peak
    mdd = abs(dd.min()) * 100

    calmar = cagr / mdd if mdd > 0 else 0

    b_arr = np.asarray(bench_rets, dtype=np.float64)
    b_equity = np.cumprod(1 + b_arr)
    b_cagr = (b_equity[-1] ** (252 / max(len(b_arr), 1)) - 1) * 100

    avg_h = np.mean(holdings_count) if holdings_count else 0

    return {
        'cagr': round(cagr, 2), 'sharpe': round(sharpe, 3),
        'sortino': round(sortino, 3), 'calmar': round(calmar, 3),
        'mdd': round(mdd, 2), 'total': round(total, 2),
        'b_cagr': round(b_cagr, 2), 'alpha': round(cagr - b_cagr, 2),
        'avg_holdings': round(avg_h, 1),
    }


class FastSimulator:
    """Numpy-accelerated portfolio simulator.

    Same semantics as CachedSimulator but all hot-path operations use
    numpy integer-indexed array lookups instead of pandas .loc.

    Cache building uses vectorized numpy operations to avoid per-dict loops
    in _reweight and _compute_status.
    """

    def __init__(self, all_rankings, dates, prices, bench=None):
        self.all_rankings = all_rankings
        self.dates = dates

        # ---- One-time conversion: prices DataFrame → numpy arrays ----
        self._price_arr = prices.values.astype(np.float64)  # (n_dates, n_tickers)

        # Date string → row index in price_arr
        ts_index = prices.index
        self._date_to_row = {}
        for row_i in range(len(ts_index)):
            self._date_to_row[ts_index[row_i].strftime('%Y%m%d')] = row_i

        # Ticker string → column index in price_arr
        col_list = list(prices.columns)
        self._ticker_to_col = {tk: ci for ci, tk in enumerate(col_list)}

        # Benchmark: 1D numpy array aligned to same date index
        self._has_bench = bench is not None and not bench.empty
        if self._has_bench:
            bench_aligned = bench.reindex(ts_index)
            self._bench_arr = bench_aligned.iloc[:, 0].values.astype(np.float64)
        else:
            self._bench_arr = None

        # Map each date in self.dates to a row index (or -1 if missing)
        self._date_row_indices = [self._date_to_row.get(d, -1) for d in self.dates]

        # ---- Pre-extract all_rankings into numpy arrays (one-time cost) ----
        # For each date, extract sub-factor scores into arrays indexed by
        # a global ticker index. This avoids repeated dict.get() in _reweight.
        self._preextracted = {}  # date → (tickers, value_s, quality_s, growth_s, momentum_s, rev_z, oca_z, prices, col_indices)
        tk_to_col = self._ticker_to_col
        for date in dates:
            rankings = all_rankings.get(date, [])
            if not rankings:
                self._preextracted[date] = None
                continue
            n = len(rankings)
            tickers = [None] * n
            value_s = np.empty(n, dtype=np.float64)
            quality_s = np.empty(n, dtype=np.float64)
            growth_s = np.empty(n, dtype=np.float64)
            momentum_s = np.empty(n, dtype=np.float64)
            rev_z = np.empty(n, dtype=np.float64)
            oca_z = np.empty(n, dtype=np.float64)
            r_prices = np.empty(n, dtype=np.float64)
            col_indices = np.empty(n, dtype=np.int32)

            for j, s in enumerate(rankings):
                tk = s['ticker']
                tickers[j] = tk
                value_s[j] = s.get('value_s') or 0.0
                quality_s[j] = s.get('quality_s') or 0.0
                growth_s[j] = s.get('growth_s') or 0.0
                momentum_s[j] = s.get('momentum_s') or 0.0
                rev_z[j] = s.get('rev_z') or 0.0
                oca_z[j] = s.get('oca_z') or 0.0
                p = s.get('price')
                r_prices[j] = float(p) if p is not None else 0.0
                col_indices[j] = tk_to_col.get(tk, -1)

            self._preextracted[date] = (tickers, value_s, quality_s, growth_s,
                                        momentum_s, rev_z, oca_z, r_prices, col_indices)

        # Cache state
        self._cached_key = None
        self._cached_pipelines = None

    def _vectorized_reweight(self, date, v_w, q_w, g_w, m_w, g_rev):
        """Vectorized reweight: returns (tickers, new_scores, new_ranks, prices, col_indices) or None."""
        pre = self._preextracted.get(date)
        if pre is None:
            return None

        tickers, value_s, quality_s, growth_s, momentum_s, rev_z, oca_z, r_prices, col_indices = pre
        n = len(tickers)

        use_original_g = abs(g_rev - 0.5) < 0.01
        if use_original_g:
            new_scores = v_w * value_s + q_w * quality_s + g_w * growth_s + m_w * momentum_s
        else:
            g_raw = g_rev * rev_z + (1 - g_rev) * oca_z
            g_std = g_raw.std()
            if g_std > 0:
                g_standardized = (g_raw - g_raw.mean()) / g_std
            else:
                g_standardized = np.zeros(n)
            new_scores = v_w * value_s + q_w * quality_s + g_w * g_standardized + m_w * momentum_s

        # Sort descending by score → assign ranks
        sort_idx = np.argsort(-new_scores)
        new_ranks = np.empty(n, dtype=np.int32)
        new_ranks[sort_idx] = np.arange(1, n + 1)

        return (tickers, new_scores, new_ranks, r_prices, col_indices)

    def _vectorized_compute_status(self, rw_t0, rw_t1, rw_t2, top_n):
        """Vectorized compute_status: returns pipeline tuple or None."""
        if rw_t0 is None:
            return None

        tickers_0, scores_0, ranks_0, prices_0, cols_0 = rw_t0
        n = len(tickers_0)

        # Build ticker→index maps for t1, t2
        if rw_t1 is not None:
            tickers_1, scores_1, ranks_1, _, _ = rw_t1
            tk_to_idx_1 = {tk: j for j, tk in enumerate(tickers_1)}
        else:
            tk_to_idx_1 = None

        if rw_t2 is not None:
            tickers_2, scores_2, ranks_2, _, _ = rw_t2
            tk_to_idx_2 = {tk: j for j, tk in enumerate(tickers_2)}
        else:
            tk_to_idx_2 = None

        # Top-n sets (by rank)
        top_t0 = set()
        for j in range(n):
            if ranks_0[j] <= top_n:
                top_t0.add(tickers_0[j])

        top_t1 = set()
        if rw_t1 is not None:
            for j in range(len(tickers_1)):
                if ranks_1[j] <= top_n:
                    top_t1.add(tickers_1[j])

        top_t2 = set()
        if rw_t2 is not None:
            for j in range(len(tickers_2)):
                if ranks_2[j] <= top_n:
                    top_t2.add(tickers_2[j])

        # Build output arrays
        tk_cols = np.empty(n, dtype=np.int32)
        w_ranks = np.empty(n, dtype=np.float64)
        sc_100s = np.empty(n, dtype=np.float64)
        stats = np.empty(n, dtype=np.int8)
        entry_prices = np.empty(n, dtype=np.float64)
        col_to_pipe_idx = {}

        for j in range(n):
            tk = tickers_0[j]
            col = cols_0[j]
            tk_cols[j] = col

            # Status
            in_t0 = tk in top_t0
            in_t1 = tk in top_t1
            in_t2 = tk in top_t2
            if in_t0 and in_t1 and in_t2:
                stats[j] = _ST_VERIFIED
            elif in_t0 and in_t1:
                stats[j] = _ST_PENDING
            elif in_t0:
                stats[j] = _ST_NEW
            else:
                stats[j] = _ST_OUTSIDE

            # Weighted score
            s0 = scores_0[j]
            if tk_to_idx_1 is not None:
                idx1 = tk_to_idx_1.get(tk)
                s1 = scores_1[idx1] if idx1 is not None else 0.0
            else:
                s1 = 0.0

            if tk_to_idx_2 is not None:
                idx2 = tk_to_idx_2.get(tk)
                s2 = scores_2[idx2] if idx2 is not None else 0.0
            else:
                s2 = 0.0

            if tk_to_idx_1 is not None and tk_to_idx_2 is not None:
                ws = s0 * 0.5 + s1 * 0.3 + s2 * 0.2
            elif tk_to_idx_1 is not None:
                ws = s0 * 0.6 + s1 * 0.4
            else:
                ws = s0

            sc_100 = (ws + 0.7) / 2.4 * 100.0
            if sc_100 < 0.0:
                sc_100 = 0.0
            elif sc_100 > 100.0:
                sc_100 = 100.0
            sc_100s[j] = sc_100

            # Weighted rank
            r0 = ranks_0[j]
            if tk_to_idx_1 is not None:
                idx1 = tk_to_idx_1.get(tk)
                r1 = ranks_1[idx1] if idx1 is not None else 999
            else:
                r1 = 999

            if tk_to_idx_2 is not None:
                idx2 = tk_to_idx_2.get(tk)
                r2 = ranks_2[idx2] if idx2 is not None else 999
            else:
                r2 = 999

            if tk_to_idx_1 is not None and tk_to_idx_2 is not None:
                w_rank = r0 * 0.5 + r1 * 0.3 + r2 * 0.2
            elif tk_to_idx_1 is not None:
                w_rank = r0 * 0.6 + r1 * 0.4
            else:
                w_rank = float(r0)
            w_ranks[j] = w_rank

            entry_prices[j] = prices_0[j]
            if col >= 0:
                col_to_pipe_idx[col] = j

        # Sort by (weighted_rank asc, raw_score desc) to match original
        # We need to reorder the arrays
        sort_keys = np.lexsort((-scores_0, w_ranks))
        tk_cols = tk_cols[sort_keys]
        w_ranks = w_ranks[sort_keys]
        sc_100s = sc_100s[sort_keys]
        stats = stats[sort_keys]
        entry_prices = entry_prices[sort_keys]

        # Rebuild col_to_pipe_idx after sorting
        col_to_pipe_idx = {}
        for j in range(n):
            col = tk_cols[j]
            if col >= 0:
                col_to_pipe_idx[col] = j

        return (tk_cols, w_ranks, sc_100s, stats, entry_prices, col_to_pipe_idx)

    def _ensure_cache(self, v_w, q_w, g_w, m_w, g_rev, top_n=20):
        """Build reweight + status cache using vectorized operations."""
        key = (v_w, q_w, g_w, m_w, g_rev, top_n)
        if self._cached_key == key:
            return
        self._cached_key = key

        dates = self.dates
        n_dates = len(dates)

        # Step 1: Vectorized reweight for all dates
        reweighted = [None] * n_dates
        for i in range(n_dates):
            reweighted[i] = self._vectorized_reweight(dates[i], v_w, q_w, g_w, m_w, g_rev)

        # Step 2: Vectorized compute_status for all dates
        pipelines = [None] * n_dates
        for i in range(2, n_dates):
            rw0 = reweighted[i]
            rw1 = reweighted[i - 1]
            rw2 = reweighted[i - 2]
            if rw0 is not None:
                pipelines[i] = self._vectorized_compute_status(rw0, rw1, rw2, top_n)

        self._cached_pipelines = pipelines

    def run_fast(self, v_w, q_w, g_w, m_w, g_rev,
                 entry_param, exit_param, max_slots, top_n=20, stop_loss=-0.10):
        """Run portfolio simulation using numpy array indexing only."""
        self._ensure_cache(v_w, q_w, g_w, m_w, g_rev, top_n)

        price_arr = self._price_arr
        bench_arr = self._bench_arr
        has_bench = self._has_bench
        date_rows = self._date_row_indices
        pipelines = self._cached_pipelines
        n_dates = len(self.dates)

        # Portfolio: dict {col_idx: entry_price}
        portfolio = {}
        daily_rets = [0.0, 0.0]  # first 2 days are always 0
        bench_rets = [0.0, 0.0]
        holdings_count = [0, 0]

        use_stop_loss = stop_loss is not None

        for i in range(2, n_dates):
            pipe = pipelines[i]
            if pipe is None:
                daily_rets.append(0.0)
                bench_rets.append(0.0)
                holdings_count.append(len(portfolio))
                continue

            tk_cols, w_ranks, sc_100s, stats, entry_prices, col_to_pipe_idx = pipe
            cur_row = date_rows[i]

            # === EXIT ===
            if portfolio:
                to_remove = []
                for col, ep in portfolio.items():
                    should_exit = False

                    # 1. Stop loss
                    if use_stop_loss and cur_row >= 0 and col >= 0:
                        cur_p = price_arr[cur_row, col]
                        if cur_p == cur_p and ep > 0:  # NaN check: x != x means NaN
                            if (cur_p / ep - 1.0) <= stop_loss:
                                should_exit = True

                    # 2. Strategy exit (weighted_rank > exit_param)
                    if not should_exit:
                        pidx = col_to_pipe_idx.get(col)
                        if pidx is None:
                            should_exit = True  # ticker not in today's ranking
                        else:
                            should_exit = w_ranks[pidx] > exit_param

                    if should_exit:
                        to_remove.append(col)

                for col in to_remove:
                    del portfolio[col]

            # === ENTRY ===
            slots_avail = max_slots - len(portfolio) if max_slots > 0 else 999
            if slots_avail > 0:
                # Find verified candidates with weighted_rank <= entry_param
                # Pre-filter using numpy boolean indexing
                mask = (stats == _ST_VERIFIED) & (w_ranks <= entry_param) & (entry_prices > 0)
                cand_indices = np.where(mask)[0]

                if len(cand_indices) > 0:
                    # Sort by -score_100 (descending)
                    if len(cand_indices) > 1:
                        sort_order = np.argsort(-sc_100s[cand_indices])
                        cand_indices = cand_indices[sort_order]

                    for ci in cand_indices:
                        if slots_avail <= 0:
                            break
                        col = tk_cols[ci]
                        if col < 0:
                            continue
                        if col in portfolio:
                            continue
                        portfolio[col] = entry_prices[ci]
                        slots_avail -= 1

            n_hold = len(portfolio)
            holdings_count.append(n_hold)

            # === DAILY RETURN ===
            if i + 1 < n_dates and n_hold > 0:
                next_row = date_rows[i + 1]
                if next_row >= 0 and cur_row >= 0:
                    total_ret = 0.0
                    count = 0
                    for col in portfolio:
                        c_p = price_arr[next_row, col]
                        p_p = price_arr[cur_row, col]
                        # NaN check via c_p == c_p
                        if c_p == c_p and p_p == p_p and p_p > 0:
                            total_ret += c_p / p_p - 1.0
                            count += 1
                    daily_rets.append(total_ret / count if count > 0 else 0.0)

                    # Benchmark
                    if has_bench:
                        b_c = bench_arr[next_row]
                        b_p = bench_arr[cur_row]
                        if b_c == b_c and b_p == b_p and b_p > 0:
                            bench_rets.append(b_c / b_p - 1.0)
                        else:
                            bench_rets.append(0.0)
                    else:
                        bench_rets.append(0.0)
                else:
                    daily_rets.append(0.0)
                    bench_rets.append(0.0)
            else:
                daily_rets.append(0.0)
                bench_rets.append(0.0)

        return _calc_metrics(daily_rets, bench_rets, holdings_count)


class FastSimulatorFromCache:
    """Even faster: takes pre-built pipelines from FastSimulator._ensure_cache.

    Use when you want to run many entry/exit/slots combos on the same
    (v_w, q_w, g_w, m_w, g_rev) without rebuilding the cache each time.

    Usage:
        fsim = FastSimulator(all_rankings, dates, prices, bench)
        fsim._ensure_cache(v_w, q_w, g_w, m_w, g_rev)
        runner = FastSimulatorFromCache(
            fsim._cached_pipelines, fsim._price_arr,
            fsim._bench_arr, fsim._date_row_indices, len(dates))
        for entry_p, exit_p, slots in combos:
            result = runner.run(entry_p, exit_p, slots)
    """

    def __init__(self, pipelines, price_arr, bench_arr, date_row_indices, n_dates):
        self.pipelines = pipelines
        self.price_arr = price_arr
        self.bench_arr = bench_arr
        self.has_bench = bench_arr is not None
        self.date_rows = date_row_indices
        self.n_dates = n_dates

    def run(self, entry_param, exit_param, max_slots, stop_loss=-0.10):
        """Same logic as FastSimulator.run_fast but avoids _ensure_cache overhead."""
        price_arr = self.price_arr
        bench_arr = self.bench_arr
        has_bench = self.has_bench
        date_rows = self.date_rows
        pipelines = self.pipelines
        n_dates = self.n_dates

        portfolio = {}
        daily_rets = [0.0, 0.0]
        bench_rets = [0.0, 0.0]
        holdings_count = [0, 0]

        use_stop_loss = stop_loss is not None

        for i in range(2, n_dates):
            pipe = pipelines[i]
            if pipe is None:
                daily_rets.append(0.0)
                bench_rets.append(0.0)
                holdings_count.append(len(portfolio))
                continue

            tk_cols, w_ranks, sc_100s, stats, entry_prices, col_to_pipe_idx = pipe
            cur_row = date_rows[i]

            # === EXIT ===
            if portfolio:
                to_remove = []
                for col, ep in portfolio.items():
                    should_exit = False
                    if use_stop_loss and cur_row >= 0 and col >= 0:
                        cur_p = price_arr[cur_row, col]
                        if cur_p == cur_p and ep > 0:
                            if (cur_p / ep - 1.0) <= stop_loss:
                                should_exit = True
                    if not should_exit:
                        pidx = col_to_pipe_idx.get(col)
                        if pidx is None:
                            should_exit = True
                        else:
                            should_exit = w_ranks[pidx] > exit_param
                    if should_exit:
                        to_remove.append(col)
                for col in to_remove:
                    del portfolio[col]

            # === ENTRY ===
            slots_avail = max_slots - len(portfolio) if max_slots > 0 else 999
            if slots_avail > 0:
                mask = (stats == _ST_VERIFIED) & (w_ranks <= entry_param) & (entry_prices > 0)
                cand_indices = np.where(mask)[0]
                if len(cand_indices) > 0:
                    if len(cand_indices) > 1:
                        sort_order = np.argsort(-sc_100s[cand_indices])
                        cand_indices = cand_indices[sort_order]
                    for ci in cand_indices:
                        if slots_avail <= 0:
                            break
                        col = tk_cols[ci]
                        if col < 0 or col in portfolio:
                            continue
                        portfolio[col] = entry_prices[ci]
                        slots_avail -= 1

            n_hold = len(portfolio)
            holdings_count.append(n_hold)

            # === DAILY RETURN ===
            if i + 1 < n_dates and n_hold > 0:
                next_row = date_rows[i + 1]
                if next_row >= 0 and cur_row >= 0:
                    total_ret = 0.0
                    count = 0
                    for col in portfolio:
                        c_p = price_arr[next_row, col]
                        p_p = price_arr[cur_row, col]
                        if c_p == c_p and p_p == p_p and p_p > 0:
                            total_ret += c_p / p_p - 1.0
                            count += 1
                    daily_rets.append(total_ret / count if count > 0 else 0.0)

                    if has_bench:
                        b_c = bench_arr[next_row]
                        b_p = bench_arr[cur_row]
                        if b_c == b_c and b_p == b_p and b_p > 0:
                            bench_rets.append(b_c / b_p - 1.0)
                        else:
                            bench_rets.append(0.0)
                    else:
                        bench_rets.append(0.0)
                else:
                    daily_rets.append(0.0)
                    bench_rets.append(0.0)
            else:
                daily_rets.append(0.0)
                bench_rets.append(0.0)

        return _calc_metrics(daily_rets, bench_rets, holdings_count)
