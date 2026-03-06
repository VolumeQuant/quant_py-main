"""
V/Q/G/M 가중치 최적화 백테스트 — 실전략 시뮬레이션

실제 전략 파이프라인을 그대로 재현:
1. 매일 가중치로 재정렬 → composite_rank 산출
2. 3일 교집합 (Slow In) → 검증 종목 중 가중순위 TOP 5
3. TOP 5 변경 시에만 리밸런싱 (빠진 종목 매도, 새 종목 매수)
4. 변경 없으면 보유 유지

타임라인:
- 2/9, 2/10, 2/11 ranking → 2/11 장마감 후 첫 3일 교집합 가능
- 2/12에 첫 매수 (시그널 다음 거래일)
- 이후 매일 새 시그널 → 포트폴리오 변경 시 다음날 리밸런싱
- 매도: 3/5 종가 기준
"""
import json
import statistics
from pathlib import Path
from collections import defaultdict

STATE_DIR = Path(__file__).parent / 'state'
TOP_N = 30       # 교집합 기준 상위 N
MAX_PICKS = 5    # 최종 추천 수
DEFAULT_MISSING_RANK = 50  # 신규 종목 페널티 (ranking_manager.py와 동일)


def load_all_rankings():
    """모든 ranking JSON 로드 (날짜순)"""
    files = sorted(STATE_DIR.glob('ranking_*.json'))
    all_data = {}
    for f in files:
        date_str = f.stem.replace('ranking_', '')
        if len(date_str) == 8 and date_str.isdigit():
            with open(f, 'r', encoding='utf-8') as fp:
                data = json.load(fp)
            all_data[date_str] = data['rankings']
    return all_data


def rerank_all(rankings, v_w, q_w, g_w, m_w):
    """
    주어진 가중치로 전 종목 점수 재계산 → composite_rank 부여

    Returns:
        list of dicts (원본 + score 재계산 + composite_rank 재부여)
    """
    scored = []
    for r in rankings:
        vs = r.get('value_s')
        qs = r.get('quality_s')
        gs = r.get('growth_s')
        ms = r.get('momentum_s')
        if any(x is None for x in [vs, qs, gs, ms]):
            continue
        entry = r.copy()
        entry['score'] = vs * v_w + qs * q_w + gs * g_w + ms * m_w
        scored.append(entry)

    # 점수 내림차순 → composite_rank 부여
    scored.sort(key=lambda x: -x['score'])
    for i, entry in enumerate(scored):
        entry['composite_rank'] = i + 1

    return scored


def simulate_3day_intersection(ranked_t0, ranked_t1, ranked_t2):
    """
    3일 교집합 + 가중순위 → TOP 5 반환

    ranking_manager.py의 get_stock_status + compute_3day_intersection 로직 재현:
    - 3일 연속 TOP 30 진입 종목 = 검증(✅)
    - 가중순위: T0×0.5 + T1×0.3 + T2×0.2
    - 신규 종목(과거 데이터 없음): DEFAULT_MISSING_RANK 페널티

    Returns:
        [(ticker, weighted_rank), ...] 상위 MAX_PICKS개
    """
    # 각 날짜의 전체 종목 맵
    map_t0 = {r['ticker']: r for r in ranked_t0}
    map_t1 = {r['ticker']: r for r in ranked_t1}
    map_t2 = {r['ticker']: r for r in ranked_t2}

    # 각 날짜의 TOP N ticker set
    top_t0 = {r['ticker'] for r in ranked_t0 if r['composite_rank'] <= TOP_N}
    top_t1 = {r['ticker'] for r in ranked_t1 if r['composite_rank'] <= TOP_N}
    top_t2 = {r['ticker'] for r in ranked_t2 if r['composite_rank'] <= TOP_N}

    # 모든 T-0 종목에 대해 가중순위 계산 (get_stock_status 로직)
    weighted_list = []
    for ticker in map_t0:
        rank_t0 = map_t0[ticker]['composite_rank']
        rank_t1 = map_t1[ticker]['composite_rank'] if ticker in map_t1 else DEFAULT_MISSING_RANK
        rank_t2 = map_t2[ticker]['composite_rank'] if ticker in map_t2 else DEFAULT_MISSING_RANK
        weighted = rank_t0 * 0.5 + rank_t1 * 0.3 + rank_t2 * 0.2

        # 상태 판별: 3일 교집합 = ✅
        in_t1 = ticker in top_t1
        in_t2 = ticker in top_t2
        is_verified = in_t1 and in_t2  # ✅ 조건

        weighted_list.append((ticker, weighted, is_verified))

    # 가중순위 기준 TOP N 선택 (get_stock_status와 동일)
    weighted_list.sort(key=lambda x: x[1])
    top_n_pool = weighted_list[:TOP_N]

    # ✅ 검증 종목만 필터 → 가중순위 상위 MAX_PICKS
    verified = [(t, w) for t, w, v in top_n_pool if v]
    return verified[:MAX_PICKS]


def run_backtest(all_data, v_pct, q_pct, g_pct, m_pct):
    """
    실전략 시뮬레이션 백테스트

    Returns:
        dict with 'total_return', 'sharpe', 'mdd', 'daily_returns',
             'trades', 'portfolio_history'
    """
    v_w, q_w, g_w, m_w = v_pct / 100, q_pct / 100, g_pct / 100, m_pct / 100
    dates = sorted(all_data.keys())

    # 모든 날짜에 대해 가중치로 재정렬
    ranked_by_date = {}
    for d in dates:
        ranked_by_date[d] = rerank_all(all_data[d], v_w, q_w, g_w, m_w)

    # 날짜별 가격 맵
    price_map = {}
    for d in dates:
        price_map[d] = {}
        for r in ranked_by_date[d]:
            if r.get('price') is not None and r['price'] > 0:
                price_map[d][r['ticker']] = r['price']

    # --- 시뮬레이션 ---
    # 첫 3일 교집합: dates[0], dates[1], dates[2] → 시그널
    # 매수: dates[3] (시그널 다음 거래일)
    if len(dates) < 4:
        return None

    portfolio = []        # 현재 보유 종목 [ticker, ...]
    portfolio_history = []  # [(date, [tickers])]
    daily_returns = []    # 일별 수익률
    trade_count = 0       # 리밸런싱 횟수

    for i in range(2, len(dates) - 1):
        signal_date = dates[i]
        trade_date = dates[i + 1]  # 시그널 다음날 매매

        # 3일 교집합 계산
        t0 = ranked_by_date[dates[i]]
        t1 = ranked_by_date[dates[i - 1]]
        t2 = ranked_by_date[dates[i - 2]]
        top5 = simulate_3day_intersection(t0, t1, t2)
        new_portfolio = [t for t, w in top5]

        # 포트폴리오 변경 감지
        if set(new_portfolio) != set(portfolio):
            trade_count += 1
            portfolio = new_portfolio

        portfolio_history.append((trade_date, list(portfolio)))

        # 수익률 계산: trade_date 종가 vs 전날 종가
        prev_date = dates[i]  # signal_date = 전일
        if portfolio:
            rets = []
            for ticker in portfolio:
                p_prev = price_map[prev_date].get(ticker)
                p_now = price_map[trade_date].get(ticker)
                if p_prev and p_now and p_prev > 0:
                    rets.append((p_now - p_prev) / p_prev)
            if rets:
                daily_returns.append(sum(rets) / len(rets))
            else:
                daily_returns.append(0.0)
        else:
            daily_returns.append(0.0)

    # --- 지표 계산 ---
    if not daily_returns:
        return None

    cumulative = 1.0
    peak = 1.0
    max_dd = 0.0
    equity_curve = [1.0]

    for r in daily_returns:
        cumulative *= (1 + r)
        equity_curve.append(cumulative)
        if cumulative > peak:
            peak = cumulative
        dd = (peak - cumulative) / peak
        if dd > max_dd:
            max_dd = dd

    total_return = (cumulative - 1) * 100

    if len(daily_returns) >= 2:
        mean_r = statistics.mean(daily_returns)
        std_r = statistics.stdev(daily_returns)
        sharpe = (mean_r / std_r) * (252 ** 0.5) if std_r > 0 else 0.0
    else:
        sharpe = 0.0

    return {
        'total_return': total_return,
        'sharpe': sharpe,
        'mdd': max_dd * 100,
        'daily_returns': daily_returns,
        'trades': trade_count,
        'equity_curve': equity_curve,
        'portfolio_history': portfolio_history,
    }


def generate_weight_grid(step=5, min_w=10, max_w=40):
    """가중치 그리드 (합=100%)"""
    combos = []
    for v in range(min_w, max_w + 1, step):
        for q in range(min_w, max_w + 1, step):
            for g in range(min_w, max_w + 1, step):
                m = 100 - v - q - g
                if min_w <= m <= max_w:
                    combos.append((v, q, g, m))
    return combos


def main():
    print("=" * 70)
    print("  V/Q/G/M Weight Optimization — Full Strategy Simulation")
    print("=" * 70)
    print()
    print("Pipeline: rerank -> 3-day intersection -> weighted rank -> TOP 5")
    print(f"Parameters: TOP_N={TOP_N}, MAX_PICKS={MAX_PICKS}, "
          f"NEW_PENALTY={DEFAULT_MISSING_RANK}")
    print()

    # 데이터 로드
    all_data = load_all_rankings()
    dates = sorted(all_data.keys())
    print(f"Data: {dates[0]} ~ {dates[-1]} ({len(dates)} trading days)")
    print(f"First signal: {dates[2]} -> First buy: {dates[3]}")
    print(f"Last sell: {dates[-1]}")
    print(f"Backtest period: {dates[3]} ~ {dates[-1]} ({len(dates)-3} trading days)")
    print()

    # 가중치 그리드
    combos = generate_weight_grid(step=5)
    print(f"Testing {len(combos)} weight combinations...")
    print()

    # 백테스트 실행
    results = []
    for idx, (v, q, g, m) in enumerate(combos):
        result = run_backtest(all_data, v, q, g, m)
        if result:
            results.append({
                'label': f"V{v}/Q{q}/G{g}/M{m}",
                'v': v, 'q': q, 'g': g, 'm': m,
                'return': result['total_return'],
                'sharpe': result['sharpe'],
                'mdd': result['mdd'],
                'trades': result['trades'],
                'portfolio_history': result['portfolio_history'],
            })
        if (idx + 1) % 50 == 0:
            print(f"  {idx+1}/{len(combos)} done...")

    print(f"\nCompleted: {len(results)} valid results")
    print()

    # ══════════════════════════════════════════
    # 샤프 기준 TOP 20
    # ══════════════════════════════════════════
    print("=" * 75)
    print("  SHARPE RATIO TOP 20")
    print("=" * 75)
    by_sharpe = sorted(results, key=lambda x: -x['sharpe'])
    print(f"{'Rank':>4} {'Weights':<20} {'Return':>8} {'Sharpe':>8} {'MDD':>8} {'Trades':>7}")
    print("-" * 60)
    for i, r in enumerate(by_sharpe[:20]):
        marker = " ***" if r['label'] == 'V30/Q25/G25/M20' else ""
        print(f"{i+1:>4} {r['label']:<20} {r['return']:>7.2f}% "
              f"{r['sharpe']:>8.2f} {r['mdd']:>7.2f}% {r['trades']:>5}{marker}")

    # ══════════════════════════════════════════
    # 현재 전략 위치
    # ══════════════════════════════════════════
    print()
    current = next((r for r in results if r['label'] == 'V30/Q25/G25/M20'), None)
    if current:
        sharpe_rank = sorted(results, key=lambda x: -x['sharpe']).index(current) + 1
        ret_rank = sorted(results, key=lambda x: -x['return']).index(current) + 1
        mdd_rank = sorted(results, key=lambda x: x['mdd']).index(current) + 1
        print(f"--- CURRENT STRATEGY: V30/Q25/G25/M20 ---")
        print(f"  Return:  {current['return']:>7.2f}%  (rank {ret_rank}/{len(results)})")
        print(f"  Sharpe:  {current['sharpe']:>7.2f}   (rank {sharpe_rank}/{len(results)})")
        print(f"  MDD:     {current['mdd']:>7.2f}%  (rank {mdd_rank}/{len(results)})")
        print(f"  Trades:  {current['trades']}")

    # ══════════════════════════════════════════
    # 수익률 TOP 10
    # ══════════════════════════════════════════
    print()
    print("=" * 75)
    print("  RETURN TOP 10")
    print("=" * 75)
    by_return = sorted(results, key=lambda x: -x['return'])
    for i, r in enumerate(by_return[:10]):
        print(f"{i+1:>4} {r['label']:<20} {r['return']:>7.2f}% "
              f"{r['sharpe']:>8.2f} {r['mdd']:>7.2f}%")

    # ══════════════════════════════════════════
    # MDD TOP 10 (낮은 순)
    # ══════════════════════════════════════════
    print()
    print("=" * 75)
    print("  MDD TOP 10 (lowest drawdown)")
    print("=" * 75)
    by_mdd = sorted(results, key=lambda x: x['mdd'])
    for i, r in enumerate(by_mdd[:10]):
        print(f"{i+1:>4} {r['label']:<20} {r['return']:>7.2f}% "
              f"{r['sharpe']:>8.2f} {r['mdd']:>7.2f}%")

    # ══════════════════════════════════════════
    # 종합 순위 TOP 10
    # ══════════════════════════════════════════
    print()
    print("=" * 75)
    print("  COMPOSITE TOP 10 (Return rank + Sharpe rank + MDD rank)")
    print("=" * 75)
    ret_sorted = sorted(results, key=lambda x: -x['return'])
    sharpe_sorted = sorted(results, key=lambda x: -x['sharpe'])
    mdd_sorted = sorted(results, key=lambda x: x['mdd'])

    for r in results:
        r['ret_rank'] = ret_sorted.index(r) + 1
        r['sharpe_rank'] = sharpe_sorted.index(r) + 1
        r['mdd_rank'] = mdd_sorted.index(r) + 1
        r['composite'] = r['ret_rank'] + r['sharpe_rank'] + r['mdd_rank']

    by_composite = sorted(results, key=lambda x: x['composite'])
    for i, r in enumerate(by_composite[:10]):
        marker = " ***" if r['label'] == 'V30/Q25/G25/M20' else ""
        print(f"{i+1:>4} {r['label']:<20} {r['return']:>7.2f}% "
              f"{r['sharpe']:>8.2f} {r['mdd']:>7.2f}% "
              f"(R:{r['ret_rank']} S:{r['sharpe_rank']} M:{r['mdd_rank']} "
              f"sum:{r['composite']}){marker}")

    # ══════════════════════════════════════════
    # 팩터별 민감도 분석
    # ══════════════════════════════════════════
    print()
    print("=" * 75)
    print("  FACTOR SENSITIVITY (avg metric by weight level)")
    print("=" * 75)
    for factor, key in [('Value', 'v'), ('Quality', 'q'),
                        ('Growth', 'g'), ('Momentum', 'm')]:
        print(f"\n  {factor}:")
        levels = sorted(set(r[key] for r in results))
        for level in levels:
            subset = [r for r in results if r[key] == level]
            avg_ret = statistics.mean([r['return'] for r in subset])
            avg_sharpe = statistics.mean([r['sharpe'] for r in subset])
            avg_mdd = statistics.mean([r['mdd'] for r in subset])
            print(f"    {level:>2}%: ret={avg_ret:>7.2f}%  "
                  f"sharpe={avg_sharpe:>6.2f}  mdd={avg_mdd:>6.2f}%")

    # ══════════════════════════════════════════
    # 1위 포트폴리오 상세
    # ══════════════════════════════════════════
    print()
    print("=" * 75)
    print("  #1 COMPOSITE — Portfolio History")
    print("=" * 75)
    best = by_composite[0]
    print(f"  Weights: {best['label']}")
    print(f"  Return: {best['return']:.2f}%, Sharpe: {best['sharpe']:.2f}, "
          f"MDD: {best['mdd']:.2f}%, Trades: {best['trades']}")

    # 1위 재실행해서 포트폴리오 이력 출력
    best_result = run_backtest(
        all_data, best['v'], best['q'], best['g'], best['m']
    )
    if best_result:
        # ticker→name 맵 구축
        name_map = {}
        for d in all_data:
            for r in all_data[d]:
                if r['ticker'] not in name_map:
                    name_map[r['ticker']] = r.get('name', r['ticker'])

        print()
        prev_port = []
        for date, tickers in best_result['portfolio_history']:
            if set(tickers) != set(prev_port):
                names = [f"{name_map.get(t, t)}({t})" for t in tickers]
                print(f"  {date}: {', '.join(names)}")
                prev_port = tickers

    # 현재 전략도 포트폴리오 이력 출력
    if current:
        print()
        print(f"  --- Current V30/Q25/G25/M20 Portfolio History ---")
        cur_result = run_backtest(all_data, 30, 25, 25, 20)
        if cur_result:
            name_map = {}
            for d in all_data:
                for r in all_data[d]:
                    if r['ticker'] not in name_map:
                        name_map[r['ticker']] = r.get('name', r['ticker'])
            prev_port = []
            for date, tickers in cur_result['portfolio_history']:
                if set(tickers) != set(prev_port):
                    names = [f"{name_map.get(t, t)}({t})" for t in tickers]
                    print(f"  {date}: {', '.join(names)}")
                    prev_port = tickers

    print()
    print(f"* WARNING: {len(dates)} trading days is too short for statistical "
          f"significance.")
    print("* These results show directional tendencies, not definitive answers.")
    print("* Re-run as data accumulates for reliable optimization.")


if __name__ == '__main__':
    main()
