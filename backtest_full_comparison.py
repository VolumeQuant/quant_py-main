"""v69 vs v71 종합 백테스트 비교 — DART/pykrx, 연도별, 하락장, 집중도, 턴오버

Usage: python backtest_full_comparison.py
"""
import os, json, glob, time, math, sys
import pandas as pd
import numpy as np
from pathlib import Path
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')

PROJECT = Path(__file__).parent
OHLCV_DIR = PROJECT / 'data_cache'


# ============================================================
# 데이터 로드
# ============================================================
def load_rankings(state_dirs):
    all_data = {}
    for sd in state_dirs:
        if not sd.exists():
            continue
        for fp in sorted(glob.glob(str(sd / 'ranking_*.json'))):
            d = os.path.basename(fp).replace('ranking_', '').replace('.json', '')
            with open(fp, 'r', encoding='utf-8') as fh:
                all_data[d] = json.load(fh)
    return all_data


def load_ohlcv():
    ohlcv_files = sorted(glob.glob(str(OHLCV_DIR / 'all_ohlcv_*.parquet')))
    if not ohlcv_files:
        return pd.DataFrame()
    full_files = [f for f in ohlcv_files if '_full' in f]
    if full_files:
        ohlcv_files = full_files
    parts = [pd.read_parquet(f).replace(0, np.nan) for f in ohlcv_files]
    return pd.concat(parts).groupby(level=0).first()


def load_kospi():
    try:
        sys.path.insert(0, str(PROJECT))
        import krx_auth
        krx_auth.login()
        from pykrx import stock
        df = stock.get_index_ohlcv('20200101', '20260331', '1001')
        if not df.empty:
            return df.iloc[:, 3]
    except Exception as e:
        print(f'KOSPI 로드 실패: {e}')
    return pd.Series()


# ============================================================
# 시뮬레이터
# ============================================================
def rerank_data(all_data, v_w=0.05, q_w=0.20, g_w=0.45, m_w=0.30):
    """팩터 가중치 변경 → composite_rank 재계산

    ranking JSON의 value_s, quality_s, growth_s, momentum_s로
    새 score = v_w*V + q_w*Q + g_w*G + m_w*M 계산 → 순위 부여.
    """
    reranked = {}
    for date, rdata in all_data.items():
        rankings = rdata.get('rankings', [])
        if not rankings:
            reranked[date] = rdata
            continue

        scored = []
        for r in rankings:
            vs = r.get('value_s', 0) or 0
            qs = r.get('quality_s', 0) or 0
            gs = r.get('growth_s', 0) or 0
            ms = r.get('momentum_s', 0) or 0
            new_score = v_w * vs + q_w * qs + g_w * gs + m_w * ms
            scored.append((new_score, r))

        scored.sort(key=lambda x: -x[0])
        new_rankings = []
        for i, (sc, r) in enumerate(scored):
            nr = r.copy()
            nr['composite_rank'] = i + 1
            nr['score'] = round(sc, 4)
            new_rankings.append(nr)

        reranked[date] = {**rdata, 'rankings': new_rankings}
    return reranked


def simulate(all_data, ohlcv, entry_rank=5, exit_rank=12, max_slots=7,
             start_filter=None, end_filter=None):
    """
    Returns: dict with cum, cagr, mdd, sharpe, daily_returns, daily_dates,
             trades (매매횟수), holdings_history (일별 보유종목)
    """
    dates = sorted(all_data.keys())
    if start_filter:
        dates = [d for d in dates if d >= start_filter]
    if end_filter:
        dates = [d for d in dates if d <= end_filter]

    portfolio = {}
    equity = 1.0
    peak = 1.0
    max_dd = 0
    start_date = None
    daily_returns = []
    daily_dates = []
    trade_count = 0
    holdings_history = []

    def get_price(ticker, date_str):
        ts = pd.Timestamp(date_str)
        if not ohlcv.empty and ts in ohlcv.index and ticker in ohlcv.columns:
            v = ohlcv.loc[ts, ticker]
            if pd.notna(v) and v > 0:
                return v
        return 0

    for i in range(len(dates)):
        d0 = dates[i]
        d1 = dates[i - 1] if i >= 1 else None
        d2 = dates[i - 2] if i >= 2 else None

        day_ret = 0
        if i >= 1 and portfolio:
            rets = []
            for tk in portfolio:
                pp = get_price(tk, dates[i - 1])
                cp = get_price(tk, d0)
                if pp > 0 and cp > 0:
                    rets.append(cp / pp - 1)
            if rets:
                day_ret = sum(rets) / len(rets)
                equity *= (1 + day_ret)
            if equity > peak:
                peak = equity
            dd = (equity / peak - 1) * 100
            if dd < max_dd:
                max_dd = dd
            daily_returns.append(day_ret)
            daily_dates.append(d0)

        if i < 2:
            continue

        # 손절 -10%
        for tk in list(portfolio.keys()):
            cp = get_price(tk, d0)
            ep = portfolio[tk]
            if cp > 0 and ep > 0 and (cp / ep - 1) <= -0.10:
                del portfolio[tk]
                trade_count += 1

        r0 = all_data.get(d0, {}).get('rankings', [])
        r1 = all_data.get(d1, {}).get('rankings', []) if d1 else []
        r2 = all_data.get(d2, {}).get('rankings', []) if d2 else []

        if not r0:
            holdings_history.append(set(portfolio.keys()))
            continue

        all_t0 = {r['ticker']: r for r in r0}
        all_t1 = {r['ticker']: r for r in r1}
        all_t2 = {r['ticker']: r for r in r2}

        def _wr(tk):
            if tk not in all_t0:
                return 999
            cr0 = all_t0[tk].get('composite_rank', all_t0[tk].get('rank', 999))
            cr1 = all_t1[tk].get('composite_rank', all_t1[tk].get('rank', 999)) if tk in all_t1 else 999
            cr2 = all_t2[tk].get('composite_rank', all_t2[tk].get('rank', 999)) if tk in all_t2 else 999
            return cr0 * 0.5 + cr1 * 0.3 + cr2 * 0.2

        prev_portfolio = set(portfolio.keys())

        # 퇴출
        for tk in list(portfolio.keys()):
            if _wr(tk) > exit_rank:
                del portfolio[tk]
                trade_count += 1

        # 진입
        top20_t0 = {r['ticker']: r for r in r0 if r.get('composite_rank', r['rank']) <= 20}
        top20_t1 = {r['ticker']: r for r in r1 if r.get('composite_rank', r['rank']) <= 20}
        top20_t2 = {r['ticker']: r for r in r2 if r.get('composite_rank', r['rank']) <= 20}
        common = set(top20_t0) & set(top20_t1) & set(top20_t2)

        verified = []
        for tk in common:
            cr0 = top20_t0[tk].get('composite_rank', top20_t0[tk]['rank'])
            cr1 = top20_t1[tk].get('composite_rank', top20_t1[tk]['rank'])
            cr2 = top20_t2[tk].get('composite_rank', top20_t2[tk]['rank'])
            wr = cr0 * 0.5 + cr1 * 0.3 + cr2 * 0.2
            verified.append({'ticker': tk, 'weighted_rank': wr})
        verified.sort(key=lambda x: x['weighted_rank'])

        for v in verified:
            if v['ticker'] in portfolio:
                continue
            if len(portfolio) >= max_slots:
                break
            if v['weighted_rank'] <= entry_rank:
                ep = get_price(v['ticker'], d0)
                if ep > 0:
                    portfolio[v['ticker']] = ep
                    trade_count += 1
                    if start_date is None:
                        start_date = d0

        holdings_history.append(set(portfolio.keys()))

    if not daily_returns:
        return None

    days = len(daily_returns)
    years = days / 252
    cum = (equity - 1) * 100
    cagr = (equity ** (1 / years) - 1) * 100 if years > 0 else 0
    sharpe = 0
    if len(daily_returns) >= 2:
        mean_r = np.mean(daily_returns)
        std_r = np.std(daily_returns, ddof=1)
        sharpe = (mean_r / std_r) * (252 ** 0.5) if std_r > 0 else 0

    # 턴오버: 일평균 포트폴리오 변경 비율
    turnover_days = 0
    for j in range(1, len(holdings_history)):
        prev = holdings_history[j - 1]
        curr = holdings_history[j]
        if prev or curr:
            changed = len(prev.symmetric_difference(curr))
            total = max(len(prev), len(curr), 1)
            turnover_days += changed / total
    avg_turnover = turnover_days / max(len(holdings_history) - 1, 1) * 100

    # 종목 집중도: 가장 많이 보유한 종목 비율
    ticker_days = defaultdict(int)
    total_holding_days = 0
    for h in holdings_history:
        for tk in h:
            ticker_days[tk] += 1
            total_holding_days += 1
    top_ticker = max(ticker_days.items(), key=lambda x: x[1]) if ticker_days else ('', 0)
    concentration = top_ticker[1] / max(total_holding_days, 1) * 100

    return {
        'cum': cum, 'cagr': cagr, 'mdd': max_dd, 'sharpe': sharpe,
        'days': days, 'start_date': start_date,
        'daily_returns': daily_returns, 'daily_dates': daily_dates,
        'trades': trade_count, 'avg_turnover': avg_turnover,
        'top_ticker': top_ticker[0], 'concentration': concentration,
        'ticker_days': dict(ticker_days),
    }


def calc_alpha(result, kospi_prices):
    if kospi_prices.empty or not result or not result['daily_returns']:
        return 0
    kospi_rets = kospi_prices.pct_change().dropna()
    sys_cum = 1
    bench_cum = 1
    matched = 0
    for d, r in zip(result['daily_dates'], result['daily_returns']):
        ts = pd.Timestamp(d)
        if ts in kospi_rets.index:
            sys_cum *= (1 + r)
            bench_cum *= (1 + kospi_rets.loc[ts])
            matched += 1
    if matched < 10:
        return 0
    years = matched / 252
    sys_ann = (sys_cum ** (1 / years) - 1) * 100 if years > 0 else 0
    bench_ann = (bench_cum ** (1 / years) - 1) * 100 if years > 0 else 0
    return sys_ann - bench_ann


def print_comparison(label, results, kospi):
    print(f'\n{"="*70}')
    print(f'  {label}')
    print(f'{"="*70}')
    header = f'{"전략":<20} {"누적":>8} {"CAGR":>7} {"MDD":>7} {"Sharpe":>7} {"Alpha":>7} {"거래":>5} {"턴오버":>6} {"집중":>5}'
    print(header)
    print('-' * 75)
    for name, r in results:
        if r is None:
            print(f'{name:<20} {"데이터부족":>8}')
            continue
        alpha = calc_alpha(r, kospi)
        print(f'{name:<20} {r["cum"]:>+7.1f}% {r["cagr"]:>+6.1f}% {r["mdd"]:>6.1f}% {r["sharpe"]:>7.2f} {alpha:>+6.1f}% {r["trades"]:>5} {r["avg_turnover"]:>5.1f}% {r["concentration"]:>4.1f}%')


def get_top_holdings(result, ohlcv, n=5):
    """가장 오래 보유한 종목 top N"""
    if not result or not result.get('ticker_days'):
        return []
    sorted_tickers = sorted(result['ticker_days'].items(), key=lambda x: -x[1])
    return sorted_tickers[:n]


# ============================================================
# 메인
# ============================================================
if __name__ == '__main__':
    print('=' * 70)
    print('  v69 vs v71 종합 백테스트 비교')
    print('=' * 70)
    print()

    t_start = time.time()

    # 데이터 로드
    print('데이터 로딩...')
    ohlcv = load_ohlcv()
    kospi = load_kospi()

    # DART 기반 rankings (새로 생성)
    dart_dirs = [PROJECT / 'state' / f'bt_{y}' for y in range(2020, 2026)] + [PROJECT / 'state']
    dart_raw = load_rankings(dart_dirs)

    # pykrx 기반 rankings (백업)
    pykrx_dirs = [PROJECT / 'state' / f'bt_{y}_pykrx_backup' for y in range(2020, 2026)] + [PROJECT / 'state']
    pykrx_raw = load_rankings(pykrx_dirs)

    print(f'DART ranking: {len(dart_raw)}일')
    print(f'pykrx ranking: {len(pykrx_raw)}일')

    # 가중치별 rerank
    print('v71 가중치로 rerank (V5Q20G45M30)...')
    dart_v71 = rerank_data(dart_raw, v_w=0.05, q_w=0.20, g_w=0.45, m_w=0.30)
    pykrx_v71 = rerank_data(pykrx_raw, v_w=0.05, q_w=0.20, g_w=0.45, m_w=0.30)

    print('v69 가중치로 rerank (V25Q25G25M25)...')
    dart_v69 = rerank_data(dart_raw, v_w=0.25, q_w=0.25, g_w=0.25, m_w=0.25)
    pykrx_v69 = rerank_data(pykrx_raw, v_w=0.25, q_w=0.25, g_w=0.25, m_w=0.25)

    # ============================================================
    # STEP 2: DART vs pykrx (2024~2026, v71)
    # ============================================================
    print('\n\n' + '#' * 70)
    print('  STEP 2: DART vs pykrx 비교 (2024~2026, v71)')
    print('#' * 70)

    dart_2024_26 = simulate(dart_v71, ohlcv, entry_rank=5, exit_rank=12, max_slots=7,
                            start_filter='20240102', end_filter='20260331')
    pykrx_2024_26 = simulate(pykrx_v71, ohlcv, entry_rank=5, exit_rank=12, max_slots=7,
                              start_filter='20240102', end_filter='20260331')
    print_comparison('DART vs pykrx (2024~2026, v71 V5Q20G45M30)',
                     [('v71 DART', dart_2024_26), ('v71 pykrx', pykrx_2024_26)], kospi)

    # ============================================================
    # STEP 3: 그리드 서치 (2024~2026, DART, v71)
    # ============================================================
    print('\n\n' + '#' * 70)
    print('  STEP 3: 최적 진입/퇴출/슬롯 그리드 서치 (2024~2026)')
    print('#' * 70)

    grid_results = []
    for entry in [3, 4, 5, 6, 7]:
        for exit_ in [8, 10, 12, 15, 18, 20]:
            if exit_ <= entry:
                continue
            for slots in [5, 7, 10]:
                r = simulate(dart_v71, ohlcv, entry_rank=entry, exit_rank=exit_, max_slots=slots,
                             start_filter='20240102', end_filter='20260331')
                if r:
                    grid_results.append({
                        'entry': entry, 'exit': exit_, 'slots': slots, **r
                    })

    grid_results.sort(key=lambda x: -x['cagr'])
    print(f'\n총 {len(grid_results)}개 조합')
    print(f'{"#":>3} {"진입":>4} {"퇴출":>4} {"슬롯":>3} {"CAGR":>7} {"MDD":>7} {"Sharpe":>7}')
    print('-' * 40)
    for i, r in enumerate(grid_results[:15]):
        marker = ' ◀' if r['entry'] == 5 and r['exit'] == 12 and r['slots'] == 7 else ''
        print(f'{i+1:>3} {r["entry"]:>4} {r["exit"]:>4} {r["slots"]:>3} {r["cagr"]:>+6.1f}% {r["mdd"]:>6.1f}% {r["sharpe"]:>7.2f}{marker}')

    # ============================================================
    # STEP 4a: v69 vs v71 전체 (2020~2026, DART)
    # ============================================================
    print('\n\n' + '#' * 70)
    print('  STEP 4a: v69 vs v71 전체 비교 (2020~2026, DART)')
    print('#' * 70)

    # v69: 동일가중 V25Q25G25M25, 퇴출>15
    v69_dart_full = simulate(dart_v69, ohlcv, entry_rank=5, exit_rank=15, max_slots=7,
                              start_filter='20200102', end_filter='20260331')
    # v71: V5Q20G45M30, 퇴출>12
    v71_dart_full = simulate(dart_v71, ohlcv, entry_rank=5, exit_rank=12, max_slots=7,
                              start_filter='20200102', end_filter='20260331')
    print_comparison('v69 vs v71 (2020~2026, DART)',
                     [('v69 DART (E5/X15)', v69_dart_full), ('v71 DART (E5/X12)', v71_dart_full)], kospi)

    # ============================================================
    # STEP 4b: 연도별 분해
    # ============================================================
    print('\n\n' + '#' * 70)
    print('  STEP 4b: 연도별 분해')
    print('#' * 70)

    year_ranges = [
        ('2020', '20200102', '20201230'),
        ('2021', '20210104', '20211230'),
        ('2022', '20220103', '20221229'),
        ('2023', '20230102', '20231228'),
        ('2024', '20240102', '20241230'),
        ('2025~26', '20250102', '20260331'),
    ]

    print(f'\n{"연도":<10} {"v69 CAGR":>10} {"v71 CAGR":>10} {"v69 MDD":>10} {"v71 MDD":>10} {"차이":>8}')
    print('-' * 55)
    for label, start, end in year_ranges:
        r69 = simulate(dart_v69, ohlcv, entry_rank=5, exit_rank=15, max_slots=7,
                        start_filter=start, end_filter=end)
        r71 = simulate(dart_v71, ohlcv, entry_rank=5, exit_rank=12, max_slots=7,
                        start_filter=start, end_filter=end)
        c69 = f'{r69["cagr"]:>+9.1f}%' if r69 else '   N/A'
        c71 = f'{r71["cagr"]:>+9.1f}%' if r71 else '   N/A'
        m69 = f'{r69["mdd"]:>9.1f}%' if r69 else '   N/A'
        m71 = f'{r71["mdd"]:>9.1f}%' if r71 else '   N/A'
        diff = f'{r71["cagr"] - r69["cagr"]:>+7.1f}%p' if r69 and r71 else '   N/A'
        print(f'{label:<10} {c69:>10} {c71:>10} {m69:>10} {m71:>10} {diff:>8}')

    # ============================================================
    # STEP 4c: 하락장 (2022) 상세
    # ============================================================
    print('\n\n' + '#' * 70)
    print('  STEP 4c: 하락장 (2022) 상세')
    print('#' * 70)

    r69_2022 = simulate(dart_v69, ohlcv, entry_rank=5, exit_rank=15, max_slots=7,
                         start_filter='20220103', end_filter='20221229')
    r71_2022 = simulate(dart_v71, ohlcv, entry_rank=5, exit_rank=12, max_slots=7,
                         start_filter='20220103', end_filter='20221229')
    print_comparison('하락장 2022',
                     [('v69 DART', r69_2022), ('v71 DART', r71_2022)], kospi)

    # ============================================================
    # STEP 4d: DART 효과 분리 (v69 pykrx vs v69 DART)
    # ============================================================
    print('\n\n' + '#' * 70)
    print('  STEP 4d: DART 효과 분리 — v69 동일 전략, 데이터만 다름')
    print('#' * 70)

    v69_pykrx_full = simulate(pykrx_v69, ohlcv, entry_rank=5, exit_rank=15, max_slots=7,
                               start_filter='20200102', end_filter='20260331')
    print_comparison('v69: DART vs pykrx (2020~2026)',
                     [('v69 DART', v69_dart_full), ('v69 pykrx', v69_pykrx_full)], kospi)

    # ============================================================
    # STEP 4e: 종목 집중도
    # ============================================================
    print('\n\n' + '#' * 70)
    print('  STEP 4e: 종목 집중도 (2020~2026)')
    print('#' * 70)

    for name, result in [('v69 DART', v69_dart_full), ('v71 DART', v71_dart_full), ('v69 pykrx', v69_pykrx_full)]:
        if result:
            print(f'\n{name} — 가장 오래 보유한 종목 Top 5:')
            top = get_top_holdings(result, ohlcv, n=5)
            # ticker → name 매핑
            name_map = {}
            for d, rdata in dart_raw.items():
                for r in rdata.get('rankings', []):
                    if r['ticker'] not in name_map:
                        name_map[r['ticker']] = r.get('name', r['ticker'])
            for tk, days in top:
                nm = name_map.get(tk, tk)
                pct = days / max(sum(result['ticker_days'].values()), 1) * 100
                print(f'  {nm} ({tk}): {days}일 ({pct:.1f}%)')
            print(f'  집중도(1위): {result["concentration"]:.1f}%')

    # ============================================================
    # STEP 4f: 턴오버 비교
    # ============================================================
    print('\n\n' + '#' * 70)
    print('  STEP 4f: 턴오버 비교')
    print('#' * 70)

    print(f'\n{"전략":<20} {"거래횟수":>8} {"일평균턴오버":>10}')
    print('-' * 40)
    for name, r in [('v69 DART', v69_dart_full), ('v71 DART', v71_dart_full),
                     ('v69 pykrx', v69_pykrx_full)]:
        if r:
            print(f'{name:<20} {r["trades"]:>8} {r["avg_turnover"]:>9.1f}%')

    # ============================================================
    # 최종 요약
    # ============================================================
    print('\n\n' + '=' * 70)
    print('  최종 요약')
    print('=' * 70)

    print(f'\n총 소요: {(time.time() - t_start) / 60:.1f}분')

    if v69_dart_full and v71_dart_full and v69_pykrx_full:
        dart_effect = v69_dart_full['cagr'] - v69_pykrx_full['cagr']
        strategy_effect = v71_dart_full['cagr'] - v69_dart_full['cagr']
        total_effect = v71_dart_full['cagr'] - v69_pykrx_full['cagr']
        print(f'\n[효과 분해] (2020~2026)')
        print(f'  DART 전환 효과:  {dart_effect:>+.1f}%p (v69 pykrx→DART)')
        print(f'  전략 변경 효과:  {strategy_effect:>+.1f}%p (v69→v71, DART 기준)')
        print(f'  총 개선:         {total_effect:>+.1f}%p (v69 pykrx → v71 DART)')

    if grid_results:
        best = grid_results[0]
        print(f'\n[2024~2026 최적 조합]')
        print(f'  진입≤{best["entry"]} / 퇴출>{best["exit"]} / 슬롯{best["slots"]}')
        print(f'  CAGR: {best["cagr"]:+.1f}%, MDD: {best["mdd"]:.1f}%, Sharpe: {best["sharpe"]:.2f}')

    print('\n완료!')
