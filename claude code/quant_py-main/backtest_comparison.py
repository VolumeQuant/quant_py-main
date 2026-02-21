"""
백테스트 비교: Top 5 vs Top 10, 동일비중 vs 순위가중
- 한 번의 전략 실행으로 4가지 시나리오 동시 비교
- 분기별 리밸런싱 (2015-2025)
"""

import pandas as pd
import numpy as np
import warnings
from datetime import datetime, timedelta
from pathlib import Path
import json
import sys

warnings.filterwarnings('ignore')

from fnguide_crawler import get_all_financial_statements, extract_magic_formula_data
from data_collector import DataCollector
from strategy_b_multifactor import MultiFactorStrategy

# 설정
START_DATE = '20150101'
END_DATE = '20251231'
IS_END_DATE = '20231231'
MIN_MARKET_CAP = 1000   # 억원
MIN_TRADING_VALUE = 50   # 억원
N_STOCKS = 10            # 전략에서 10개 선정 (Top 5는 여기서 잘라냄)

# 거래비용
COMMISSION = 0.00015
TAX = 0.0023
BASE_SLIPPAGE = 0.001

OUTPUT_DIR = Path(__file__).parent / 'backtest_results'
OUTPUT_DIR.mkdir(exist_ok=True)

# 4가지 시나리오
SCENARIOS = {
    'top5_equal':   {'n': 5,  'weighted': False, 'label': 'Top 5 동일비중'},
    'top5_ranked':  {'n': 5,  'weighted': True,  'label': 'Top 5 순위가중'},
    'top10_equal':  {'n': 10, 'weighted': False, 'label': 'Top 10 동일비중'},
    'top10_ranked': {'n': 10, 'weighted': True,  'label': 'Top 10 순위가중'},
}


def rank_weights(n):
    """
    순위 가중치: 1위 = n, 2위 = n-1, ... n위 = 1
    정규화하여 합이 1이 되도록
    """
    raw = np.array([n - i for i in range(n)], dtype=float)
    return raw / raw.sum()


def generate_rebalance_dates(start_year=2015, end_year=2025):
    """분기별 리밸런싱 날짜 (3, 6, 9, 12월 말)"""
    dates = []
    for year in range(start_year, end_year + 1):
        for month in [3, 6, 9, 12]:
            if month == 12:
                date = f"{year}1231"
            else:
                next_month = month + 1
                last_day = (datetime(year, next_month, 1) - timedelta(days=1)).day
                date = f"{year}{month:02d}{last_day:02d}"
            dates.append(date)
    return dates


def get_universe_for_date(collector, date):
    """특정 날짜의 유니버스"""
    try:
        market_cap_df = collector.get_market_cap(date, market='ALL')
        if market_cap_df.empty:
            return pd.DataFrame(), []

        market_cap_df['시가총액_억'] = market_cap_df['시가총액'] / 1e8
        filtered = market_cap_df[market_cap_df['시가총액_억'] >= MIN_MARKET_CAP].copy()

        filtered['거래대금_억'] = filtered['거래대금'] / 1e8
        filtered = filtered[filtered['거래대금_억'] >= MIN_TRADING_VALUE]

        from pykrx import stock
        exclude_kw = ['금융', '은행', '증권', '보험', '캐피탈', '카드', '저축',
                      '지주', '홀딩스', 'SPAC', '스팩', '리츠', 'REIT']
        valid = []
        for ticker in filtered.index:
            try:
                name = stock.get_market_ticker_name(ticker)
                if not any(kw in name for kw in exclude_kw):
                    valid.append(ticker)
            except Exception:
                continue

        return filtered.loc[filtered.index.isin(valid)], valid
    except Exception as e:
        print(f"  유니버스 실패 ({date}): {e}")
        return pd.DataFrame(), []


def run_strategy(collector, date, tickers, universe_df):
    """전략 B 실행 → 상위 10개 반환 (순위순)"""
    if not tickers:
        return pd.DataFrame()

    try:
        fs_data = get_all_financial_statements(tickers, use_cache=True)
        magic_df = extract_magic_formula_data(fs_data, base_date=date)
        if magic_df.empty:
            return pd.DataFrame()

        from pykrx import stock as pykrx_stock
        try:
            mc_kospi = pykrx_stock.get_market_cap(date, market='KOSPI')
            mc_kosdaq = pykrx_stock.get_market_cap(date, market='KOSDAQ')
            if not mc_kospi.empty:
                mc_kospi['섹터'] = 'KOSPI'
            if not mc_kosdaq.empty:
                mc_kosdaq['섹터'] = 'KOSDAQ'
            mc_all = pd.concat([mc_kospi, mc_kosdaq])
            magic_df = magic_df.merge(
                mc_all[['시가총액', '섹터']],
                left_on='종목코드', right_index=True, how='left'
            )
        except Exception:
            magic_df = magic_df.merge(
                universe_df[['시가총액']],
                left_on='종목코드', right_index=True, how='left'
            )

        magic_df['시가총액'] = magic_df['시가총액'] / 1e8

        # 모멘텀 가격 데이터
        end_dt = datetime.strptime(date, '%Y%m%d')
        start_dt = end_dt - timedelta(days=400)
        try:
            price_df = collector.get_all_ohlcv(
                magic_df['종목코드'].tolist(),
                start_dt.strftime('%Y%m%d'), date
            )
        except Exception:
            price_df = None

        strategy = MultiFactorStrategy()
        selected, _ = strategy.run(magic_df, price_df=price_df, n_stocks=N_STOCKS)
        return selected

    except Exception as e:
        print(f"  전략 실패 ({date}): {e}")
        return pd.DataFrame()


def get_stock_returns(collector, tickers, start_date, end_date):
    """각 종목의 일별 수익률 수집 → DataFrame"""
    returns_dict = {}
    for ticker in tickers:
        try:
            ohlcv = collector.get_ohlcv(ticker, start_date, end_date)
            if ohlcv.empty:
                # 상장폐지
                returns_dict[ticker] = pd.Series(
                    -1.0, index=[pd.to_datetime(start_date)]
                )
            else:
                returns_dict[ticker] = ohlcv['종가'].pct_change()
        except Exception:
            returns_dict[ticker] = pd.Series(
                -1.0, index=[pd.to_datetime(start_date)]
            )
    if not returns_dict:
        return pd.DataFrame()
    return pd.concat(returns_dict, axis=1)


def weighted_portfolio_return(returns_df, weights):
    """가중 포트폴리오 수익률"""
    # returns_df 컬럼 수와 weights 길이 맞추기
    n = min(len(weights), returns_df.shape[1])
    w = weights[:n]
    w = w / w.sum()  # 재정규화 (종목 수 부족 시)
    return (returns_df.iloc[:, :n] * w).sum(axis=1)


def apply_transaction_cost(portfolio_return, universe_df):
    """거래비용 차감"""
    if portfolio_return.empty or universe_df is None:
        return portfolio_return

    avg_tv = universe_df.get('거래대금', pd.Series()).mean()
    if pd.isna(avg_tv):
        avg_tv = 1e9

    impact = min(100_000_000 / N_STOCKS / max(avg_tv, 1) * 10, 0.009)
    buy_cost = COMMISSION + BASE_SLIPPAGE + impact
    sell_cost = COMMISSION + TAX + BASE_SLIPPAGE + impact

    ret = portfolio_return.copy()
    if len(ret) > 0:
        ret.iloc[0] -= buy_cost
    if len(ret) > 1:
        ret.iloc[-1] -= sell_cost
    return ret


def calc_metrics(returns, label=''):
    """성과 지표 계산"""
    if returns.empty or len(returns) < 20:
        return {}

    cum = (1 + returns).cumprod()
    total = cum.iloc[-1] - 1
    years = len(returns) / 252

    cagr = cum.iloc[-1] ** (1 / years) - 1 if years > 0 and cum.iloc[-1] > 0 else 0
    vol = returns.std() * np.sqrt(252)
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()
    sharpe = (cagr - 0.03) / vol if vol > 0 else 0

    down = returns[returns < 0]
    down_std = down.std() * np.sqrt(252) if len(down) > 0 else 0
    sortino = (cagr - 0.03) / down_std if down_std > 0 else 0
    calmar = abs(cagr / mdd) if mdd != 0 else 0
    win_rate = (returns > 0).sum() / len(returns) * 100

    return {
        'label': label,
        'total_return': total * 100,
        'cagr': cagr * 100,
        'volatility': vol * 100,
        'mdd': mdd * 100,
        'sharpe': sharpe,
        'sortino': sortino,
        'calmar': calmar,
        'win_rate': win_rate,
        'trading_days': len(returns),
    }


def run_comparison_backtest():
    """메인 비교 백테스트"""
    print("=" * 80)
    print("백테스트 비교: Top 5 vs Top 10, 동일비중 vs 순위가중")
    print(f"기간: {START_DATE} ~ {END_DATE}")
    print(f"리밸런싱: 분기별 (3/6/9/12월)")
    print("=" * 80)

    collector = DataCollector(start_date=START_DATE, end_date=END_DATE)
    rebal_dates = generate_rebalance_dates(2015, 2025)

    # 시나리오별 수익률 누적
    scenario_returns = {k: [] for k in SCENARIOS}

    # 벤치마크 (KOSPI200)
    from pykrx import stock as pykrx_stock
    try:
        idx = pykrx_stock.get_index_ohlcv(START_DATE, END_DATE, '1028')
        close_col = [c for c in idx.columns if '종가' in c]
        close_col = close_col[0] if close_col else idx.columns[3]
        bench_returns = idx[close_col].pct_change().dropna()
        print(f"벤치마크 (KOSPI200) 로드 완료: {len(bench_returns)}일")
    except Exception as e:
        print(f"벤치마크 로드 실패: {e}")
        bench_returns = pd.Series(dtype=float)

    total_quarters = len(rebal_dates) - 1
    for i in range(total_quarters):
        rebal = rebal_dates[i]
        next_rebal = rebal_dates[i + 1]
        print(f"\n[{i+1}/{total_quarters}] {rebal} → {next_rebal}")

        # 1. 유니버스
        universe_df, tickers = get_universe_for_date(collector, rebal)
        if not tickers:
            print("  유니버스 없음")
            continue
        print(f"  유니버스: {len(tickers)}개")

        # 2. 전략 실행 (Top 10)
        selected = run_strategy(collector, rebal, tickers, universe_df)
        if selected.empty:
            print("  선정 실패")
            continue

        top10_tickers = selected['종목코드'].tolist()[:10]
        top5_tickers = top10_tickers[:5]
        print(f"  선정: {len(top10_tickers)}개 (Top 5: {len(top5_tickers)}개)")

        # 3. 수익률 수집 (10개 종목 한번에)
        returns_df = get_stock_returns(collector, top10_tickers, rebal, next_rebal)
        if returns_df.empty:
            print("  수익률 없음")
            continue

        # 4. 시나리오별 포트폴리오 수익률 계산
        for key, cfg in SCENARIOS.items():
            n = cfg['n']
            sub_returns = returns_df.iloc[:, :n]  # Top N 종목만

            if sub_returns.empty:
                continue

            if cfg['weighted']:
                w = rank_weights(min(n, sub_returns.shape[1]))
                port_ret = weighted_portfolio_return(sub_returns, w)
            else:
                port_ret = sub_returns.mean(axis=1)

            port_ret = apply_transaction_cost(port_ret, universe_df)
            scenario_returns[key].append(port_ret)

        # 진행률 표시
        top_names = []
        for t in top5_tickers[:3]:
            try:
                name = pykrx_stock.get_market_ticker_name(t)
                top_names.append(name)
            except Exception:
                top_names.append(t)
        print(f"  Top 3: {', '.join(top_names)}")

    # === 결과 집계 ===
    print("\n" + "=" * 80)
    print("                    백테스트 결과 비교")
    print("=" * 80)

    all_metrics = {}
    all_cumulative = {}

    for key, cfg in SCENARIOS.items():
        rets = scenario_returns[key]
        if not rets:
            print(f"\n{cfg['label']}: 데이터 없음")
            continue

        full_ret = pd.concat(rets)
        full_ret = full_ret[~full_ret.index.duplicated(keep='first')].sort_index()

        # 전체 기간
        metrics = calc_metrics(full_ret, cfg['label'])
        all_metrics[key] = metrics

        # 누적 수익률
        cum = (1 + full_ret).cumprod()
        all_cumulative[key] = cum

        # IS / OOS
        is_ret = full_ret[full_ret.index <= IS_END_DATE]
        oos_ret = full_ret[full_ret.index > IS_END_DATE]
        is_m = calc_metrics(is_ret, f"{cfg['label']} [IS]")
        oos_m = calc_metrics(oos_ret, f"{cfg['label']} [OOS]")

        print(f"\n{'─' * 50}")
        print(f"📊 {cfg['label']}")
        print(f"{'─' * 50}")
        print(f"  전체  | CAGR {metrics.get('cagr',0):+.1f}%  MDD {metrics.get('mdd',0):.1f}%  Sharpe {metrics.get('sharpe',0):.2f}  Sortino {metrics.get('sortino',0):.2f}")
        print(f"  IS    | CAGR {is_m.get('cagr',0):+.1f}%  MDD {is_m.get('mdd',0):.1f}%  Sharpe {is_m.get('sharpe',0):.2f}")
        print(f"  OOS   | CAGR {oos_m.get('cagr',0):+.1f}%  MDD {oos_m.get('mdd',0):.1f}%  Sharpe {oos_m.get('sharpe',0):.2f}")

        # 저장
        full_ret.to_csv(OUTPUT_DIR / f'comparison_{key}_returns.csv')
        cum.to_csv(OUTPUT_DIR / f'comparison_{key}_cumulative.csv')

    # 벤치마크 지표
    if not bench_returns.empty:
        bench_m = calc_metrics(bench_returns, 'KOSPI200')
        all_metrics['kospi200'] = bench_m
        print(f"\n{'─' * 50}")
        print(f"📊 KOSPI200 (벤치마크)")
        print(f"{'─' * 50}")
        print(f"  전체  | CAGR {bench_m.get('cagr',0):+.1f}%  MDD {bench_m.get('mdd',0):.1f}%  Sharpe {bench_m.get('sharpe',0):.2f}")

    # === 비교 테이블 ===
    print("\n" + "=" * 80)
    print("                    비교 요약")
    print("=" * 80)

    headers = ['시나리오', 'CAGR', 'MDD', 'Sharpe', 'Sortino', 'Calmar', 'Win%']
    print(f"{'시나리오':<22} {'CAGR':>8} {'MDD':>8} {'Sharpe':>8} {'Sortino':>8} {'Calmar':>8} {'Win%':>6}")
    print("─" * 80)
    for key, m in all_metrics.items():
        label = m.get('label', key)
        print(f"{label:<22} {m.get('cagr',0):>+7.1f}% {m.get('mdd',0):>7.1f}% {m.get('sharpe',0):>8.2f} {m.get('sortino',0):>8.2f} {m.get('calmar',0):>8.2f} {m.get('win_rate',0):>5.1f}%")

    # === Top 5 vs Top 10 차이 ===
    if 'top5_equal' in all_metrics and 'top10_equal' in all_metrics:
        d_cagr = all_metrics['top5_equal']['cagr'] - all_metrics['top10_equal']['cagr']
        d_mdd = all_metrics['top5_equal']['mdd'] - all_metrics['top10_equal']['mdd']
        print(f"\nTop 5 vs Top 10 (동일비중): CAGR 차이 {d_cagr:+.1f}%p, MDD 차이 {d_mdd:+.1f}%p")

    if 'top5_ranked' in all_metrics and 'top10_ranked' in all_metrics:
        d_cagr = all_metrics['top5_ranked']['cagr'] - all_metrics['top10_ranked']['cagr']
        d_mdd = all_metrics['top5_ranked']['mdd'] - all_metrics['top10_ranked']['mdd']
        print(f"Top 5 vs Top 10 (순위가중): CAGR 차이 {d_cagr:+.1f}%p, MDD 차이 {d_mdd:+.1f}%p")

    # === 동일비중 vs 순위가중 ===
    if 'top5_equal' in all_metrics and 'top5_ranked' in all_metrics:
        d_cagr = all_metrics['top5_ranked']['cagr'] - all_metrics['top5_equal']['cagr']
        print(f"\n동일비중 vs 순위가중 (Top 5): CAGR 차이 {d_cagr:+.1f}%p")

    if 'top10_equal' in all_metrics and 'top10_ranked' in all_metrics:
        d_cagr = all_metrics['top10_ranked']['cagr'] - all_metrics['top10_equal']['cagr']
        print(f"동일비중 vs 순위가중 (Top 10): CAGR 차이 {d_cagr:+.1f}%p")

    # JSON 저장
    with open(OUTPUT_DIR / 'comparison_metrics.json', 'w', encoding='utf-8') as f:
        json.dump(all_metrics, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n결과 저장: {OUTPUT_DIR}")
    print("=" * 80)

    return all_metrics


if __name__ == '__main__':
    run_comparison_backtest()
