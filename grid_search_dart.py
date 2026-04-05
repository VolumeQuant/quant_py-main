"""DART 기반 종합 그리드 서치 — 팩터 가중치 + 진입/퇴출/슬롯 최적화

평가: 전체(2020~2026), 2024~2026, 2022(하락장), 연도별
지표: CAGR, MDD, Sharpe, Sortino, Alpha, Calmar
"""
import os, json, glob, time, sys
import pandas as pd
import numpy as np
from pathlib import Path
from collections import defaultdict
from itertools import product

sys.stdout.reconfigure(encoding='utf-8')
PROJECT = Path(__file__).parent
OHLCV_DIR = PROJECT / 'data_cache'


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
    except:
        pass
    return pd.Series()


def rerank_data(all_data, v_w, q_w, g_w, m_w):
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
    dates = sorted(all_data.keys())
    if start_filter:
        dates = [d for d in dates if d >= start_filter]
    if end_filter:
        dates = [d for d in dates if d <= end_filter]

    portfolio = {}
    equity = 1.0
    peak = 1.0
    max_dd = 0
    daily_returns = []

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

        if i < 2:
            continue

        for tk in list(portfolio.keys()):
            cp = get_price(tk, d0)
            ep = portfolio[tk]
            if cp > 0 and ep > 0 and (cp / ep - 1) <= -0.10:
                del portfolio[tk]

        r0 = all_data.get(d0, {}).get('rankings', [])
        r1 = all_data.get(d1, {}).get('rankings', []) if d1 else []
        r2 = all_data.get(d2, {}).get('rankings', []) if d2 else []
        if not r0:
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

        for tk in list(portfolio.keys()):
            if _wr(tk) > exit_rank:
                del portfolio[tk]

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

    if not daily_returns or len(daily_returns) < 10:
        return None

    days = len(daily_returns)
    years = days / 252
    cum = (equity - 1) * 100
    cagr = (equity ** (1 / years) - 1) * 100 if years > 0 else 0

    mean_r = np.mean(daily_returns)
    std_r = np.std(daily_returns, ddof=1)
    sharpe = (mean_r / std_r) * (252 ** 0.5) if std_r > 0 else 0

    downside = [r for r in daily_returns if r < 0]
    down_std = np.std(downside, ddof=1) if len(downside) > 1 else 1e-9
    sortino = (mean_r / down_std) * (252 ** 0.5) if down_std > 0 else 0

    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    return {
        'cum': cum, 'cagr': cagr, 'mdd': max_dd,
        'sharpe': sharpe, 'sortino': sortino, 'calmar': calmar,
        'days': days,
    }


def calc_alpha(result, daily_dates, kospi_prices):
    if kospi_prices.empty or not result:
        return 0
    kospi_rets = kospi_prices.pct_change().dropna()
    sys_cum = 1 + result['cum'] / 100
    # rough alpha
    years = result['days'] / 252
    first_ts = pd.Timestamp(daily_dates[0]) if daily_dates else None
    last_ts = pd.Timestamp(daily_dates[-1]) if daily_dates else None
    if first_ts and last_ts and first_ts in kospi_prices.index and last_ts in kospi_prices.index:
        k_start = kospi_prices.loc[first_ts]
        k_end = kospi_prices.loc[last_ts]
        if k_start > 0:
            bench_cum = k_end / k_start
            bench_ann = (bench_cum ** (1 / years) - 1) * 100 if years > 0 else 0
            return result['cagr'] - bench_ann
    return 0


if __name__ == '__main__':
    print('=' * 70)
    print('  DART 기반 종합 그리드 서치')
    print('=' * 70)

    t_start = time.time()

    print('\n데이터 로딩...')
    ohlcv = load_ohlcv()
    kospi = load_kospi()

    dart_dirs = [PROJECT / 'state' / f'bt_{y}' for y in range(2020, 2026)] + [PROJECT / 'state']
    dart_raw = load_rankings(dart_dirs)
    print(f'DART ranking: {len(dart_raw)}일')

    # ============================================================
    # Phase 1: 팩터 가중치 그리드 (진입/퇴출 고정: E5/X12/S7)
    # ============================================================
    print('\n' + '#' * 70)
    print('  Phase 1: 팩터 가중치 최적화 (E5/X12/S7 고정)')
    print('#' * 70)

    weight_combos = []
    for v in range(5, 35, 5):
        for q in range(10, 35, 5):
            for g in range(15, 55, 5):
                m = 100 - v - q - g
                if 10 <= m <= 40:
                    weight_combos.append((v, q, g, m))

    print(f'팩터 가중치 조합: {len(weight_combos)}개')

    p1_results = []
    done = 0
    for v, q, g, m in weight_combos:
        reranked = rerank_data(dart_raw, v/100, q/100, g/100, m/100)

        r_full = simulate(reranked, ohlcv, entry_rank=5, exit_rank=12, max_slots=7,
                          start_filter='20200710', end_filter='20260320')
        r_2024 = simulate(reranked, ohlcv, entry_rank=5, exit_rank=12, max_slots=7,
                          start_filter='20240102', end_filter='20260320')
        r_2022 = simulate(reranked, ohlcv, entry_rank=5, exit_rank=12, max_slots=7,
                          start_filter='20220103', end_filter='20221229')

        if r_full and r_2024:
            p1_results.append({
                'v': v, 'q': q, 'g': g, 'm': m,
                'full_cagr': r_full['cagr'], 'full_mdd': r_full['mdd'],
                'full_sharpe': r_full['sharpe'], 'full_sortino': r_full['sortino'],
                'full_calmar': r_full['calmar'],
                'r2024_cagr': r_2024['cagr'], 'r2024_mdd': r_2024['mdd'],
                'r2024_sharpe': r_2024['sharpe'],
                'r2022_cagr': r_2022['cagr'] if r_2022 else 0,
                'r2022_mdd': r_2022['mdd'] if r_2022 else -99,
            })

        done += 1
        if done % 20 == 0:
            print(f'  [{done}/{len(weight_combos)}] {time.time()-t_start:.0f}초')

    # 정렬 기준: 전체 Sharpe
    p1_results.sort(key=lambda x: -x['full_sharpe'])

    print(f'\n=== Phase 1 결과: 전체기간 Sharpe 기준 Top 15 ===')
    print(f'{"#":>3} {"V":>3}{"Q":>3}{"G":>3}{"M":>3} {"전체CAGR":>9} {"전체MDD":>8} {"Sharpe":>7} {"Sortino":>8} {"Calmar":>7} {"24~26":>8} {"2022":>8}')
    print('-' * 80)
    for i, r in enumerate(p1_results[:15]):
        marker = ' <--' if r['v']==5 and r['q']==20 and r['g']==45 and r['m']==30 else ''
        print(f'{i+1:>3} V{r["v"]:>2}Q{r["q"]:>2}G{r["g"]:>2}M{r["m"]:>2} '
              f'{r["full_cagr"]:>+8.1f}% {r["full_mdd"]:>7.1f}% {r["full_sharpe"]:>7.2f} '
              f'{r["full_sortino"]:>8.2f} {r["full_calmar"]:>7.2f} '
              f'{r["r2024_cagr"]:>+7.1f}% {r["r2022_cagr"]:>+7.1f}%{marker}')

    # 2024~2026 기준 Top 15
    p1_by_2024 = sorted(p1_results, key=lambda x: -x['r2024_sharpe'])
    print(f'\n=== Phase 1 결과: 2024~2026 Sharpe 기준 Top 15 ===')
    print(f'{"#":>3} {"V":>3}{"Q":>3}{"G":>3}{"M":>3} {"전체CAGR":>9} {"24~26":>8} {"24Shrp":>7} {"2022":>8} {"2022MDD":>8}')
    print('-' * 65)
    for i, r in enumerate(p1_by_2024[:15]):
        marker = ' <--' if r['v']==5 and r['q']==20 and r['g']==45 and r['m']==30 else ''
        print(f'{i+1:>3} V{r["v"]:>2}Q{r["q"]:>2}G{r["g"]:>2}M{r["m"]:>2} '
              f'{r["full_cagr"]:>+8.1f}% {r["r2024_cagr"]:>+7.1f}% {r["r2024_sharpe"]:>7.2f} '
              f'{r["r2022_cagr"]:>+7.1f}% {r["r2022_mdd"]:>7.1f}%{marker}')

    # ============================================================
    # Phase 2: Top 5 가중치 × 진입/퇴출/슬롯
    # ============================================================
    print('\n\n' + '#' * 70)
    print('  Phase 2: 진입/퇴출/슬롯 최적화 (Top 5 가중치)')
    print('#' * 70)

    top5_weights = p1_results[:5]
    entry_opts = [3, 4, 5, 6, 7]
    exit_opts = [8, 10, 12, 15, 18, 20]
    slot_opts = [5, 7, 10]

    p2_results = []
    total = len(top5_weights) * len(entry_opts) * len(exit_opts) * len(slot_opts)
    done = 0

    for w in top5_weights:
        reranked = rerank_data(dart_raw, w['v']/100, w['q']/100, w['g']/100, w['m']/100)
        for entry, exit_, slots in product(entry_opts, exit_opts, slot_opts):
            if exit_ <= entry:
                continue

            r_full = simulate(reranked, ohlcv, entry_rank=entry, exit_rank=exit_, max_slots=slots,
                              start_filter='20200710', end_filter='20260320')
            r_2024 = simulate(reranked, ohlcv, entry_rank=entry, exit_rank=exit_, max_slots=slots,
                              start_filter='20240102', end_filter='20260320')
            r_2022 = simulate(reranked, ohlcv, entry_rank=entry, exit_rank=exit_, max_slots=slots,
                              start_filter='20220103', end_filter='20221229')

            if r_full:
                p2_results.append({
                    'v': w['v'], 'q': w['q'], 'g': w['g'], 'm': w['m'],
                    'entry': entry, 'exit': exit_, 'slots': slots,
                    'full_cagr': r_full['cagr'], 'full_mdd': r_full['mdd'],
                    'full_sharpe': r_full['sharpe'], 'full_sortino': r_full['sortino'],
                    'full_calmar': r_full['calmar'],
                    'r2024_cagr': r_2024['cagr'] if r_2024 else 0,
                    'r2022_cagr': r_2022['cagr'] if r_2022 else 0,
                    'r2022_mdd': r_2022['mdd'] if r_2022 else -99,
                })

            done += 1
            if done % 50 == 0:
                print(f'  [{done}/{total}] {time.time()-t_start:.0f}초')

    # 정렬: 전체 Sharpe
    p2_results.sort(key=lambda x: -x['full_sharpe'])

    print(f'\n=== Phase 2 결과: 전체기간 Sharpe Top 20 ===')
    print(f'{"#":>3} {"가중치":<14} {"E":>2}{"X":>3}{"S":>2} {"CAGR":>8} {"MDD":>7} {"Sharpe":>7} {"Sortino":>8} {"24~26":>8} {"2022":>8}')
    print('-' * 75)
    for i, r in enumerate(p2_results[:20]):
        w_str = f'V{r["v"]}Q{r["q"]}G{r["g"]}M{r["m"]}'
        marker = ' <--' if r['v']==5 and r['q']==20 and r['g']==45 and r['m']==30 and r['entry']==5 and r['exit']==12 and r['slots']==7 else ''
        print(f'{i+1:>3} {w_str:<14} {r["entry"]:>2}{r["exit"]:>3}{r["slots"]:>2} '
              f'{r["full_cagr"]:>+7.1f}% {r["full_mdd"]:>6.1f}% {r["full_sharpe"]:>7.2f} '
              f'{r["full_sortino"]:>8.2f} {r["r2024_cagr"]:>+7.1f}% {r["r2022_cagr"]:>+7.1f}%{marker}')

    # 2024~2026 Sharpe Top 20
    p2_by_2024 = sorted(p2_results, key=lambda x: -(x.get('r2024_cagr', 0)))
    print(f'\n=== Phase 2 결과: 2024~2026 CAGR Top 20 ===')
    print(f'{"#":>3} {"가중치":<14} {"E":>2}{"X":>3}{"S":>2} {"전체":>8} {"24~26":>8} {"2022":>8} {"2022MDD":>8}')
    print('-' * 65)
    for i, r in enumerate(p2_by_2024[:20]):
        w_str = f'V{r["v"]}Q{r["q"]}G{r["g"]}M{r["m"]}'
        print(f'{i+1:>3} {w_str:<14} {r["entry"]:>2}{r["exit"]:>3}{r["slots"]:>2} '
              f'{r["full_cagr"]:>+7.1f}% {r["r2024_cagr"]:>+7.1f}% '
              f'{r["r2022_cagr"]:>+7.1f}% {r["r2022_mdd"]:>7.1f}%')

    # ============================================================
    # Phase 3: 연도별 분해 (Top 1)
    # ============================================================
    if p2_results:
        best = p2_results[0]
        print(f'\n\n{"#"*70}')
        print(f'  Phase 3: 최적 전략 연도별 분해')
        print(f'  V{best["v"]}Q{best["q"]}G{best["g"]}M{best["m"]} E{best["entry"]}/X{best["exit"]}/S{best["slots"]}')
        print(f'{"#"*70}')

        reranked = rerank_data(dart_raw, best['v']/100, best['q']/100, best['g']/100, best['m']/100)

        year_ranges = [
            ('2020(7~12)', '20200710', '20201230'),
            ('2021', '20210104', '20211230'),
            ('2022', '20220103', '20221229'),
            ('2023', '20230102', '20231228'),
            ('2024', '20240102', '20241230'),
            ('2025~26', '20250102', '20260320'),
            ('전체', '20200710', '20260320'),
        ]

        print(f'\n{"연도":<12} {"CAGR":>8} {"MDD":>8} {"Sharpe":>8} {"Sortino":>8} {"Calmar":>8}')
        print('-' * 55)
        for label, start, end in year_ranges:
            r = simulate(reranked, ohlcv, entry_rank=best['entry'], exit_rank=best['exit'],
                        max_slots=best['slots'], start_filter=start, end_filter=end)
            if r:
                print(f'{label:<12} {r["cagr"]:>+7.1f}% {r["mdd"]:>7.1f}% {r["sharpe"]:>8.2f} '
                      f'{r["sortino"]:>8.2f} {r["calmar"]:>8.2f}')
            else:
                print(f'{label:<12} {"N/A":>8}')

    # ============================================================
    # 최종 요약
    # ============================================================
    print(f'\n\n{"="*70}')
    print(f'  최종 요약')
    print(f'{"="*70}')
    print(f'총 소요: {(time.time()-t_start)/60:.1f}분')

    if p2_results:
        best = p2_results[0]
        print(f'\n[전체기간 Sharpe 1위]')
        print(f'  V{best["v"]}Q{best["q"]}G{best["g"]}M{best["m"]} E≤{best["entry"]}/X>{best["exit"]}/S{best["slots"]}')
        print(f'  CAGR: {best["full_cagr"]:+.1f}%, MDD: {best["full_mdd"]:.1f}%, Sharpe: {best["full_sharpe"]:.2f}, Sortino: {best["full_sortino"]:.2f}')

    if p2_by_2024:
        best24 = p2_by_2024[0]
        print(f'\n[2024~2026 CAGR 1위]')
        print(f'  V{best24["v"]}Q{best24["q"]}G{best24["g"]}M{best24["m"]} E≤{best24["entry"]}/X>{best24["exit"]}/S{best24["slots"]}')
        print(f'  2024~26 CAGR: {best24["r2024_cagr"]:+.1f}%, 전체 CAGR: {best24["full_cagr"]:+.1f}%')

    # v71 현행 찾기
    v71_current = [r for r in p2_results if r['v']==5 and r['q']==20 and r['g']==45 and r['m']==30
                   and r['entry']==5 and r['exit']==12 and r['slots']==7]
    if v71_current:
        c = v71_current[0]
        rank_sharpe = sorted(p2_results, key=lambda x: -x['full_sharpe']).index(c) + 1
        print(f'\n[v71 현행 (V5Q20G45M30 E5/X12/S7)]')
        print(f'  CAGR: {c["full_cagr"]:+.1f}%, Sharpe: {c["full_sharpe"]:.2f}, 순위: {rank_sharpe}/{len(p2_results)}')

    print('\n완료!')
