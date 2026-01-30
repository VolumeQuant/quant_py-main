"""
백테스트 결과 시각화
- 누적 수익률 차트
- IS/OOS 비교
- Drawdown 차트
- 성과 지표 테이블
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path
import json

# 한글 폰트 설정
plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

OUTPUT_DIR = Path(__file__).parent / 'backtest_results'
FIGURE_DIR = Path(__file__).parent / 'figures'
FIGURE_DIR.mkdir(exist_ok=True)

IS_END_DATE = '2023-12-31'


def load_backtest_results():
    """
    백테스트 결과 로드
    """
    results = {}

    # 벤치마크
    benchmark_file = OUTPUT_DIR / 'backtest_benchmark_returns.csv'
    if benchmark_file.exists():
        results['benchmark'] = pd.read_csv(benchmark_file, index_col=0, parse_dates=True).squeeze()

    # 전략 A
    strategy_a_file = OUTPUT_DIR / 'backtest_strategy_A_returns.csv'
    if strategy_a_file.exists():
        results['strategy_a'] = pd.read_csv(strategy_a_file, index_col=0, parse_dates=True).squeeze()

    # 전략 B
    strategy_b_file = OUTPUT_DIR / 'backtest_strategy_B_returns.csv'
    if strategy_b_file.exists():
        results['strategy_b'] = pd.read_csv(strategy_b_file, index_col=0, parse_dates=True).squeeze()

    # 성과 지표
    for strategy in ['A', 'B']:
        metrics_file = OUTPUT_DIR / f'backtest_strategy_{strategy}_metrics.json'
        if metrics_file.exists():
            with open(metrics_file, 'r') as f:
                results[f'metrics_{strategy}'] = json.load(f)

    return results


def plot_cumulative_returns(results, save=True):
    """
    누적 수익률 차트
    """
    fig, ax = plt.subplots(figsize=(14, 7))

    # 각 전략의 누적 수익률 계산
    if 'benchmark' in results:
        cumulative = (1 + results['benchmark']).cumprod()
        ax.plot(cumulative.index, cumulative.values, label='코스피 (벤치마크)',
               color='gray', linewidth=1.5, alpha=0.7)

    if 'strategy_a' in results:
        cumulative = (1 + results['strategy_a']).cumprod()
        ax.plot(cumulative.index, cumulative.values, label='전략 A (마법공식)',
               color='blue', linewidth=2)

    if 'strategy_b' in results:
        cumulative = (1 + results['strategy_b']).cumprod()
        ax.plot(cumulative.index, cumulative.values, label='전략 B (멀티팩터)',
               color='red', linewidth=2)

    # IS/OOS 구분선
    ax.axvline(pd.Timestamp(IS_END_DATE), color='green', linestyle='--',
              linewidth=1.5, label='IS/OOS 구분선')

    # IS/OOS 영역 표시
    ax.axvspan(ax.get_xlim()[0], mdates.date2num(pd.Timestamp(IS_END_DATE)),
              alpha=0.1, color='blue', label='In-Sample')
    ax.axvspan(mdates.date2num(pd.Timestamp(IS_END_DATE)), ax.get_xlim()[1],
              alpha=0.1, color='red', label='Out-of-Sample')

    ax.set_title('누적 수익률 비교 (2015-2025)', fontsize=14, fontweight='bold')
    ax.set_xlabel('날짜', fontsize=12)
    ax.set_ylabel('누적 수익률', fontsize=12)
    ax.legend(loc='upper left', fontsize=10)
    ax.grid(True, alpha=0.3)

    # x축 날짜 포맷
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax.xaxis.set_major_locator(mdates.YearLocator())

    plt.tight_layout()

    if save:
        plt.savefig(FIGURE_DIR / 'backtest_cumulative_returns.png', dpi=150)
        print(f"저장: {FIGURE_DIR / 'backtest_cumulative_returns.png'}")

    plt.show()


def plot_drawdown(results, save=True):
    """
    Drawdown 차트
    """
    fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)

    strategies = [
        ('benchmark', '코스피 (벤치마크)', 'gray'),
        ('strategy_a', '전략 A (마법공식)', 'blue'),
        ('strategy_b', '전략 B (멀티팩터)', 'red')
    ]

    for ax, (key, name, color) in zip(axes, strategies):
        if key not in results:
            continue

        returns = results[key]
        cumulative = (1 + returns).cumprod()
        peak = cumulative.cummax()
        drawdown = (cumulative - peak) / peak * 100

        ax.fill_between(drawdown.index, drawdown.values, 0, color=color, alpha=0.3)
        ax.plot(drawdown.index, drawdown.values, color=color, linewidth=1)

        # IS/OOS 구분선
        ax.axvline(pd.Timestamp(IS_END_DATE), color='green', linestyle='--', linewidth=1)

        ax.set_title(f'{name} Drawdown', fontsize=12)
        ax.set_ylabel('Drawdown (%)', fontsize=10)
        ax.grid(True, alpha=0.3)

        # MDD 표시
        mdd = drawdown.min()
        mdd_date = drawdown.idxmin()
        ax.annotate(f'MDD: {mdd:.1f}%', xy=(mdd_date, mdd),
                   xytext=(10, -20), textcoords='offset points',
                   fontsize=9, color='black',
                   arrowprops=dict(arrowstyle='->', color='black'))

    axes[-1].set_xlabel('날짜', fontsize=12)
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    axes[-1].xaxis.set_major_locator(mdates.YearLocator())

    plt.tight_layout()

    if save:
        plt.savefig(FIGURE_DIR / 'backtest_drawdown.png', dpi=150)
        print(f"저장: {FIGURE_DIR / 'backtest_drawdown.png'}")

    plt.show()


def plot_performance_table(results, save=True):
    """
    성과 지표 테이블
    """
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.axis('off')

    # 테이블 데이터 구성
    metrics_names = ['CAGR (%)', 'MDD (%)', '변동성 (%)', 'Sharpe', 'Sortino', 'Win Rate (%)']

    # 벤치마크 성과 계산
    if 'benchmark' in results:
        benchmark_returns = results['benchmark']
        benchmark_cumulative = (1 + benchmark_returns).cumprod()
        years = len(benchmark_returns) / 252
        benchmark_cagr = (benchmark_cumulative.iloc[-1]) ** (1/years) - 1 if years > 0 else 0
        benchmark_vol = benchmark_returns.std() * np.sqrt(252)
        peak = benchmark_cumulative.cummax()
        benchmark_mdd = ((benchmark_cumulative - peak) / peak).min()
        benchmark_sharpe = (benchmark_cagr - 0.03) / benchmark_vol if benchmark_vol > 0 else 0

        benchmark_data = [
            f"{benchmark_cagr*100:.1f}",
            f"{benchmark_mdd*100:.1f}",
            f"{benchmark_vol*100:.1f}",
            f"{benchmark_sharpe:.2f}",
            "-",
            "-"
        ]
    else:
        benchmark_data = ["-"] * 6

    # 전략 A/B 성과
    strategy_a_data = ["-"] * 6
    strategy_b_data = ["-"] * 6

    if 'metrics_A' in results:
        m = results['metrics_A'].get('full_metrics', {})
        strategy_a_data = [
            f"{m.get('cagr', 0):.1f}",
            f"{m.get('mdd', 0):.1f}",
            f"{m.get('annual_volatility', 0):.1f}",
            f"{m.get('sharpe', 0):.2f}",
            f"{m.get('sortino', 0):.2f}",
            f"{m.get('win_rate', 0):.1f}"
        ]

    if 'metrics_B' in results:
        m = results['metrics_B'].get('full_metrics', {})
        strategy_b_data = [
            f"{m.get('cagr', 0):.1f}",
            f"{m.get('mdd', 0):.1f}",
            f"{m.get('annual_volatility', 0):.1f}",
            f"{m.get('sharpe', 0):.2f}",
            f"{m.get('sortino', 0):.2f}",
            f"{m.get('win_rate', 0):.1f}"
        ]

    # 테이블 생성
    table_data = list(zip(metrics_names, benchmark_data, strategy_a_data, strategy_b_data))
    columns = ['지표', '코스피', '전략 A\n(마법공식)', '전략 B\n(멀티팩터)']

    table = ax.table(
        cellText=table_data,
        colLabels=columns,
        loc='center',
        cellLoc='center',
        colColours=['#f0f0f0'] * 4
    )

    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1.2, 1.8)

    # 헤더 스타일
    for i in range(4):
        table[(0, i)].set_text_props(fontweight='bold')
        table[(0, i)].set_facecolor('#4472C4')
        table[(0, i)].set_text_props(color='white')

    ax.set_title('백테스트 성과 비교 (2015-2025)', fontsize=14, fontweight='bold', pad=20)

    plt.tight_layout()

    if save:
        plt.savefig(FIGURE_DIR / 'backtest_performance_table.png', dpi=150, bbox_inches='tight')
        print(f"저장: {FIGURE_DIR / 'backtest_performance_table.png'}")

    plt.show()


def plot_is_oos_comparison(results, save=True):
    """
    IS vs OOS 성과 비교
    """
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    strategies = ['전략 A (마법공식)', '전략 B (멀티팩터)']
    metrics_keys = ['metrics_A', 'metrics_B']
    colors = ['blue', 'red']

    for ax, title, metric_key, color in zip(axes, strategies, metrics_keys, colors):
        if metric_key not in results:
            continue

        is_metrics = results[metric_key].get('is_metrics', {})
        oos_metrics = results[metric_key].get('oos_metrics', {})

        x = np.arange(3)
        width = 0.35

        is_values = [
            is_metrics.get('cagr', 0),
            abs(is_metrics.get('mdd', 0)),
            is_metrics.get('sharpe', 0) * 10  # 스케일 조정
        ]
        oos_values = [
            oos_metrics.get('cagr', 0),
            abs(oos_metrics.get('mdd', 0)),
            oos_metrics.get('sharpe', 0) * 10
        ]

        bars1 = ax.bar(x - width/2, is_values, width, label='In-Sample (2015-2023)',
                      color=color, alpha=0.7)
        bars2 = ax.bar(x + width/2, oos_values, width, label='Out-of-Sample (2024-2025)',
                      color=color, alpha=0.4, hatch='//')

        ax.set_ylabel('값', fontsize=11)
        ax.set_title(title, fontsize=12, fontweight='bold')
        ax.set_xticks(x)
        ax.set_xticklabels(['CAGR (%)', '|MDD| (%)', 'Sharpe×10'])
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3, axis='y')

        # 값 표시
        for bars in [bars1, bars2]:
            for bar in bars:
                height = bar.get_height()
                ax.annotate(f'{height:.1f}',
                           xy=(bar.get_x() + bar.get_width() / 2, height),
                           xytext=(0, 3), textcoords="offset points",
                           ha='center', va='bottom', fontsize=9)

    plt.suptitle('In-Sample vs Out-of-Sample 성과 비교', fontsize=14, fontweight='bold')
    plt.tight_layout()

    if save:
        plt.savefig(FIGURE_DIR / 'backtest_is_oos_comparison.png', dpi=150)
        print(f"저장: {FIGURE_DIR / 'backtest_is_oos_comparison.png'}")

    plt.show()


def plot_annual_returns(results, save=True):
    """
    연도별 수익률 비교
    """
    fig, ax = plt.subplots(figsize=(14, 7))

    years = range(2015, 2026)
    width = 0.25

    strategies = [
        ('benchmark', '코스피', 'gray'),
        ('strategy_a', '전략 A', 'blue'),
        ('strategy_b', '전략 B', 'red')
    ]

    for i, (key, name, color) in enumerate(strategies):
        if key not in results:
            continue

        returns = results[key]
        annual_returns = []

        for year in years:
            year_returns = returns[returns.index.year == year]
            if not year_returns.empty:
                cumulative = (1 + year_returns).cumprod().iloc[-1] - 1
                annual_returns.append(cumulative * 100)
            else:
                annual_returns.append(0)

        x = np.arange(len(years))
        ax.bar(x + i*width, annual_returns, width, label=name, color=color, alpha=0.7)

    ax.set_xlabel('연도', fontsize=12)
    ax.set_ylabel('수익률 (%)', fontsize=12)
    ax.set_title('연도별 수익률 비교', fontsize=14, fontweight='bold')
    ax.set_xticks(np.arange(len(years)) + width)
    ax.set_xticklabels(years)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3, axis='y')
    ax.axhline(0, color='black', linewidth=0.5)

    # IS/OOS 구분
    ax.axvline(8.5, color='green', linestyle='--', linewidth=2, label='IS/OOS')

    plt.tight_layout()

    if save:
        plt.savefig(FIGURE_DIR / 'backtest_annual_returns.png', dpi=150)
        print(f"저장: {FIGURE_DIR / 'backtest_annual_returns.png'}")

    plt.show()


def main():
    """
    메인 실행
    """
    print("=" * 80)
    print("백테스트 결과 시각화")
    print("=" * 80)

    # 결과 로드
    results = load_backtest_results()

    if not results:
        print("백테스트 결과가 없습니다. full_backtest.py를 먼저 실행하세요.")
        return

    print(f"로드된 데이터: {list(results.keys())}")

    # 차트 생성
    print("\n[1] 누적 수익률 차트")
    plot_cumulative_returns(results)

    print("\n[2] Drawdown 차트")
    plot_drawdown(results)

    print("\n[3] 성과 지표 테이블")
    plot_performance_table(results)

    print("\n[4] IS vs OOS 비교")
    plot_is_oos_comparison(results)

    print("\n[5] 연도별 수익률")
    plot_annual_returns(results)

    print("\n" + "=" * 80)
    print(f"모든 차트 저장 완료: {FIGURE_DIR}")
    print("=" * 80)


if __name__ == '__main__':
    main()
