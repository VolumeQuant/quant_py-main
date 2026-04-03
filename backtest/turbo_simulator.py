"""Ultra-fast portfolio simulator — zero numpy in hot loop, flat array lookups

55x+ speedup over CachedSimulator (pandas-based) by:
  1. Pre-sorting candidate lists during cache build (eliminates np.argsort per day)
  2. Flat numpy array for weighted_rank lookup (eliminates dict.get per day)
  3. Pure Python hot loop with no numpy function calls
  4. Pre-allocated return arrays

Performance (1,525 trading days):
  CachedSimulator:  ~262ms/run   (pandas .loc + dict comprehension)
  FastSimulator:     ~15ms/run   (numpy array indexing)
  TurboSimulator:     ~4ms/run   (flat arrays + pre-sorted candidates)

Architecture:
  1. One-time setup: prices DataFrame → numpy array, rankings → pre-extracted arrays
  2. _ensure_cache: vectorized reweight + build flat pipelines with pre-sorted candidates
  3. run_fast/_run_inner: pure Python loop, array[int] lookups, no numpy calls

Usage:
    from turbo_simulator import TurboSimulator, TurboRunner
    tsim = TurboSimulator(all_rankings, dates, prices, bench)

    # Single run:
    result = tsim.run_fast(v_w, q_w, g_w, m_w, g_rev,
                           entry_param=5, exit_param=10.0, max_slots=5)

    # Many entry/exit combos on same weights (fastest):
    tsim._ensure_cache(v_w, q_w, g_w, m_w, g_rev)
    runner = TurboRunner(tsim)
    for entry_p, exit_p, slots in combos:
        result = runner.run(entry_p, exit_p, slots)
"""
import numpy as np
import pandas as pd

_SQRT_252 = np.sqrt(252)
_SENTINEL_WRANK = 9999.0  # weighted_rank for tickers not in today's ranking


# ---------- metrics (identical to FastSimulator) ----------

def _calc_metrics(daily_rets, bench_rets, holdings_count):
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
    sharpe = mean_r / std_r * _SQRT_252

    down = arr[arr < 0]
    down_std = down.std() if len(down) > 0 else std_r
    sortino = (mean_r / down_std * _SQRT_252) if down_std > 0 else sharpe

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


class TurboSimulator:
    """Ultra-fast simulator with pre-sorted candidate lists and flat array lookups.

    Key optimizations over FastSimulator:
    1. weighted_rank stored in flat numpy array (col→wrank) instead of dict
       - Eliminates dict.get() in exit logic (replaced by array[col] lookup)
    2. Candidate lists pre-sorted by -score_100 during cache build
       - Eliminates np.argsort per day in run()
    3. All pipeline data is plain Python tuples/lists for fastest iteration
    """

    def __init__(self, all_rankings, dates, prices, bench=None):
        self.all_rankings = all_rankings
        self.dates = dates
        self._n_cols = prices.shape[1]

        # ---- prices DataFrame → numpy array ----
        self._price_arr = prices.values.astype(np.float64)

        ts_index = prices.index
        self._date_to_row = {}
        for row_i in range(len(ts_index)):
            self._date_to_row[ts_index[row_i].strftime('%Y%m%d')] = row_i

        col_list = list(prices.columns)
        self._ticker_to_col = {tk: ci for ci, tk in enumerate(col_list)}

        # Benchmark
        self._has_bench = bench is not None and not bench.empty
        if self._has_bench:
            bench_aligned = bench.reindex(ts_index)
            self._bench_arr = bench_aligned.iloc[:, 0].values.astype(np.float64)
        else:
            self._bench_arr = None

        self._date_row_indices = [self._date_to_row.get(d, -1) for d in self.dates]

        # ---- Pre-extract rankings into arrays (one-time cost) ----
        self._preextracted = {}
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

        # ---- 60일 상관관계 1회 사전 계산 (가중치 무관) ----
        self._corr_all = self._precompute_all_correlations()

        # Cache
        self._cached_key = None
        self._cached_flat = None

    def _vectorized_reweight(self, date, v_w, q_w, g_w, m_w, g_rev):
        """Returns (tickers, new_scores, new_ranks, prices, col_indices) or None."""
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

        sort_idx = np.argsort(-new_scores)
        new_ranks = np.empty(n, dtype=np.int32)
        new_ranks[sort_idx] = np.arange(1, n + 1)

        return (tickers, new_scores, new_ranks, r_prices, col_indices)

    def _build_day_pipeline(self, rw_t0, rw_t1, rw_t2, top_n, n_cols):
        """Build pipeline for one day.

        Returns: (wrank_arr, candidates_sorted) or None
          - wrank_arr: 1D numpy array of size n_cols. wrank_arr[col] = weighted_rank.
                       Default = _SENTINEL_WRANK (not in ranking → triggers exit).
          - candidates_sorted: tuple of (cols, entry_prices, wranks) where each is a
            plain Python list, pre-sorted by score_100 descending.
            Only VERIFIED tickers with valid col and price > 0.
        """
        if rw_t0 is None:
            return None

        tickers_0, scores_0, ranks_0, prices_0, cols_0 = rw_t0
        n = len(tickers_0)

        # Build ticker → index maps for t-1, t-2
        if rw_t1 is not None:
            tickers_1, scores_1, ranks_1 = rw_t1[0], rw_t1[1], rw_t1[2]
            tk_to_idx_1 = {}
            for j in range(len(tickers_1)):
                tk_to_idx_1[tickers_1[j]] = j
        else:
            tk_to_idx_1 = None

        if rw_t2 is not None:
            tickers_2, scores_2, ranks_2 = rw_t2[0], rw_t2[1], rw_t2[2]
            tk_to_idx_2 = {}
            for j in range(len(tickers_2)):
                tk_to_idx_2[tickers_2[j]] = j
        else:
            tk_to_idx_2 = None

        # Top-n sets
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

        has_t1 = tk_to_idx_1 is not None
        has_t2 = tk_to_idx_2 is not None
        has_both = has_t1 and has_t2

        # Flat wrank array: default = sentinel (triggers exit for unknown tickers)
        wrank_arr = np.full(n_cols, _SENTINEL_WRANK, dtype=np.float64)

        # Candidates for verified tickers
        candidates_raw = []  # list of (score_100, col, entry_price, w_rank)

        for j in range(n):
            tk = tickers_0[j]
            col = int(cols_0[j])
            if col < 0:
                continue

            # Weighted rank
            r0 = int(ranks_0[j])
            if has_t1:
                idx1 = tk_to_idx_1.get(tk)
                r1 = int(ranks_1[idx1]) if idx1 is not None else 999
            else:
                r1 = 999

            if has_t2:
                idx2 = tk_to_idx_2.get(tk)
                r2 = int(ranks_2[idx2]) if idx2 is not None else 999
            else:
                r2 = 999

            if has_both:
                w_rank = r0 * 0.5 + r1 * 0.3 + r2 * 0.2
            elif has_t1:
                w_rank = r0 * 0.6 + r1 * 0.4
            else:
                w_rank = float(r0)

            # Store in flat array
            wrank_arr[col] = w_rank

            # Check if verified
            in_t0 = tk in top_t0
            if not in_t0:
                continue
            in_t1 = tk in top_t1
            if not in_t1:
                continue
            in_t2 = tk in top_t2
            if not in_t2:
                continue

            # Verified: compute score_100
            s0 = float(scores_0[j])
            if has_t1:
                idx1 = tk_to_idx_1.get(tk)
                s1 = float(scores_1[idx1]) if idx1 is not None else 0.0
            else:
                s1 = 0.0
            if has_t2:
                idx2 = tk_to_idx_2.get(tk)
                s2 = float(scores_2[idx2]) if idx2 is not None else 0.0
            else:
                s2 = 0.0

            if has_both:
                ws = s0 * 0.5 + s1 * 0.3 + s2 * 0.2
            elif has_t1:
                ws = s0 * 0.6 + s1 * 0.4
            else:
                ws = s0

            sc_100 = (ws + 0.7) / 2.4 * 100.0
            if sc_100 < 0.0:
                sc_100 = 0.0
            elif sc_100 > 100.0:
                sc_100 = 100.0

            ep = float(prices_0[j])
            if ep > 0:
                candidates_raw.append((sc_100, col, ep, w_rank))

        # Pre-sort by score_100 descending
        candidates_raw.sort(key=lambda x: -x[0])

        # Unpack into parallel lists for fastest iteration
        cand_cols = [c[1] for c in candidates_raw]
        cand_prices = [c[2] for c in candidates_raw]
        cand_wranks = [c[3] for c in candidates_raw]

        return (wrank_arr, cand_cols, cand_prices, cand_wranks)

    def _precompute_all_correlations(self, lookback=60, min_corr=0.3):
        """전체 날짜 × 유니버스 종목 간 60일 상관관계 1회 사전 계산.
        corr >= min_corr인 쌍만 저장 (메모리 절약).
        Returns: list[dict] — corr_all[date_idx] = {(col_a, col_b): corr}
        """
        n_dates = len(self.dates)
        corr_all = [None] * n_dates
        price_arr = self._price_arr

        for i in range(n_dates):
            row = self._date_row_indices[i]
            if row < lookback:
                corr_all[i] = {}
                continue

            # 이 날짜의 유니버스 종목 col indices
            pre = self._preextracted.get(self.dates[i])
            if pre is None:
                corr_all[i] = {}
                continue
            col_indices = pre[8]  # numpy array of col indices
            valid_cols = [int(c) for c in col_indices if c >= 0]
            if len(valid_cols) < 2:
                corr_all[i] = {}
                continue

            # 60일 수익률 (벡터화)
            price_slice = price_arr[row - lookback:row + 1, :]
            with np.errstate(divide='ignore', invalid='ignore'):
                returns = np.diff(price_slice, axis=0) / price_slice[:-1, :]

            # 유효 종목만 추출
            cols_arr = np.array(valid_cols)
            ret_sub = returns[:, cols_arr]  # (lookback, n_valid)

            # NaN/inf 없고 std > 0인 종목만
            valid_mask = np.all(np.isfinite(ret_sub), axis=0) & (ret_sub.std(axis=0) > 0)
            valid_idx = np.where(valid_mask)[0]

            if len(valid_idx) < 2:
                corr_all[i] = {}
                continue

            # 벡터화 상관관계 (1회 np.corrcoef 호출)
            ret_valid = ret_sub[:, valid_idx]
            corr_matrix = np.corrcoef(ret_valid.T)

            # corr >= min_corr인 쌍만 저장
            result = {}
            for a in range(len(valid_idx)):
                for b in range(a + 1, len(valid_idx)):
                    cv = corr_matrix[a, b]
                    if cv >= min_corr:
                        ca = cols_arr[valid_idx[a]]
                        cb = cols_arr[valid_idx[b]]
                        key = (min(int(ca), int(cb)), max(int(ca), int(cb)))
                        result[key] = float(cv)

            corr_all[i] = result

        return corr_all

    def _ensure_cache(self, v_w, q_w, g_w, m_w, g_rev, top_n=20):
        """Build optimized cache with flat wrank arrays and pre-sorted candidates."""
        key = (v_w, q_w, g_w, m_w, g_rev, top_n)
        if self._cached_key == key:
            return
        self._cached_key = key

        dates = self.dates
        n_dates = len(dates)
        n_cols = self._n_cols

        # Step 1: Reweight all dates (numpy-vectorized per date)
        reweighted = [None] * n_dates
        for i in range(n_dates):
            reweighted[i] = self._vectorized_reweight(dates[i], v_w, q_w, g_w, m_w, g_rev)

        # Step 2: Build flat pipelines
        flat = [None] * n_dates
        for i in range(2, n_dates):
            rw0 = reweighted[i]
            rw1 = reweighted[i - 1]
            rw2 = reweighted[i - 2]
            if rw0 is not None:
                flat[i] = self._build_day_pipeline(rw0, rw1, rw2, top_n, n_cols)

        self._cached_flat = flat

    def run_fast(self, v_w, q_w, g_w, m_w, g_rev,
                 entry_param, exit_param, max_slots, top_n=20, stop_loss=-0.10,
                 corr_threshold=None):
        """Run simulation. Builds cache if needed, then runs hot loop.
        corr_threshold: None=필터 없음, 0.65=상관관계 >= 0.65인 종목 스킵
        """
        self._ensure_cache(v_w, q_w, g_w, m_w, g_rev, top_n)
        return _run_inner(
            self._cached_flat, self._price_arr, self._bench_arr,
            self._has_bench, self._date_row_indices, len(self.dates),
            entry_param, exit_param, max_slots, stop_loss,
            self._corr_all if corr_threshold is not None else None,
            corr_threshold)


def _run_inner(flat_pipelines, price_arr, bench_arr, has_bench,
               date_rows, n_dates, entry_param, exit_param, max_slots,
               stop_loss=-0.10, corr_maps=None, corr_threshold=None):
    """Pure Python hot loop — zero numpy function calls, zero pandas.

    All data access is:
      - price_arr[row, col]: numpy 2D array element lookup (no function call)
      - wrank_arr[col]: numpy 1D array element lookup (no function call)
      - cand_cols[i]: plain Python list indexing
    No dict.get() in the critical path (replaced by flat array).
    Candidates are pre-sorted during cache build.
    """
    portfolio = {}  # {col_index: entry_price}
    # Pre-allocate return arrays as plain Python lists
    daily_rets = [0.0] * n_dates
    bench_rets = [0.0] * n_dates
    holdings_count = [0] * n_dates

    use_stop_loss = stop_loss is not None

    for i in range(2, n_dates):
        pipe = flat_pipelines[i]
        if pipe is None:
            holdings_count[i] = len(portfolio)
            continue

        wrank_arr, cand_cols, cand_prices, cand_wranks = pipe
        cur_row = date_rows[i]

        # === EXIT ===
        if portfolio:
            to_remove = []
            for col, ep in portfolio.items():
                should_exit = False
                # 1. Stop loss
                if use_stop_loss and cur_row >= 0:
                    cur_p = price_arr[cur_row, col]
                    if cur_p == cur_p and ep > 0:  # NaN check: x != x for NaN
                        if (cur_p / ep - 1.0) <= stop_loss:
                            should_exit = True
                # 2. Strategy exit: wrank_arr[col] > exit_param
                #    Sentinel value (_SENTINEL_WRANK=9999) handles missing tickers
                if not should_exit:
                    if wrank_arr[col] > exit_param:
                        should_exit = True
                if should_exit:
                    to_remove.append(col)
            for col in to_remove:
                del portfolio[col]

        # === ENTRY ===
        # cand_cols/cand_prices/cand_wranks are pre-sorted by score_100 desc
        slots_avail = max_slots - len(portfolio)
        if slots_avail > 0:
            use_corr = corr_maps is not None and corr_threshold is not None
            day_corr = corr_maps[i] if use_corr else None
            selected_cols = []  # 이번 날짜에 새로 매수할 종목들

            n_cand = len(cand_cols)
            for k in range(n_cand):
                if slots_avail <= 0:
                    break
                if cand_wranks[k] <= entry_param:
                    c = cand_cols[k]
                    if c not in portfolio:
                        if day_corr:
                            is_correlated = False
                            # Layer 2: 기존 보유 종목과 체크
                            for hc in portfolio:
                                key = (min(c, hc), max(c, hc))
                                if day_corr.get(key, 0.0) >= corr_threshold:
                                    is_correlated = True
                                    break
                            # Layer 1: 같은 날 새로 매수한 종목과 체크
                            if not is_correlated:
                                for sc in selected_cols:
                                    key = (min(c, sc), max(c, sc))
                                    if day_corr.get(key, 0.0) >= corr_threshold:
                                        is_correlated = True
                                        break
                            if is_correlated:
                                continue
                        portfolio[c] = cand_prices[k]
                        selected_cols.append(c)
                        slots_avail -= 1

        n_hold = len(portfolio)
        holdings_count[i] = n_hold

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
                daily_rets[i] = total_ret / count if count > 0 else 0.0

                if has_bench:
                    b_c = bench_arr[next_row]
                    b_p = bench_arr[cur_row]
                    if b_c == b_c and b_p == b_p and b_p > 0:
                        bench_rets[i] = b_c / b_p - 1.0

    return _calc_metrics(daily_rets, bench_rets, holdings_count)


class TurboRunner:
    """Fastest path: run many entry/exit/slots combos on pre-built cache.

    Usage:
        tsim = TurboSimulator(all_rankings, dates, prices, bench)
        tsim._ensure_cache(v_w, q_w, g_w, m_w, g_rev)
        runner = TurboRunner(tsim)
        for entry_p, exit_p, slots in combos:
            result = runner.run(entry_p, exit_p, slots)
    """

    def __init__(self, tsim):
        self._flat = tsim._cached_flat
        self._price_arr = tsim._price_arr
        self._bench_arr = tsim._bench_arr
        self._has_bench = tsim._has_bench
        self._date_rows = tsim._date_row_indices
        self._n_dates = len(tsim.dates)
        self._corr_all = getattr(tsim, '_corr_all', None)

    def run(self, entry_param, exit_param, max_slots, stop_loss=-0.10,
            corr_threshold=None):
        return _run_inner(
            self._flat, self._price_arr, self._bench_arr,
            self._has_bench, self._date_rows, self._n_dates,
            entry_param, exit_param, max_slots, stop_loss,
            self._corr_all if corr_threshold is not None else None,
            corr_threshold)
