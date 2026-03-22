"""백테스트 종합 성과 지표 모듈 (한국 주식 퀀트)

daily_returns (list[float], %) 기반으로 모든 지표를 계산.
trade_log (list[dict]) 기반으로 거래 지표를 계산.

Usage:
    from bt_metrics import report, compare
    report(daily_returns, trade_log, label='현행 전략')
"""
import math
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')


# ── (A) 수익률 지표 ──

def total_return(daily_rets):
    """누적 수익률 (%) — 복리 누적. prod(1 + r/100) - 1"""
    cum = 1.0
    for r in daily_rets:
        cum *= (1 + r / 100)
    return (cum - 1) * 100


def cagr(daily_rets, trading_days=252):
    """CAGR (연환산 복리 수익률, %)
    (최종NAV)^(252/거래일수) - 1
    """
    n = len(daily_rets)
    if n == 0:
        return 0
    cum = 1.0
    for r in daily_rets:
        cum *= (1 + r / 100)
    years = n / trading_days
    if years <= 0 or cum <= 0:
        return 0
    return (cum ** (1 / years) - 1) * 100


# ── (B) 위험 지표 ──

def max_drawdown(daily_rets):
    """MDD (%) — 복리 NAV 기준 고점 대비 최대 하락폭. 음수 반환."""
    cum = 1.0
    peak = 1.0
    mdd = 0
    for r in daily_rets:
        cum *= (1 + r / 100)
        if cum > peak:
            peak = cum
        dd = (cum - peak) / peak * 100
        if dd < mdd:
            mdd = dd
    return mdd


def recovery_days(daily_rets):
    """MDD 복구 기간 — 고점 회복까지 걸린 거래일수"""
    cum = 1.0
    peak = 1.0
    max_recovery = 0
    dd_start = 0
    in_dd = False
    for i, r in enumerate(daily_rets):
        cum *= (1 + r / 100)
        if cum >= peak:
            if in_dd:
                max_recovery = max(max_recovery, i - dd_start)
                in_dd = False
            peak = cum
        elif not in_dd:
            dd_start = i
            in_dd = True
    if in_dd:
        max_recovery = max(max_recovery, len(daily_rets) - dd_start)
    return max_recovery


def annualized_volatility(daily_rets, trading_days=252):
    """연환산 변동성 (%) = std(daily) × √252"""
    if len(daily_rets) < 2:
        return 0
    mean = sum(daily_rets) / len(daily_rets)
    var = sum((r - mean) ** 2 for r in daily_rets) / (len(daily_rets) - 1)
    return math.sqrt(var * trading_days)


def downside_volatility(daily_rets, trading_days=252):
    """하방 변동성 (%) — 음수 수익률만 계산. 소르티노 분모."""
    neg = [min(r, 0) ** 2 for r in daily_rets]
    if not neg:
        return 0
    return math.sqrt(sum(neg) / len(neg) * trading_days)


# ── (C) 위험조정 수익 지표 ──

def sharpe_ratio(daily_rets, trading_days=252):
    """샤프 비율 = CAGR / 변동성"""
    vol = annualized_volatility(daily_rets, trading_days)
    if vol == 0:
        return 0
    return cagr(daily_rets, trading_days) / vol


def sortino_ratio(daily_rets, trading_days=252):
    """소르티노 비율 = CAGR / 하방변동성"""
    ds_vol = downside_volatility(daily_rets, trading_days)
    if ds_vol == 0:
        return 0
    return cagr(daily_rets, trading_days) / ds_vol


def calmar_ratio(daily_rets, trading_days=252):
    """칼마 비율 = CAGR / |MDD|"""
    mdd = max_drawdown(daily_rets)
    if mdd == 0:
        return 0
    return cagr(daily_rets, trading_days) / abs(mdd)


def information_ratio(daily_rets, bench_rets, trading_days=252):
    """정보비율 (IR) = 연환산 초과수익률 평균 / 추적오차

    daily_rets, bench_rets: 동일 길이의 일일 수익률 리스트 (%)
    """
    n = min(len(daily_rets), len(bench_rets))
    if n < 2:
        return 0
    excess = [daily_rets[i] - bench_rets[i] for i in range(n)]
    mean_ex = sum(excess) / n
    var_ex = sum((e - mean_ex) ** 2 for e in excess) / (n - 1)
    te = math.sqrt(var_ex * trading_days)  # 연환산 추적오차
    if te == 0:
        return 0
    ann_excess = mean_ex * trading_days
    return ann_excess / te


def bootstrap_excess_ci(daily_rets, bench_rets, n_bootstrap=10000, ci=0.90):
    """부트스트랩 CI — 누적 초과수익률의 신뢰구간

    Returns: (lower, median, upper) 누적 초과수익률 (%)
    """
    import random
    n = min(len(daily_rets), len(bench_rets))
    if n < 10:
        return (0, 0, 0)
    excess = [daily_rets[i] - bench_rets[i] for i in range(n)]

    cum_excess = []
    for _ in range(n_bootstrap):
        sample = random.choices(excess, k=n)
        cum = 1.0
        for e in sample:
            cum *= (1 + e / 100)
        cum_excess.append((cum - 1) * 100)

    cum_excess.sort()
    alpha = (1 - ci) / 2
    lo_idx = int(alpha * n_bootstrap)
    hi_idx = int((1 - alpha) * n_bootstrap) - 1
    med_idx = n_bootstrap // 2
    return (cum_excess[lo_idx], cum_excess[med_idx], cum_excess[hi_idx])


# ── (D) 거래 통계 ──

def trade_stats(trade_log, total_days=None):
    """거래 로그 기반 통계

    trade_log: list[dict] with 'return' key (%)
    total_days: 백테스트 총 거래일수 (회전율 계산용)
    """
    if not trade_log:
        return {
            'total_trades': 0, 'win_rate': 0, 'avg_return': 0,
            'avg_win': 0, 'avg_loss': 0, 'profit_loss_ratio': 0,
            'profit_factor': 0, 'expectancy': 0,
            'max_consecutive_win': 0, 'max_consecutive_loss': 0,
            'avg_hold_days': 0, 'turnover': 0,
        }

    returns = [t['return'] for t in trade_log]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]

    # 프로핏 팩터: 총이익합 / |총손실합|
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0
    pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    win_rate = len(wins) / len(returns) if returns else 0
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0
    pl_ratio = avg_win / avg_loss if avg_loss > 0 else float('inf')
    expectancy = sum(returns) / len(returns)

    # 최대 연속 승리/패배
    max_con_loss = max_con_win = cur_loss = cur_win = 0
    for r in returns:
        if r <= 0:
            cur_loss += 1
            cur_win = 0
            max_con_loss = max(max_con_loss, cur_loss)
        else:
            cur_win += 1
            cur_loss = 0
            max_con_win = max(max_con_win, cur_win)

    # 평균 보유일수 (캘린더일 기준)
    hold_days = []
    for t in trade_log:
        if 'entry_date' in t and 'exit_date' in t:
            try:
                d1 = datetime.strptime(t['entry_date'], '%Y-%m-%d')
                d2 = datetime.strptime(t['exit_date'], '%Y-%m-%d')
                hold_days.append((d2 - d1).days)
            except Exception:
                pass
    avg_hold = sum(hold_days) / len(hold_days) if hold_days else 0

    # 연환산 회전율
    to = len(trade_log) / total_days * 252 if total_days and total_days > 0 else 0

    return {
        'total_trades': len(returns),
        'win_rate': win_rate,
        'avg_return': expectancy,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'profit_loss_ratio': pl_ratio,
        'profit_factor': pf,
        'expectancy': expectancy,
        'max_consecutive_win': max_con_win,
        'max_consecutive_loss': max_con_loss,
        'avg_hold_days': avg_hold,
        'turnover': to,
    }


# ── (E) 출력 함수 ──

def report(daily_rets, trade_log=None, label='전략'):
    """종합 성과 리포트 — 단일 전략 상세 출력"""
    n = len(daily_rets)
    if n == 0:
        print(f'[{label}] 데이터 없음')
        return

    tr = total_return(daily_rets)
    ca = cagr(daily_rets)
    mdd = max_drawdown(daily_rets)
    rec = recovery_days(daily_rets)
    vol = annualized_volatility(daily_rets)
    ds_vol = downside_volatility(daily_rets)
    sh = sharpe_ratio(daily_rets)
    so = sortino_ratio(daily_rets)
    cal = calmar_ratio(daily_rets)

    print(f'\n{"="*50}')
    print(f'  {label} — 종합 성과 리포트')
    print(f'{"="*50}')
    print(f'  기간: {n}거래일')
    print()

    print(f'  ── 수익률 ──')
    print(f'  누적 수익률       {tr:+.2f}%')
    print(f'  연환산 (CAGR)     {ca:+.2f}%')
    print()

    print(f'  ── 위험 ──')
    print(f'  MDD              {mdd:.2f}%')
    print(f'  복구 기간         {rec}일')
    print(f'  연환산 변동성     {vol:.2f}%')
    print(f'  하방 변동성       {ds_vol:.2f}%')
    print()

    print(f'  ── 위험 조정 수익 ──')
    print(f'  샤프 비율         {sh:.2f}')
    print(f'  소르티노 비율     {so:.2f}')
    print(f'  칼마 비율         {cal:.2f}')

    if trade_log:
        ts = trade_stats(trade_log, n)
        print()
        print(f'  ── 거래 ──')
        print(f'  총 거래           {ts["total_trades"]}건')
        print(f'  승률              {ts["win_rate"]:.1%}')
        print(f'  평균 수익         {ts["avg_return"]:+.2f}%')
        print(f'  평균 이익 (승)    +{ts["avg_win"]:.2f}%')
        print(f'  평균 손실 (패)    -{ts["avg_loss"]:.2f}%')
        print(f'  손익비            {ts["profit_loss_ratio"]:.2f}')
        pf = ts["profit_factor"]
        pf_str = f'{pf:.2f}' if pf != float('inf') else '∞'
        print(f'  프로핏 팩터       {pf_str}')
        print(f'  기대값            {ts["expectancy"]:+.2f}%')
        print(f'  최대 연승         {ts["max_consecutive_win"]}연승')
        print(f'  최대 연패         {ts["max_consecutive_loss"]}연패')
        if ts['avg_hold_days'] > 0:
            print(f'  평균 보유일       {ts["avg_hold_days"]:.0f}일')
        print(f'  연환산 회전율     {ts["turnover"]:.1f}회')

    print(f'{"="*50}')


def compare(results, bench_daily=None):
    """여러 전략 비교 테이블

    results: list of (label, daily_rets, trade_log_or_None)
    bench_daily: 벤치마크 일일 수익률 (IR 계산용, optional)
    벤치마크가 포함된 경우 'BM:' 라벨로 전달하면 알파 계산.
    """
    # 벤치마크 누적 수익률 찾기 (KOSPI 우선)
    bench_total = None
    bench_rets = bench_daily
    for label, daily_rets, tlog in results:
        if 'BM:KOSPI' == label:
            bench_total = total_return(daily_rets)
            if bench_rets is None:
                bench_rets = daily_rets
            break
    if bench_total is None:
        for label, daily_rets, tlog in results:
            if 'BM:' in label:
                bench_total = total_return(daily_rets)
                if bench_rets is None:
                    bench_rets = daily_rets
                break

    has_ir = bench_rets is not None
    w = 114 if has_ir else (104 if bench_total is not None else 94)
    print(f'\n{"="*w}')
    print(f'  전략 비교')
    print(f'{"="*w}')

    alpha_col = f' {"알파":>8}' if bench_total is not None else ''
    ir_col = f' {"IR":>6}' if has_ir else ''
    header = (f'{"전략":<16} {"누적":>7} {"CAGR":>8} {"MDD":>7} '
              f'{"샤프":>6} {"소르티노":>8} {"칼마":>6} '
              f'{"승률":>6} {"PF":>6} {"거래":>5}{alpha_col}{ir_col}')
    print(header)
    print('-' * w)

    for label, daily_rets, tlog in results:
        tr = total_return(daily_rets)
        ca = cagr(daily_rets)
        mdd = max_drawdown(daily_rets)
        sh = sharpe_ratio(daily_rets)
        so = sortino_ratio(daily_rets)
        cal = calmar_ratio(daily_rets)

        if tlog:
            ts = trade_stats(tlog)
            wr = f'{ts["win_rate"]:.0%}'
            pf = ts["profit_factor"]
            pf_str = f'{pf:.1f}' if pf != float('inf') else '∞'
            trades = f'{ts["total_trades"]}'
        else:
            wr = '-'
            pf_str = '-'
            trades = '-'

        alpha_str = ''
        if bench_total is not None:
            alpha = tr - bench_total
            alpha_str = f' {alpha:>+7.1f}%'

        ir_str = ''
        if has_ir and not label.startswith('BM:'):
            ir_val = information_ratio(daily_rets, bench_rets)
            ir_str = f' {ir_val:>6.2f}'
        elif has_ir:
            ir_str = f' {"—":>6}'

        print(f'{label:<16} {tr:>+6.1f}% {ca:>+7.1f}% {mdd:>+6.1f}% '
              f'{sh:>6.2f} {so:>8.2f} {cal:>6.2f} '
              f'{wr:>6} {pf_str:>6} {trades:>5}{alpha_str}{ir_str}')

    print(f'{"="*w}')


if __name__ == '__main__':
    # 테스트: 샘플 데이터
    sample_rets = [0.5, -0.3, 1.2, -2.0, 0.8, 0.3, -0.5, 1.5, -1.0, 0.7] * 25
    sample_trades = [
        {'return': 5.2, 'entry_date': '2026-02-12', 'exit_date': '2026-02-20'},
        {'return': -3.1, 'entry_date': '2026-02-20', 'exit_date': '2026-02-25'},
        {'return': 8.5, 'entry_date': '2026-02-25', 'exit_date': '2026-03-05'},
        {'return': -10.0, 'entry_date': '2026-03-05', 'exit_date': '2026-03-06'},
        {'return': 2.3, 'entry_date': '2026-03-06', 'exit_date': '2026-03-12'},
    ]
    report(sample_rets, sample_trades, label='테스트 (샘플 데이터)')
