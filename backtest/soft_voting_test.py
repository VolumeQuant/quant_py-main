"""소프트 보팅 앙상블 vs 개별 전략 비교"""
import sys
import json
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

from backtest.production_simulator import ProductionSimulator

CACHE_DIR = PROJECT_ROOT / 'data_cache'
STATE_DIR = PROJECT_ROOT / 'state'


class SoftVotingSimulator(ProductionSimulator):
    def __init__(self, all_rankings, dates, prices, weight_sets):
        super().__init__(all_rankings, dates, prices)
        self.weight_sets = weight_sets

    def run_ensemble(self, strategy='rank', entry_param=5, exit_param=10,
                     max_slots=5, top_n=20, stop_loss=-0.10):
        # 각 전략별 reweight
        all_rw = []
        for (v, q, g, m, gr) in self.weight_sets:
            rw = {}
            for date in self.dates:
                rankings = self.all_rankings.get(date, [])
                if rankings:
                    rw[date] = self._reweight(rankings, v, q, g, m, gr)
                else:
                    rw[date] = []
            all_rw.append(rw)

        # 날짜별 score 평균
        merged = {}
        for date in self.dates:
            tk_scores = {}
            tk_prices = {}
            for rw in all_rw:
                for s in rw.get(date, []):
                    tk = s['ticker']
                    if tk not in tk_scores:
                        tk_scores[tk] = []
                        tk_prices[tk] = s.get('price')
                    tk_scores[tk].append(s['new_score'])

            avg_scored = []
            for tk, scores in tk_scores.items():
                avg_scored.append({
                    'ticker': tk,
                    'price': tk_prices[tk],
                    'new_score': np.mean(scores),
                })
            avg_scored.sort(key=lambda x: -x['new_score'])
            for i, s in enumerate(avg_scored):
                s['new_rank'] = i + 1
            merged[date] = avg_scored

        # 매매 시뮬레이션
        portfolio = {}
        daily_rets = []
        bench_rets = []
        holdings_count = []

        for i, date in enumerate(self.dates):
            if i < 2:
                daily_rets.append(0)
                bench_rets.append(0)
                holdings_count.append(len(portfolio))
                continue

            d0, d1, d2 = self.dates[i], self.dates[i-1], self.dates[i-2]
            s0 = merged.get(d0, [])
            s1 = merged.get(d1, [])
            s2 = merged.get(d2, [])

            if not s0:
                daily_rets.append(0)
                bench_rets.append(0)
                holdings_count.append(len(portfolio))
                continue

            pipeline = self._compute_status(s0, s1, s2, top_n)
            status_map = {s['ticker']: s for s in pipeline}

            cur_ts = pd.Timestamp(date)
            for tk in list(portfolio.keys()):
                entry_price = portfolio[tk]
                should_exit = False
                if stop_loss is not None and tk in self.prices.columns and cur_ts in self.prices.index:
                    cur_price = self.prices.loc[cur_ts, tk]
                    if pd.notna(cur_price) and entry_price > 0:
                        if (cur_price / entry_price - 1) <= stop_loss:
                            should_exit = True
                if not should_exit:
                    s = status_map.get(tk)
                    if s is None:
                        should_exit = True
                    elif strategy == 'rank':
                        should_exit = s['weighted_rank'] > exit_param
                if should_exit:
                    del portfolio[tk]

            candidates = []
            for s in pipeline:
                if s['ticker'] in portfolio or s['price'] is None or s['status'] != 'verified':
                    continue
                if strategy == 'rank' and s['weighted_rank'] <= entry_param:
                    candidates.append(s)
            candidates.sort(key=lambda x: -x['score_100'])
            for c in candidates:
                if max_slots > 0 and len(portfolio) >= max_slots:
                    break
                portfolio[c['ticker']] = c['price']

            holdings_count.append(len(portfolio))
            if i + 1 < len(self.dates) and portfolio:
                next_ts = pd.Timestamp(self.dates[i + 1])
                if next_ts in self.prices.index and cur_ts in self.prices.index:
                    rets = []
                    for tk in portfolio:
                        if tk in self.prices.columns:
                            c_p = self.prices.loc[next_ts, tk]
                            p_p = self.prices.loc[cur_ts, tk]
                            if pd.notna(c_p) and pd.notna(p_p) and p_p > 0:
                                rets.append(c_p / p_p - 1)
                    daily_rets.append(np.mean(rets) if rets else 0)
                    bench_rets.append(0)
                else:
                    daily_rets.append(0)
                    bench_rets.append(0)
            else:
                daily_rets.append(0)
                bench_rets.append(0)

        return self._calc_metrics(daily_rets, bench_rets, holdings_count)


def main():
    print('=== 데이터 로드 ===')
    all_rankings = {}
    for yr in ['2021', '2022', '2023', '2024', '2025']:
        for f in sorted(Path(f'state/bt_{yr}').glob('ranking_*.json')):
            date = f.stem.replace('ranking_', '')
            r = json.load(open(f, encoding='utf-8'))
            all_rankings[date] = r.get('rankings', [])

    dates = sorted(all_rankings.keys())
    ohlcv_files = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'))
    ohlcv_files.sort(key=lambda f: f.stem.split('_')[2])
    prices = pd.read_parquet(ohlcv_files[0])
    print(f'{len(dates)}일 ({dates[0]}~{dates[-1]})')

    # 전략 정의
    strategies = {
        'v72현재':  (0.15, 0.25, 0.40, 0.20, 0.7),
        '전체최적': (0.15, 0.15, 0.35, 0.35, 1.0),
        '최근최적': (0.30, 0.20, 0.45, 0.05, 0.7),
        '하락최적': (0.15, 0.20, 0.45, 0.20, 1.0),
        '안정형':   (0.10, 0.20, 0.40, 0.30, 0.8),
    }

    ensemble_sets = [
        (0.15, 0.15, 0.35, 0.35, 1.0),
        (0.30, 0.20, 0.45, 0.05, 0.7),
        (0.15, 0.20, 0.45, 0.20, 1.0),
    ]

    # 국면 분류
    avg_price = prices.mean(axis=1).dropna()

    periods = {
        '전체 2021~26': [d for d in dates if '20210104' <= d <= '20260320'],
        '최근 2024~26': [d for d in dates if '20240102' <= d <= '20260320'],
    }

    for d in dates:
        ts = pd.Timestamp(d)
        if ts not in avg_price.index:
            continue
        idx = avg_price.index.get_loc(ts)
        if idx < 126:
            continue
        ret = avg_price.iloc[idx] / avg_price.iloc[idx - 126] - 1
        if ret > 0.10:
            periods.setdefault('상승장', []).append(d)
        elif ret < -0.10:
            periods.setdefault('하락장', []).append(d)
        else:
            periods.setdefault('횡보장', []).append(d)

    # 실행
    for period_name, period_dates in periods.items():
        sub_rankings = {d: all_rankings[d] for d in period_dates if d in all_rankings}
        sub_dates = sorted(sub_rankings.keys())
        if len(sub_dates) < 60:
            continue

        print(f'\n{"="*80}')
        print(f'  {period_name} ({len(sub_dates)}일)')
        print(f'{"="*80}')
        print(f'{"전략":<12} {"Sharpe":>7} {"CAGR":>8} {"MDD":>7} {"Calmar":>7} {"Total":>9} {"AvgH":>5}')
        print('-' * 62)

        for strat_name, (v, q, g, m, gr) in strategies.items():
            sim = ProductionSimulator(sub_rankings, sub_dates, prices)
            r = sim.run(v_w=v, q_w=q, g_w=g, m_w=m, g_rev=gr,
                        strategy='rank', entry_param=5, exit_param=10,
                        max_slots=5, top_n=20, stop_loss=-0.10)
            print(f'{strat_name:<12} {r["sharpe"]:>7.3f} {r["cagr"]:>7.1f}% {r["mdd"]:>6.1f}% {r["calmar"]:>7.3f} {r["total"]:>8.1f}% {r["avg_holdings"]:>5.1f}')

        esim = SoftVotingSimulator(sub_rankings, sub_dates, prices, ensemble_sets)
        er = esim.run_ensemble(strategy='rank', entry_param=5, exit_param=10,
                               max_slots=5, top_n=20, stop_loss=-0.10)
        print(f'{"소프트보팅":<12} {er["sharpe"]:>7.3f} {er["cagr"]:>7.1f}% {er["mdd"]:>6.1f}% {er["calmar"]:>7.3f} {er["total"]:>8.1f}% {er["avg_holdings"]:>5.1f}')


if __name__ == '__main__':
    main()
