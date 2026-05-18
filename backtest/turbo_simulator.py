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
            # 6개 G 서브팩터 z-score
            g_subs = {k: np.empty(n, dtype=np.float64) for k in
                      ['rev_z', 'oca_z', 'rev_accel_z', 'gp_growth_z', 'op_margin_z', 'cfo_growth_z']}
            r_prices = np.empty(n, dtype=np.float64)
            col_indices = np.empty(n, dtype=np.int32)

            # 4종 모멘텀 배열
            mom_6m_s = np.empty(n, dtype=np.float64)
            mom_6m1m_s = np.empty(n, dtype=np.float64)
            mom_12m_s = np.empty(n, dtype=np.float64)
            mom_12m1m_s = np.empty(n, dtype=np.float64)

            for j, s in enumerate(rankings):
                tk = s['ticker']
                tickers[j] = tk
                value_s[j] = s.get('value_s') or 0.0
                quality_s[j] = s.get('quality_s') or 0.0
                growth_s[j] = s.get('growth_s') or 0.0
                momentum_s[j] = s.get('momentum_s') or 0.0
                for gk in g_subs:
                    g_subs[gk][j] = s.get(gk) or 0.0
                p = s.get('price')
                r_prices[j] = float(p) if p is not None else 0.0
                col_indices[j] = tk_to_col.get(tk, -1)
                mom_6m_s[j] = s.get('mom_6m_s') or momentum_s[j]
                mom_6m1m_s[j] = s.get('mom_6m1m_s') or 0.0
                mom_12m_s[j] = s.get('mom_12m_s') or 0.0
                mom_12m1m_s[j] = s.get('mom_12m1m_s') or 0.0

            self._preextracted[date] = (tickers, value_s, quality_s, growth_s,
                                        momentum_s, g_subs, r_prices, col_indices,
                                        mom_6m_s, mom_6m1m_s, mom_12m_s, mom_12m1m_s)

        # ---- 60일 상관관계 1회 사전 계산 (가중치 무관) ----
        self._corr_all = self._precompute_all_correlations()

        # Cache
        self._cached_key = None
        self._cached_flat = None
        self._cached_base_key = None  # (v_w, q_w, g_w, g_rev) for partial reuse
        self._cached_partials = None  # V+Q+G partial sums per date

    def _compute_partial(self, date, v_w, q_w, g_w, g_rev, g_sub1='rev_z', g_sub2='oca_z',
                         g_sub3=None, g_w1=None, g_w2=None, g_w3=None,
                         quality_gate=0.0, g_sub4=None, g_w4=None):
        """V+Q+G 부분합 계산. 2팩터: g_rev*sub1 + (1-g_rev)*sub2.
        3팩터: w1*s1+w2*s2+w3*s3. 4팩터: w1*s1+w2*s2+w3*s3+w4*s4.
        quality_gate>0: G z-score에 quality 감쇠 적용.
        """
        pre = self._preextracted.get(date)
        if pre is None:
            return None
        (tickers, value_s, quality_s, growth_s, momentum_s,
         g_subs, r_prices, col_indices,
         mom_6m_s, mom_6m1m_s, mom_12m_s, mom_12m1m_s) = pre
        n = len(tickers)
        sub1_arr = g_subs.get(g_sub1, g_subs.get('rev_z'))
        sub2_arr = g_subs.get(g_sub2, g_subs.get('oca_z'))
        if g_sub3 is not None and g_w1 is not None:
            sub3_arr = g_subs.get(g_sub3, np.zeros(n))
            if g_sub4 is not None and g_w4 is not None:
                sub4_arr = g_subs.get(g_sub4, np.zeros(n))
                g_raw = g_w1 * sub1_arr + g_w2 * sub2_arr + g_w3 * sub3_arr + g_w4 * sub4_arr
            else:
                g_raw = g_w1 * sub1_arr + g_w2 * sub2_arr + g_w3 * sub3_arr
        else:
            g_raw = g_rev * sub1_arr + (1 - g_rev) * sub2_arr
        g_std = g_raw.std()
        g_standardized = (g_raw - g_raw.mean()) / g_std if g_std > 0 else np.zeros(n)
        if quality_gate > 0:
            gate = np.clip(0.5 + quality_s * quality_gate, 0.3, 1.0)
            g_standardized = g_standardized * gate
        partial = v_w * value_s + q_w * quality_s + g_w * g_standardized
        return (tickers, partial, r_prices, col_indices, mom_6m_s, mom_6m1m_s, mom_12m_s, mom_12m1m_s)

    def _vectorized_reweight(self, date, v_w, q_w, g_w, m_w, g_rev, mom_type='6m'):
        """Returns (tickers, new_scores, new_ranks, prices, col_indices) or None."""
        pre = self._preextracted.get(date)
        if pre is None:
            return None

        (tickers, value_s, quality_s, growth_s, momentum_s,
         g_subs, r_prices, col_indices,
         mom_6m_s, mom_6m1m_s, mom_12m_s, mom_12m1m_s) = pre
        rev_z = g_subs.get('rev_z', np.zeros(len(tickers)))
        oca_z = g_subs.get('oca_z', np.zeros(len(tickers)))

        # 모멘텀 타입 선택
        if mom_type == '6m':
            use_momentum = mom_6m_s
        elif mom_type == '6m-1m':
            use_momentum = mom_6m1m_s
        elif mom_type == '12m':
            use_momentum = mom_12m_s
        elif mom_type == '12m-1m':
            use_momentum = mom_12m1m_s
        else:
            use_momentum = momentum_s
        n = len(tickers)

        use_original_g = abs(g_rev - 0.5) < 0.01
        if use_original_g:
            new_scores = v_w * value_s + q_w * quality_s + g_w * growth_s + m_w * use_momentum
        else:
            g_raw = g_rev * rev_z + (1 - g_rev) * oca_z
            g_std = g_raw.std()
            if g_std > 0:
                g_standardized = (g_raw - g_raw.mean()) / g_std
            else:
                g_standardized = np.zeros(n)
            new_scores = v_w * value_s + q_w * quality_s + g_w * g_standardized + m_w * use_momentum

        sort_idx = np.argsort(-new_scores)
        new_ranks = np.empty(n, dtype=np.int32)
        new_ranks[sort_idx] = np.arange(1, n + 1)

        return (tickers, new_scores, new_ranks, r_prices, col_indices)

    def _build_day_pipeline(self, rw_t0, rw_t1, rw_t2, top_n, n_cols, use_score_wr=False):
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

        # 1st pass: 모든 종목의 weighted score/rank 계산
        all_ws = []  # (j, col, tk, ws, w_rank_legacy)
        for j in range(n):
            tk = tickers_0[j]
            col = int(cols_0[j])
            if col < 0:
                continue

            # score 가중평균
            s0 = float(scores_0[j])
            s1_val = float(scores_1[tk_to_idx_1[tk]]) if has_t1 and tk in tk_to_idx_1 else 0.0
            s2_val = float(scores_2[tk_to_idx_2[tk]]) if has_t2 and tk in tk_to_idx_2 else 0.0
            if has_both:
                ws = s0 * 0.4 + s1_val * 0.35 + s2_val * 0.25  # v80.13: 50:30:20 → 40:35:25
            elif has_t1:
                ws = s0 * 0.6 + s1_val * 0.4
            else:
                ws = s0

            # rank 가중평균 (legacy) — Top 20 한정 + PENALTY 50 (production과 일치)
            # CLAUDE.md 의도: 빈 날(Top 20 안 들면) = PENALTY 50. cr 그대로 X.
            _PEN = 50
            r0 = int(ranks_0[j])
            if has_t1:
                idx1 = tk_to_idx_1.get(tk)
                if idx1 is not None:
                    r1_raw = int(ranks_1[idx1])
                    r1 = r1_raw if r1_raw <= top_n else _PEN
                else:
                    r1 = _PEN
            else:
                r1 = _PEN
            if has_t2:
                idx2 = tk_to_idx_2.get(tk)
                if idx2 is not None:
                    r2_raw = int(ranks_2[idx2])
                    r2 = r2_raw if r2_raw <= top_n else _PEN
                else:
                    r2 = _PEN
            else:
                r2 = _PEN
            if has_both:
                wr_legacy = r0 * 0.4 + r1 * 0.35 + r2 * 0.25  # v80.13: 50:30:20 → 40:35:25
            elif has_t1:
                wr_legacy = r0 * 0.6 + r1 * 0.4
            else:
                wr_legacy = float(r0)

            all_ws.append((j, col, tk, ws, wr_legacy))

        # score 기반 wr: ws 내림차순 → rank 1,2,3...
        if use_score_wr and all_ws:
            sorted_by_ws = sorted(all_ws, key=lambda x: -x[3])
            score_rank_map = {}
            for rank_i, (j, col, tk, ws, _) in enumerate(sorted_by_ws):
                score_rank_map[(j, col, tk)] = rank_i + 1
        else:
            score_rank_map = None

        # 2nd pass: wrank_arr + candidates 생성
        candidates_raw = []
        for j, col, tk, ws, wr_legacy in all_ws:
            w_rank = score_rank_map[(j, col, tk)] if score_rank_map else wr_legacy
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

    def _ensure_cache(self, v_w, q_w, g_w, m_w, g_rev, top_n=20, mom_type='6m',
                      g_sub1='rev_z', g_sub2='oca_z',
                      g_sub3=None, g_w1=None, g_w2=None, g_w3=None,
                      use_score_wr=False, quality_gate=0.0,
                      g_sub4=None, g_w4=None):
        """Build optimized cache — V+Q+G 부분합 재사용, G 서브팩터 2/3/4팩터 선택 가능."""
        key = (v_w, q_w, g_w, m_w, g_rev, top_n, mom_type, g_sub1, g_sub2, g_sub3, g_w1, g_w2, g_w3, use_score_wr, quality_gate, g_sub4, g_w4)
        if self._cached_key == key:
            return
        self._cached_key = key

        dates = self.dates
        n_dates = len(dates)
        n_cols = self._n_cols

        # Step 0: V+Q+G 부분합 캐싱 (G 서브팩터 + 비율이 같으면 재사용)
        base_key = (v_w, q_w, g_w, g_rev, g_sub1, g_sub2, g_sub3, g_w1, g_w2, g_w3, quality_gate, g_sub4, g_w4)
        if self._cached_base_key != base_key:
            self._cached_partials = [None] * n_dates
            for i in range(n_dates):
                self._cached_partials[i] = self._compute_partial(
                    dates[i], v_w, q_w, g_w, g_rev, g_sub1, g_sub2, g_sub3, g_w1, g_w2, g_w3, quality_gate, g_sub4, g_w4)
            self._cached_base_key = base_key

        # Step 1: 부분합 + 모멘텀으로 최종 스코어 (빠름)
        mom_map = {'6m': 4, '6m-1m': 5, '12m': 6, '12m-1m': 7}
        mi = mom_map.get(mom_type, 4)

        reweighted = [None] * n_dates
        for i in range(n_dates):
            p = self._cached_partials[i]
            if p is None:
                continue
            tickers, partial, r_prices, col_indices = p[0], p[1], p[2], p[3]
            use_momentum = p[mi]
            new_scores = partial + m_w * use_momentum
            sort_idx = np.argsort(-new_scores)
            new_ranks = np.empty(len(tickers), dtype=np.int32)
            new_ranks[sort_idx] = np.arange(1, len(tickers) + 1)
            reweighted[i] = (tickers, new_scores, new_ranks, r_prices, col_indices)

        # Step 2: Build flat pipelines
        flat = [None] * n_dates
        for i in range(2, n_dates):
            rw0 = reweighted[i]
            rw1 = reweighted[i - 1]
            rw2 = reweighted[i - 2]
            if rw0 is not None:
                flat[i] = self._build_day_pipeline(rw0, rw1, rw2, top_n, n_cols, use_score_wr)

        self._cached_flat = flat

    def run_fast(self, v_w, q_w, g_w, m_w, g_rev,
                 entry_param, exit_param, max_slots, top_n=20, stop_loss=-0.10,
                 corr_threshold=None, trailing_stop=None, mom_type='6m',
                 take_profit=None, g_sub1='rev_z', g_sub2='oca_z',
                 g_sub3=None, g_w1=None, g_w2=None, g_w3=None,
                 use_score_wr=False, quality_gate=0.0):
        """Run simulation. Builds cache if needed, then runs hot loop.
        2팩터: g_sub1/g_sub2 + g_rev (sub1 비율)
        3팩터: g_sub1/g_sub2/g_sub3 + g_w1/g_w2/g_w3 (각 비율, 합=1.0)
        """
        self._ensure_cache(v_w, q_w, g_w, m_w, g_rev, top_n, mom_type, g_sub1, g_sub2,
                          g_sub3, g_w1, g_w2, g_w3, use_score_wr, quality_gate)
        return _run_inner(
            self._cached_flat, self._price_arr, self._bench_arr,
            self._has_bench, self._date_row_indices, len(self.dates),
            entry_param, exit_param, max_slots, stop_loss,
            self._corr_all if corr_threshold is not None else None,
            corr_threshold, trailing_stop, take_profit)


    def run_regime(self, defense_params, offense_params, regime_dict,
                   stop_loss=-0.10, corr_threshold=None, trailing_stop=None,
                   take_profit=None,
                   stop_loss_o=None, stop_loss_d=None,
                   trailing_stop_o=None, trailing_stop_d=None,
                   g_sub1_d='rev_z', g_sub2_d='oca_z',
                   g_sub1_o='rev_z', g_sub2_o='oca_z',
                   g_sub3_d=None, g_w1_d=None, g_w2_d=None, g_w3_d=None,
                   g_sub3_o=None, g_w1_o=None, g_w2_o=None, g_w3_o=None,
                   use_score_wr=False, quality_gate_d=0.0, quality_gate_o=0.0,
                   g_sub4_d=None, g_w4_d=None, g_sub4_o=None, g_w4_o=None,
                   breakout_hold=None):
        """국면전환 시뮬레이션 — 전환 시 포트폴리오 완전 청산 후 새 전략 재진입.

        Args:
            defense_params: dict with v,q,g,m,g_rev,entry,exit,slots,mom_type
            offense_params: dict with v,q,g,m,g_rev,entry,exit,slots,mom_type
            regime_dict: {date_str: True(공격)/False(방��)}
        """
        dp, op = defense_params, offense_params

        # 방어/공격 캐시 각각 빌드
        self._ensure_cache(dp['v'], dp['q'], dp['g'], dp['m'],
                          dp['g_rev'], 20, dp.get('mom', '6m'), g_sub1_d, g_sub2_d,
                          g_sub3_d, g_w1_d, g_w2_d, g_w3_d, use_score_wr, quality_gate_d,
                          g_sub4_d, g_w4_d)
        defense_flat = list(self._cached_flat)

        self._ensure_cache(op['v'], op['q'], op['g'], op['m'],
                          op['g_rev'], 20, op.get('mom', '6m'), g_sub1_o, g_sub2_o,
                          g_sub3_o, g_w1_o, g_w2_o, g_w3_o, use_score_wr, quality_gate_o,
                          g_sub4_o, g_w4_o)
        offense_flat = list(self._cached_flat)

        return _run_regime_inner(
            defense_flat, offense_flat,
            dp['entry'], dp['exit'], dp['slots'],
            op['entry'], op['exit'], op['slots'],
            regime_dict, self.dates,
            self._price_arr, self._bench_arr, self._has_bench,
            self._date_row_indices, len(self.dates),
            stop_loss,
            self._corr_all if corr_threshold is not None else None,
            corr_threshold, trailing_stop,
            breakout_hold, take_profit,
            stop_loss_o, trailing_stop_o,
            stop_loss_d, trailing_stop_d)


def _run_regime_inner(defense_flat, offense_flat,
                      d_entry, d_exit, d_slots,
                      o_entry, o_exit, o_slots,
                      regime_dict, dates,
                      price_arr, bench_arr, has_bench,
                      date_rows, n_dates,
                      stop_loss=-0.10, corr_maps=None,
                      corr_threshold=None, trailing_stop=None,
                      breakout_hold=None, take_profit=None,
                      stop_loss_o=None, trailing_stop_o=None,
                      stop_loss_d=None, trailing_stop_d=None):
    """국면전환 시뮬레이션 핫루프 — 전환 시 포트폴리오 청산.
    국면별 SL/TS: stop_loss_o/d, trailing_stop_o/d 지정 시 해당값 사용.
    None이면 단일 stop_loss/trailing_stop 폴백.
    """
    portfolio = {}
    peak_prices = {}
    grace_days = {}  # breakout hold 유예 일수
    daily_rets = [0.0] * n_dates
    bench_rets = [0.0] * n_dates
    holdings_count = [0] * n_dates

    # 국면별 fallback
    sl_o = stop_loss_o if stop_loss_o is not None else stop_loss
    sl_d = stop_loss_d if stop_loss_d is not None else stop_loss
    ts_o = trailing_stop_o if trailing_stop_o is not None else trailing_stop
    ts_d = trailing_stop_d if trailing_stop_d is not None else trailing_stop

    use_take_profit = take_profit is not None
    use_hold = breakout_hold is not None
    if use_hold:
        hold_lookback = breakout_hold.get('lookback', 20)
        hold_price_chg = breakout_hold.get('price_chg_min', 0.25)
        hold_ma_period = breakout_hold.get('ma_period', 60)
        hold_max_grace = breakout_hold.get('max_grace', 2)
    prev_regime = None

    for i in range(2, n_dates):
        d = dates[i]
        cur_regime = regime_dict.get(d, False)  # False=방어, True=공격

        # === 국면 전환 감지 → 포트폴리오 청산 ===
        if prev_regime is not None and cur_regime != prev_regime:
            # 전환일: 기존 전량 매도 (수익률은 전일까지 반영됨)
            portfolio.clear()
            peak_prices.clear()

        prev_regime = cur_regime

        # 현재 국면에 맞는 파이프라인/파라미터 선택
        if cur_regime:  # 공격
            pipe = offense_flat[i]
            entry_param = o_entry
            exit_param = o_exit
            max_slots = o_slots
            cur_sl = sl_o
            cur_ts = ts_o
        else:  # 방어
            pipe = defense_flat[i]
            entry_param = d_entry
            exit_param = d_exit
            max_slots = d_slots
            cur_sl = sl_d
            cur_ts = ts_d
        use_stop_loss = cur_sl is not None
        use_trailing = cur_ts is not None

        if pipe is None:
            holdings_count[i] = len(portfolio)
            continue

        wrank_arr, cand_cols, cand_prices, cand_wranks = pipe
        cur_row = date_rows[i]

        # === UPDATE PEAK PRICES ===
        if use_trailing and portfolio and cur_row >= 0:
            for col in portfolio:
                cur_p = price_arr[cur_row, col]
                if cur_p == cur_p and cur_p > 0:
                    if col in peak_prices:
                        if cur_p > peak_prices[col]:
                            peak_prices[col] = cur_p
                    else:
                        peak_prices[col] = cur_p

        # === EXIT ===
        if portfolio:
            to_remove = []
            for col, ep in portfolio.items():
                should_exit = False
                if use_stop_loss and cur_row >= 0:
                    cur_p = price_arr[cur_row, col]
                    if cur_p == cur_p and ep > 0:
                        if (cur_p / ep - 1.0) <= cur_sl:
                            should_exit = True
                if not should_exit and use_trailing and cur_row >= 0:
                    cur_p = price_arr[cur_row, col]
                    pk = peak_prices.get(col, ep)
                    if cur_p == cur_p and pk > 0:
                        if (cur_p / pk - 1.0) <= cur_ts:
                            should_exit = True
                if not should_exit and use_take_profit and cur_row >= 0:
                    cur_p = price_arr[cur_row, col]
                    if cur_p == cur_p and ep > 0:
                        if (cur_p / ep - 1.0) >= take_profit:
                            should_exit = True
                if not should_exit:
                    if wrank_arr[col] > exit_param:
                        should_exit = True
                        # Breakout Hold: rank exit만 유예 (손절/트레일링은 유예 안 함)
                        if use_hold and should_exit and cur_row >= hold_lookback:
                            cur_p = price_arr[cur_row, col]
                            past_p = price_arr[cur_row - hold_lookback, col]
                            if (past_p > 0 and cur_p > 0 and
                                (cur_p / past_p - 1.0) >= hold_price_chg):
                                # MA 체크
                                ma_start = max(0, cur_row - hold_ma_period)
                                ma_slice = price_arr[ma_start:cur_row, col]
                                ma_val = np.nanmean(ma_slice) if len(ma_slice) > 0 else 0
                                if ma_val > 0 and cur_p > ma_val:
                                    grace = grace_days.get(col, 0)
                                    if grace < hold_max_grace:
                                        grace_days[col] = grace + 1
                                        should_exit = False
                if should_exit:
                    to_remove.append(col)
                    grace_days.pop(col, None)
                else:
                    # 유예 아닌데 rank 통과했으면 grace 초기화
                    if col in grace_days and wrank_arr[col] <= exit_param:
                        del grace_days[col]
            for col in to_remove:
                del portfolio[col]
                if col in peak_prices:
                    del peak_prices[col]

        # === ENTRY ===
        slots_avail = max_slots - len(portfolio)
        if slots_avail > 0:
            use_corr = corr_maps is not None and corr_threshold is not None
            day_corr = corr_maps[i] if use_corr else None
            selected_cols = []

            n_cand = len(cand_cols)
            for k in range(n_cand):
                if slots_avail <= 0:
                    break
                if cand_wranks[k] <= entry_param:
                    c = cand_cols[k]
                    if c not in portfolio:
                        if day_corr:
                            is_correlated = False
                            for hc in portfolio:
                                key = (min(c, hc), max(c, hc))
                                if day_corr.get(key, 0.0) >= corr_threshold:
                                    is_correlated = True
                                    break
                            if not is_correlated:
                                for sc in selected_cols:
                                    key = (min(c, sc), max(c, sc))
                                    if day_corr.get(key, 0.0) >= corr_threshold:
                                        is_correlated = True
                                        break
                            if is_correlated:
                                continue
                        portfolio[c] = cand_prices[k]
                        peak_prices[c] = cand_prices[k]
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

    metrics = _calc_metrics(daily_rets, bench_rets, holdings_count)
    metrics['_daily_rets'] = daily_rets
    return metrics


def _run_inner(flat_pipelines, price_arr, bench_arr, has_bench,
               date_rows, n_dates, entry_param, exit_param, max_slots,
               stop_loss=-0.10, corr_maps=None, corr_threshold=None,
               trailing_stop=None, take_profit=None):
    """Pure Python hot loop — zero numpy function calls, zero pandas.

    trailing_stop: None=미사용, -0.15=고점 대비 -15%이면 매도
    take_profit: None=미사용, 0.30=진입가 대비 +30%이면 매도
    """
    portfolio = {}  # {col_index: entry_price}
    peak_prices = {}  # {col_index: peak_price} — 트레일링 스톱용
    daily_rets = [0.0] * n_dates
    bench_rets = [0.0] * n_dates
    holdings_count = [0] * n_dates

    use_stop_loss = stop_loss is not None
    use_trailing = trailing_stop is not None
    use_take_profit = take_profit is not None

    for i in range(2, n_dates):
        pipe = flat_pipelines[i]
        if pipe is None:
            holdings_count[i] = len(portfolio)
            continue

        wrank_arr, cand_cols, cand_prices, cand_wranks = pipe
        cur_row = date_rows[i]

        # === UPDATE PEAK PRICES ===
        if use_trailing and portfolio and cur_row >= 0:
            for col in portfolio:
                cur_p = price_arr[cur_row, col]
                if cur_p == cur_p and cur_p > 0:  # NaN check
                    if col in peak_prices:
                        if cur_p > peak_prices[col]:
                            peak_prices[col] = cur_p
                    else:
                        peak_prices[col] = cur_p

        # === EXIT ===
        if portfolio:
            to_remove = []
            for col, ep in portfolio.items():
                should_exit = False
                # 1. Stop loss (진입가 대비)
                if use_stop_loss and cur_row >= 0:
                    cur_p = price_arr[cur_row, col]
                    if cur_p == cur_p and ep > 0:  # NaN check: x != x for NaN
                        if (cur_p / ep - 1.0) <= stop_loss:
                            should_exit = True
                # 1.5. Trailing stop (고점 대비)
                if not should_exit and use_trailing and cur_row >= 0:
                    cur_p = price_arr[cur_row, col]
                    pk = peak_prices.get(col, ep)
                    if cur_p == cur_p and pk > 0:
                        if (cur_p / pk - 1.0) <= trailing_stop:
                            should_exit = True
                # 1.7. Take profit (진입가 대비)
                if not should_exit and use_take_profit and cur_row >= 0:
                    cur_p = price_arr[cur_row, col]
                    if cur_p == cur_p and ep > 0:
                        if (cur_p / ep - 1.0) >= take_profit:
                            should_exit = True
                # 2. Strategy exit: wrank_arr[col] > exit_param
                if not should_exit:
                    if wrank_arr[col] > exit_param:
                        should_exit = True
                if should_exit:
                    to_remove.append(col)
            for col in to_remove:
                del portfolio[col]
                if col in peak_prices:
                    del peak_prices[col]

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
                        peak_prices[c] = cand_prices[k]
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

    metrics = _calc_metrics(daily_rets, bench_rets, holdings_count)
    metrics['_daily_rets'] = daily_rets
    return metrics


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
            corr_threshold=None, trailing_stop=None, take_profit=None):
        return _run_inner(
            self._flat, self._price_arr, self._bench_arr,
            self._has_bench, self._date_rows, self._n_dates,
            entry_param, exit_param, max_slots, stop_loss,
            self._corr_all if corr_threshold is not None else None,
            corr_threshold, trailing_stop, take_profit)
