"""프로덕션 동일 로직 시뮬레이터

프로덕션(send_telegram_auto.py + ranking_manager.py)과 동일한 매매 로직:
  1. 매일 전종목 스코어링 (ranking JSON의 서브팩터 재가중)
  2. 3일 교집합 (Slow In): top_n 기준 3일 연속 포함 → ✅
  3. score_100 = (ws + 0.7) / 2.4 × 100 (3일 가중)
  4. 진입: ✅ + score_100 ≥ entry_threshold (또는 rank ≤ entry_rank)
  5. 이탈: score_100 < exit_threshold (또는 rank > exit_rank)
  6. 슬롯 제한

Usage:
    from production_simulator import ProductionSimulator
    sim = ProductionSimulator(all_rankings, prices, bench)
    result = sim.run(v_w=0.25, q_w=0.10, g_w=0.40, m_w=0.25, ...)
"""
import numpy as np
import pandas as pd


class ProductionSimulator:
    def __init__(self, all_rankings, dates, prices, bench=None):
        """
        all_rankings: {date_str: [{'ticker','score','value_s','quality_s','growth_s',
                                    'momentum_s','rev_z','oca_z','price'}, ...]}
        dates: sorted list of date strings
        prices: DataFrame (index=Timestamp, columns=tickers, values=close)
        bench: DataFrame with KOSPI index
        """
        self.all_rankings = all_rankings
        self.dates = dates
        self.prices = prices
        self.bench = bench if bench is not None else pd.DataFrame()

    def _reweight(self, rankings, v_w, q_w, g_w, m_w, g_rev):
        """서브팩터 재가중 → 새 score + rank

        G비율 0.5(기본)이면 growth_s 그대로 사용 (프로덕션 동일).
        G비율 변경 시 rev_z+oca_z로 재계산 후 재표준화(std=1).
        """
        use_original_g = abs(g_rev - 0.5) < 0.01

        if use_original_g:
            # growth_s 그대로 사용
            scored = []
            for s in rankings:
                v = s.get('value_s') or 0
                q = s.get('quality_s') or 0
                g = s.get('growth_s') or 0
                m = s.get('momentum_s') or 0
                new_score = v_w * v + q_w * q + g_w * g + m_w * m
                scored.append({
                    'ticker': s['ticker'],
                    'price': s.get('price'),
                    'new_score': new_score,
                })
        else:
            # G비율 변경: rev_z+oca_z 재계산 후 재표준화
            g_raws = []
            items = []
            for s in rankings:
                rev = s.get('rev_z') or 0
                oca = s.get('oca_z') or 0
                g_raw = g_rev * rev + (1 - g_rev) * oca
                g_raws.append(g_raw)
                items.append(s)

            # 재표준화 (std=1)
            g_arr = np.array(g_raws)
            g_mean = g_arr.mean()
            g_std = g_arr.std()
            if g_std > 0:
                g_standardized = (g_arr - g_mean) / g_std
            else:
                g_standardized = g_arr * 0

            scored = []
            for idx, s in enumerate(items):
                v = s.get('value_s') or 0
                q = s.get('quality_s') or 0
                m = s.get('momentum_s') or 0
                new_score = v_w * v + q_w * q + g_w * g_standardized[idx] + m_w * m
                scored.append({
                    'ticker': s['ticker'],
                    'price': s.get('price'),
                    'new_score': new_score,
                })

        scored.sort(key=lambda x: -x['new_score'])
        for i, s in enumerate(scored):
            s['new_rank'] = i + 1
        return scored

    def _compute_status(self, scored_t0, scored_t1, scored_t2, top_n):
        """3일 교집합 → 상태(✅/⏳/🆕) + weighted_rank + weighted_score"""
        def top_set(scored, n):
            return set(s['ticker'] for s in scored[:n])

        def score_map(scored):
            return {s['ticker']: s['new_score'] for s in scored}

        def rank_map(scored):
            return {s['ticker']: s['new_rank'] for s in scored}

        top_t0 = top_set(scored_t0, top_n)
        top_t1 = top_set(scored_t1, top_n) if scored_t1 else set()
        top_t2 = top_set(scored_t2, top_n) if scored_t2 else set()

        sm0 = score_map(scored_t0)
        sm1 = score_map(scored_t1) if scored_t1 else {}
        sm2 = score_map(scored_t2) if scored_t2 else {}

        rm0 = rank_map(scored_t0)
        rm1 = rank_map(scored_t1) if scored_t1 else {}
        rm2 = rank_map(scored_t2) if scored_t2 else {}

        price_map = {s['ticker']: s['price'] for s in scored_t0 if s.get('price')}

        # 전체 종목에 대해 weighted_rank 계산 (퇴출용 — 프로덕션 동일)
        all_tickers = set(rm0.keys())
        result = []
        for tk in all_tickers:
            in_t0 = tk in top_t0
            in_t1 = tk in top_t1
            in_t2 = tk in top_t2

            # 진입 상태는 top_n 교집합 기준
            if in_t0 and in_t1 and in_t2:
                status = 'verified'  # ✅
            elif in_t0 and in_t1:
                status = 'pending'   # ⏳
            elif in_t0:
                status = 'new'       # 🆕
            else:
                status = 'outside'   # top_n 밖 (퇴출 판정용)

            # weighted score (3일 가중)
            s0 = sm0.get(tk, 0)
            s1 = sm1.get(tk, 0)
            s2 = sm2.get(tk, 0)

            if sm1 and sm2:
                ws = s0 * 0.5 + s1 * 0.3 + s2 * 0.2
            elif sm1:
                ws = s0 * 0.6 + s1 * 0.4
            else:
                ws = s0

            score_100 = max(0.0, min(100.0, (ws + 0.7) / 2.4 * 100))

            # weighted rank
            r0 = rm0.get(tk, 999)
            r1 = rm1.get(tk, 999)
            r2 = rm2.get(tk, 999)
            if rm1 and rm2:
                w_rank = r0 * 0.5 + r1 * 0.3 + r2 * 0.2
            elif rm1:
                w_rank = r0 * 0.6 + r1 * 0.4
            else:
                w_rank = float(r0)

            result.append({
                'ticker': tk,
                'status': status,
                'score_100': score_100,
                'weighted_rank': w_rank,
                'price': price_map.get(tk),
                'raw_score': s0,
            })

        result.sort(key=lambda x: x['weighted_rank'])
        return result

    def run(self, v_w, q_w, g_w, m_w, g_rev=0.5,
            strategy='score', entry_param=72, exit_param=68,
            max_slots=5, top_n=20, stop_loss=-0.10):
        """
        strategy: 'score', 'rank', 'hybrid_se'(score entry + rank exit), 'hybrid_re'
        entry_param: score threshold (score) or max rank (rank)
        exit_param: score threshold (score) or max rank (rank)
        stop_loss: 손절 비율 (기본 -10%, None이면 비활성)
        """
        portfolio = {}  # ticker → entry_price
        daily_rets = []
        bench_rets = []
        holdings_count = []

        # 사전 재가중 (전 날짜)
        reweighted = {}
        for date in self.dates:
            rankings = self.all_rankings.get(date, [])
            if rankings:
                reweighted[date] = self._reweight(rankings, v_w, q_w, g_w, m_w, g_rev)
            else:
                reweighted[date] = []

        for i, date in enumerate(self.dates):
            if i < 2:
                daily_rets.append(0)
                bench_rets.append(0)
                holdings_count.append(len(portfolio))
                continue

            d0, d1, d2 = self.dates[i], self.dates[i-1], self.dates[i-2]
            scored_t0 = reweighted.get(d0, [])
            scored_t1 = reweighted.get(d1, [])
            scored_t2 = reweighted.get(d2, [])

            if not scored_t0:
                daily_rets.append(0)
                bench_rets.append(0)
                holdings_count.append(len(portfolio))
                continue

            # 3일 교집합 + 상태
            pipeline = self._compute_status(scored_t0, scored_t1, scored_t2, top_n)

            # score_100 / rank 맵
            status_map = {s['ticker']: s for s in pipeline}

            # === 매도 ===
            cur_ts = pd.Timestamp(date)
            for tk in list(portfolio.keys()):
                entry_price = portfolio[tk]
                should_exit = False

                # 1. 손절 (-10%)
                if stop_loss is not None and tk in self.prices.columns and cur_ts in self.prices.index:
                    cur_price = self.prices.loc[cur_ts, tk]
                    if pd.notna(cur_price) and entry_price > 0:
                        if (cur_price / entry_price - 1) <= stop_loss:
                            should_exit = True

                # 2. 전략 기반 이탈
                if not should_exit:
                    s = status_map.get(tk)
                    if s is None:
                        should_exit = True
                    elif strategy == 'score':
                        should_exit = s['score_100'] < exit_param
                    elif strategy == 'rank':
                        should_exit = s['weighted_rank'] > exit_param
                    elif strategy == 'hybrid_se':
                        should_exit = s['weighted_rank'] > exit_param
                    elif strategy == 'hybrid_re':
                        should_exit = s['score_100'] < exit_param

                if should_exit:
                    del portfolio[tk]

            # === 매수 ===
            candidates = []
            for s in pipeline:
                if s['ticker'] in portfolio:
                    continue
                if s['price'] is None:
                    continue
                if s['status'] != 'verified':  # ✅만
                    continue

                should_enter = False
                if strategy == 'score':
                    should_enter = s['score_100'] >= entry_param
                elif strategy == 'rank':
                    should_enter = s['weighted_rank'] <= entry_param
                elif strategy == 'hybrid_se':
                    should_enter = s['score_100'] >= entry_param
                elif strategy == 'hybrid_re':
                    should_enter = s['weighted_rank'] <= entry_param

                if should_enter:
                    candidates.append(s)

            # score_100 내림차순 (프로덕션과 동일)
            candidates.sort(key=lambda x: -x['score_100'])

            for c in candidates:
                if max_slots > 0 and len(portfolio) >= max_slots:
                    break
                portfolio[c['ticker']] = c['price']

            holdings_count.append(len(portfolio))

            # === 수익률 ===
            if i + 1 < len(self.dates) and portfolio:
                next_ts = pd.Timestamp(self.dates[i + 1])
                cur_ts = pd.Timestamp(date)
                if next_ts in self.prices.index and cur_ts in self.prices.index:
                    rets = []
                    for tk in portfolio:
                        if tk in self.prices.columns:
                            c_price = self.prices.loc[next_ts, tk]
                            p_price = self.prices.loc[cur_ts, tk]
                            if pd.notna(c_price) and pd.notna(p_price) and p_price > 0:
                                rets.append(c_price / p_price - 1)
                    daily_rets.append(np.mean(rets) if rets else 0)

                    # 벤치마크
                    if not self.bench.empty and next_ts in self.bench.index and cur_ts in self.bench.index:
                        b_c = self.bench.loc[next_ts].iloc[0]
                        b_p = self.bench.loc[cur_ts].iloc[0]
                        bench_rets.append((b_c / b_p - 1) if (pd.notna(b_c) and pd.notna(b_p) and b_p > 0) else 0)
                    else:
                        bench_rets.append(0)
                else:
                    daily_rets.append(0)
                    bench_rets.append(0)
            else:
                daily_rets.append(0)
                bench_rets.append(0)

        return self._calc_metrics(daily_rets, bench_rets, holdings_count)

    def _calc_metrics(self, daily_rets, bench_rets, holdings_count):
        arr = np.array(daily_rets)
        n = len(arr)
        if n == 0 or arr.std() == 0:
            return {'cagr': 0, 'sharpe': 0, 'sortino': 0, 'calmar': 0,
                    'mdd': 0, 'total': 0, 'b_cagr': 0, 'alpha': 0, 'avg_holdings': 0}

        equity = np.cumprod(1 + arr)
        total = (equity[-1] - 1) * 100
        cagr = (equity[-1] ** (252 / max(n, 1)) - 1) * 100
        sharpe = arr.mean() / arr.std() * np.sqrt(252)

        down = arr[arr < 0]
        down_std = down.std() if len(down) > 0 else arr.std()
        sortino = (arr.mean() / down_std * np.sqrt(252)) if down_std > 0 else sharpe

        peak = np.maximum.accumulate(np.concatenate([[1], equity]))
        dd = (np.concatenate([[1], equity]) - peak) / peak
        mdd = abs(dd.min()) * 100

        calmar = cagr / mdd if mdd > 0 else 0

        b_arr = np.array(bench_rets)
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
