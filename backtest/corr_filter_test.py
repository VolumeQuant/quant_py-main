"""상관관계 필터 비교 테스트"""
import sys
import json
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
from backtest.production_simulator import ProductionSimulator

CACHE_DIR = PROJECT_ROOT / 'data_cache'

class CorrFilterSimulator(ProductionSimulator):
    def __init__(self, all_rankings, dates, prices, corr_threshold=0.65):
        super().__init__(all_rankings, dates, prices)
        self.corr_threshold = corr_threshold

    def run_with_corr_filter(self, v_w, q_w, g_w, m_w, g_rev,
                              max_per_group=1, fill_from_lower=True,
                              entry_param=5, exit_param=10, max_slots=5,
                              top_n=20, stop_loss=-0.10):
        reweighted = {}
        for date in self.dates:
            rankings = self.all_rankings.get(date, [])
            if rankings:
                reweighted[date] = self._reweight(rankings, v_w, q_w, g_w, m_w, g_rev)
            else:
                reweighted[date] = []

        portfolio = {}
        daily_rets = []
        bench_rets = []
        holdings_count = []

        for i, date in enumerate(self.dates):
            if i < 2:
                daily_rets.append(0)
                bench_rets.append(0)
                holdings_count.append(0)
                continue

            d0, d1, d2 = self.dates[i], self.dates[i-1], self.dates[i-2]
            s0 = reweighted.get(d0, [])
            s1 = reweighted.get(d1, [])
            s2 = reweighted.get(d2, [])

            if not s0:
                daily_rets.append(0)
                bench_rets.append(0)
                holdings_count.append(len(portfolio))
                continue

            pipeline = self._compute_status(s0, s1, s2, top_n)
            status_map = {s['ticker']: s for s in pipeline}
            cur_ts = pd.Timestamp(date)

            # 매도
            for tk in list(portfolio.keys()):
                ep = portfolio[tk]
                should_exit = False
                if stop_loss and tk in self.prices.columns and cur_ts in self.prices.index:
                    cp = self.prices.loc[cur_ts, tk]
                    if pd.notna(cp) and ep > 0 and (cp / ep - 1) <= stop_loss:
                        should_exit = True
                if not should_exit:
                    s = status_map.get(tk)
                    if s is None or s['weighted_rank'] > exit_param:
                        should_exit = True
                if should_exit:
                    del portfolio[tk]

            # 매수 후보
            candidates = [s for s in pipeline
                         if s['ticker'] not in portfolio and s['price']
                         and s['status'] == 'verified' and s['weighted_rank'] <= entry_param]
            candidates.sort(key=lambda x: -x['score_100'])

            extended = []
            if fill_from_lower:
                extended = [s for s in pipeline
                           if s['ticker'] not in portfolio and s['price']
                           and s['status'] == 'verified' and s['weighted_rank'] <= exit_param]
                extended.sort(key=lambda x: -x['score_100'])

            # 상관관계 필터
            cand_tickers = [c['ticker'] for c in candidates]
            if len(cand_tickers) >= 2 and cur_ts in self.prices.index:
                idx = self.prices.index.get_loc(cur_ts)
                start_idx = max(0, idx - 60)
                window = self.prices.iloc[start_idx:idx + 1]
                valid = [t for t in cand_tickers if t in window.columns]

                if len(valid) >= 2:
                    rets = window[valid].pct_change().dropna()
                    if len(rets) >= 30:
                        corr_matrix = rets.corr()
                        groups = []
                        visited = set()
                        for t in valid:
                            if t in visited:
                                continue
                            group = [t]
                            visited.add(t)
                            queue = [t]
                            while queue:
                                curr = queue.pop(0)
                                for other in valid:
                                    if other in visited:
                                        continue
                                    if corr_matrix.loc[curr, other] >= self.corr_threshold:
                                        group.append(other)
                                        visited.add(other)
                                        queue.append(other)
                            groups.append(group)

                        filtered = []
                        for grp in groups:
                            grp_cands = [c for c in candidates if c['ticker'] in grp]
                            grp_cands.sort(key=lambda x: -x['score_100'])
                            filtered.extend(grp_cands[:max_per_group])

                        if fill_from_lower and len(filtered) < max_slots:
                            used = set(c['ticker'] for c in filtered)
                            for s in extended:
                                if s['ticker'] not in used and len(filtered) < max_slots:
                                    filtered.append(s)
                                    used.add(s['ticker'])

                        candidates = filtered

            for c in candidates:
                if max_slots > 0 and len(portfolio) >= max_slots:
                    break
                portfolio[c['ticker']] = c['price']

            holdings_count.append(len(portfolio))

            if i + 1 < len(self.dates) and portfolio:
                next_ts = pd.Timestamp(self.dates[i + 1])
                if next_ts in self.prices.index and cur_ts in self.prices.index:
                    rets_list = []
                    for tk in portfolio:
                        if tk in self.prices.columns:
                            cp = self.prices.loc[next_ts, tk]
                            pp = self.prices.loc[cur_ts, tk]
                            if pd.notna(cp) and pd.notna(pp) and pp > 0:
                                rets_list.append(cp / pp - 1)
                    daily_rets.append(np.mean(rets_list) if rets_list else 0)
                    bench_rets.append(0)
                else:
                    daily_rets.append(0)
                    bench_rets.append(0)
            else:
                daily_rets.append(0)
                bench_rets.append(0)

        return self._calc_metrics(daily_rets, bench_rets, holdings_count)


def main():
    all_rankings = {}
    for yr in ['2024', '2025']:
        for f in sorted(Path(f'state/bt_{yr}').glob('ranking_*.json')):
            date = f.stem.replace('ranking_', '')
            r = json.load(open(f, encoding='utf-8'))
            all_rankings[date] = r.get('rankings', [])

    dates = sorted(all_rankings.keys())
    ohlcv_files = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'))
    ohlcv_files.sort(key=lambda f: f.stem.split('_')[2])
    prices = pd.read_parquet(ohlcv_files[0])

    V, Q, G, M, GR = 0.25, 0.10, 0.50, 0.15, 0.3

    print('=== 상관관계 필터 비교 (2024~2026, V25Q10G50M15 g0.3) ===\n')
    header = f'{"전략":<25} {"CAGR":>7} {"Total":>8} {"MDD":>6} {"Sharpe":>7} {"Sortino":>8} {"Calmar":>7} {"AvgH":>5}'
    print(header)
    print('-' * 80)

    # 1. 필터 없음
    sim = CorrFilterSimulator(all_rankings, dates, prices, 0.65)
    r1 = sim.run(V, Q, G, M, GR, strategy='rank', entry_param=5, exit_param=10, max_slots=5, top_n=20, stop_loss=-0.10)
    print(f'{"필터없음(현재)":<25} {r1["cagr"]:>6.1f}% {r1["total"]:>7.1f}% {r1["mdd"]:>5.1f}% {r1["sharpe"]:>7.3f} {r1["sortino"]:>8.3f} {r1["calmar"]:>7.3f} {r1["avg_holdings"]:>5.1f}')

    # 2. 택1 + 하위 채움 (0.65)
    r2 = sim.run_with_corr_filter(V, Q, G, M, GR, max_per_group=1, fill_from_lower=True)
    print(f'{"택1+하위채움(0.65)":<25} {r2["cagr"]:>6.1f}% {r2["total"]:>7.1f}% {r2["mdd"]:>5.1f}% {r2["sharpe"]:>7.3f} {r2["sortino"]:>8.3f} {r2["calmar"]:>7.3f} {r2["avg_holdings"]:>5.1f}')

    # 3. 택1 + 채움 없음
    r3 = sim.run_with_corr_filter(V, Q, G, M, GR, max_per_group=1, fill_from_lower=False)
    print(f'{"택1+채움없음(0.65)":<25} {r3["cagr"]:>6.1f}% {r3["total"]:>7.1f}% {r3["mdd"]:>5.1f}% {r3["sharpe"]:>7.3f} {r3["sortino"]:>8.3f} {r3["calmar"]:>7.3f} {r3["avg_holdings"]:>5.1f}')

    # 4. 택2 + 하위 채움
    r4 = sim.run_with_corr_filter(V, Q, G, M, GR, max_per_group=2, fill_from_lower=True)
    print(f'{"택2+하위채움(0.65)":<25} {r4["cagr"]:>6.1f}% {r4["total"]:>7.1f}% {r4["mdd"]:>5.1f}% {r4["sharpe"]:>7.3f} {r4["sortino"]:>8.3f} {r4["calmar"]:>7.3f} {r4["avg_holdings"]:>5.1f}')

    # 5. 택1 (0.70)
    sim7 = CorrFilterSimulator(all_rankings, dates, prices, 0.70)
    r5 = sim7.run_with_corr_filter(V, Q, G, M, GR, max_per_group=1, fill_from_lower=True)
    print(f'{"택1+하위채움(0.70)":<25} {r5["cagr"]:>6.1f}% {r5["total"]:>7.1f}% {r5["mdd"]:>5.1f}% {r5["sharpe"]:>7.3f} {r5["sortino"]:>8.3f} {r5["calmar"]:>7.3f} {r5["avg_holdings"]:>5.1f}')

    # 6. 택1 (0.80)
    sim8 = CorrFilterSimulator(all_rankings, dates, prices, 0.80)
    r6 = sim8.run_with_corr_filter(V, Q, G, M, GR, max_per_group=1, fill_from_lower=True)
    print(f'{"택1+하위채움(0.80)":<25} {r6["cagr"]:>6.1f}% {r6["total"]:>7.1f}% {r6["mdd"]:>5.1f}% {r6["sharpe"]:>7.3f} {r6["sortino"]:>8.3f} {r6["calmar"]:>7.3f} {r6["avg_holdings"]:>5.1f}')


if __name__ == '__main__':
    main()
