"""
진입/퇴출 순위 기준 그리드 서치 백테스트

현행 점수 기반(score≥72 진입, score<68 퇴출)을
순위 기반으로 전환할 때 최적 파라미터 탐색.

그리드:
  - entry_rank: ✅ 검증 종목 중 weighted_rank ≤ N (3,4,5,6,7,8,10)
  - exit_rank: weighted_rank > M이면 퇴출 (10,15,20,25,30)
  - top_n: pipeline 크기 — 상태 판별 + 워치리스트 (20,25,30)
  - 비교군: 현행 점수 기반 (entry≥72, exit<68)

시뮬레이션:
  - 매일 3일 가중순위 계산 → ✅ 검증 종목 중 entry 조건 → 포트폴리오
  - 포트폴리오 변경 시 다음날 종가 리밸런싱
  - 동일비중, 벤치마크(KODEX200) 비교
"""

import json
import statistics
from pathlib import Path
from collections import defaultdict

STATE_DIR = Path(__file__).parent / 'state'
DEFAULT_MISSING_RANK = 50


def load_all_rankings():
    files = sorted(STATE_DIR.glob('ranking_*.json'))
    all_data = {}
    for f in files:
        date_str = f.stem.replace('ranking_', '')
        if len(date_str) == 8 and date_str.isdigit():
            with open(f, 'r', encoding='utf-8') as fp:
                data = json.load(fp)
            all_data[date_str] = data
    return all_data


def weighted_score_100(ticker, r_t0, r_t1=None, r_t2=None):
    """점수 기반 비교군용"""
    def _build_maps(rankings):
        if not rankings:
            return {}, 0
        rlist = rankings.get('rankings', [])
        ticker_map = {r['ticker']: r['score'] for r in rlist}
        rank_map = {r.get('composite_rank', r['rank']): r['score'] for r in rlist}
        fallback = rank_map.get(DEFAULT_MISSING_RANK, 0)
        return ticker_map, fallback

    t0_map, _ = _build_maps(r_t0)
    t1_map, t1_fb = _build_maps(r_t1)
    t2_map, t2_fb = _build_maps(r_t2)

    s0 = t0_map.get(ticker, 0)
    s1 = t1_map.get(ticker, t1_fb)
    s2 = t2_map.get(ticker, t2_fb)
    ws = s0 * 0.5 + s1 * 0.3 + s2 * 0.2
    return max(0.0, min(100.0, (ws + 3.0) / 6.0 * 100))


def get_pipeline(rankings_t0, rankings_t1, rankings_t2, top_n):
    """get_stock_status 재현 — 가중순위 + 상태 판별"""
    all_t0 = {item['ticker']: item for item in rankings_t0.get('rankings', [])}
    all_t1 = {}
    top_t1_set = set()
    if rankings_t1:
        for item in rankings_t1.get('rankings', []):
            all_t1[item['ticker']] = item
            if item.get('composite_rank', item['rank']) <= top_n:
                top_t1_set.add(item['ticker'])
    all_t2 = {}
    top_t2_set = set()
    if rankings_t2:
        for item in rankings_t2.get('rankings', []):
            all_t2[item['ticker']] = item
            if item.get('composite_rank', item['rank']) <= top_n:
                top_t2_set.add(item['ticker'])

    scored = []
    for ticker, item in all_t0.items():
        entry = item.copy()
        rank_t0 = item.get('composite_rank', item['rank'])

        if rankings_t1 and rankings_t2:
            rank_t1 = all_t1[ticker].get('composite_rank', all_t1[ticker]['rank']) if ticker in all_t1 else DEFAULT_MISSING_RANK
            rank_t2 = all_t2[ticker].get('composite_rank', all_t2[ticker]['rank']) if ticker in all_t2 else DEFAULT_MISSING_RANK
            weighted = rank_t0 * 0.5 + rank_t1 * 0.3 + rank_t2 * 0.2
        elif rankings_t1:
            rank_t1 = all_t1[ticker].get('composite_rank', all_t1[ticker]['rank']) if ticker in all_t1 else DEFAULT_MISSING_RANK
            weighted = rank_t0 * 0.6 + rank_t1 * 0.4
        else:
            weighted = float(rank_t0)

        entry['weighted_rank'] = round(weighted, 1)

        in_t1 = ticker in top_t1_set
        in_t2 = ticker in top_t2_set
        if in_t1 and in_t2:
            entry['status'] = 'V'  # ✅
        elif in_t1:
            entry['status'] = 'P'  # ⏳
        else:
            entry['status'] = 'N'  # 🆕

        scored.append(entry)

    scored.sort(key=lambda x: x['weighted_rank'])
    return scored[:top_n]


def simulate_rank_strategy(all_data, dates, entry_rank, exit_rank, top_n):
    """
    순위 기반 전략 시뮬레이션

    진입: ✅ 검증 + weighted_rank ≤ entry_rank
    퇴출: weighted_rank > exit_rank (pipeline 밖 이탈 포함)
    """
    portfolio = set()
    daily_returns = []
    trade_count = 0

    for i in range(2, len(dates) - 1):
        d0, d1, d2 = dates[i], dates[i-1], dates[i-2]
        r0, r1, r2 = all_data[d0], all_data[d1], all_data[d2]
        next_date = dates[i + 1]

        pipeline = get_pipeline(r0, r1, r2, top_n)
        pipe_map = {s['ticker']: s for s in pipeline}
        pipe_tickers = set(pipe_map.keys())

        # 퇴출: pipeline 상위 exit_rank 밖
        top_exit = set(s['ticker'] for s in pipeline[:exit_rank])
        exits = set()
        for t in portfolio:
            if t not in top_exit:
                exits.add(t)

        # 진입: ✅ 검증 종목 중 상위 entry_rank개 + 미보유
        verified = [s for s in pipeline if s['status'] == 'V']
        entry_tickers = set(s['ticker'] for s in verified[:entry_rank])
        entries = entry_tickers - portfolio

        if exits or entries:
            trade_count += 1
        portfolio = (portfolio - exits) | entries

        # 수익률: d0 종가 → next_date 종가
        p0_map = {r['ticker']: r['price'] for r in r0.get('rankings', []) if r.get('price')}
        r_next = all_data.get(next_date)
        p1_map = {r['ticker']: r['price'] for r in r_next.get('rankings', []) if r.get('price')} if r_next else {}

        if portfolio:
            rets = []
            for t in portfolio:
                pp0 = p0_map.get(t)
                pp1 = p1_map.get(t)
                if pp0 and pp1 and pp0 > 0:
                    rets.append((pp1 - pp0) / pp0)
            daily_returns.append(sum(rets) / len(rets) if rets else 0.0)
        else:
            daily_returns.append(0.0)

    return compute_metrics(daily_returns, trade_count)


def simulate_score_strategy(all_data, dates, entry_score, exit_score, top_n):
    """현행 점수 기반 전략 시뮬레이션 (비교군)"""
    portfolio = set()
    daily_returns = []
    trade_count = 0

    for i in range(2, len(dates) - 1):
        d0, d1, d2 = dates[i], dates[i-1], dates[i-2]
        r0, r1, r2 = all_data[d0], all_data[d1], all_data[d2]
        next_date = dates[i + 1]

        pipeline = get_pipeline(r0, r1, r2, top_n)

        # 모든 pipeline 종목의 score_100 계산
        scores = {}
        for s in pipeline:
            scores[s['ticker']] = weighted_score_100(s['ticker'], r0, r1, r2)

        pipe_map = {s['ticker']: s for s in pipeline}

        # 퇴출: score < exit_score
        exits = set()
        for t in portfolio:
            sc = scores.get(t, 0)
            if sc < exit_score:
                exits.add(t)

        # 진입: ✅ + score ≥ entry_score
        entries = set()
        for s in pipeline:
            if s['status'] == 'V' and scores.get(s['ticker'], 0) >= entry_score and s['ticker'] not in portfolio:
                entries.add(s['ticker'])

        if exits or entries:
            trade_count += 1
        portfolio = (portfolio - exits) | entries

        p0_map = {r['ticker']: r['price'] for r in r0.get('rankings', []) if r.get('price')}
        r_next = all_data.get(next_date)
        p1_map = {r['ticker']: r['price'] for r in r_next.get('rankings', []) if r.get('price')} if r_next else {}

        if portfolio:
            rets = []
            for t in portfolio:
                pp0 = p0_map.get(t)
                pp1 = p1_map.get(t)
                if pp0 and pp1 and pp0 > 0:
                    rets.append((pp1 - pp0) / pp0)
            daily_returns.append(sum(rets) / len(rets) if rets else 0.0)
        else:
            daily_returns.append(0.0)

    return compute_metrics(daily_returns, trade_count)


def compute_metrics(daily_returns, trade_count):
    if not daily_returns:
        return None

    cumulative = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in daily_returns:
        cumulative *= (1 + r)
        if cumulative > peak:
            peak = cumulative
        dd = (peak - cumulative) / peak
        if dd > max_dd:
            max_dd = dd

    total_return = (cumulative - 1) * 100
    win_days = sum(1 for r in daily_returns if r > 0)
    total_days = len([r for r in daily_returns])

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
        'trades': trade_count,
        'win_rate': win_days / total_days * 100 if total_days > 0 else 0,
        'n_days': total_days,
        'avg_daily': statistics.mean(daily_returns) * 100 if daily_returns else 0,
    }


def main():
    import sys
    sys.stdout.reconfigure(encoding='utf-8')

    print("=" * 80)
    print("  진입/퇴출 순위 기반 그리드 서치 백테스트")
    print("=" * 80)

    all_data = load_all_rankings()
    dates = sorted(all_data.keys())
    print(f"데이터: {dates[0]} ~ {dates[-1]} ({len(dates)}거래일)")
    print(f"백테스트: {dates[3]} ~ {dates[-1]} ({len(dates)-3}거래일)")
    print()

    if len(dates) < 5:
        print("ERROR: 최소 5일 이상 데이터 필요")
        return

    # ══════════════════════════════════════════
    # 그리드 정의
    # ══════════════════════════════════════════
    entry_ranks = [3, 4, 5, 6, 7, 8, 10]
    exit_ranks = [10, 15, 20, 25, 30]
    top_ns = [20, 25, 30]

    # 현행 점수 기반 비교군
    score_configs = [
        (72, 68, 'score72/68'),
        (70, 65, 'score70/65'),
        (75, 70, 'score75/70'),
    ]

    total = len(entry_ranks) * len(exit_ranks) * len(top_ns) + len(score_configs) * len(top_ns)
    print(f"테스트 조합: {total}개")
    print(f"  순위 기반: entry({entry_ranks}) × exit({exit_ranks}) × top_n({top_ns})")
    print(f"  점수 기반: {[c[2] for c in score_configs]} × top_n({top_ns})")
    print()

    results = []
    count = 0

    # ── 순위 기반 전략 ──
    for top_n in top_ns:
        for entry_r in entry_ranks:
            for exit_r in exit_ranks:
                if entry_r > exit_r:
                    continue  # 진입 기준이 퇴출보다 넓으면 무의미
                count += 1
                result = simulate_rank_strategy(all_data, dates, entry_r, exit_r, top_n)
                if result:
                    results.append({
                        'type': 'rank',
                        'label': f"R entry≤{entry_r}/exit>{exit_r}/N{top_n}",
                        'entry': entry_r,
                        'exit': exit_r,
                        'top_n': top_n,
                        **result,
                    })
                if count % 30 == 0:
                    print(f"  {count}/{total} 완료...")

    # ── 점수 기반 전략 (비교군) ──
    for entry_s, exit_s, label in score_configs:
        for top_n in top_ns:
            count += 1
            result = simulate_score_strategy(all_data, dates, entry_s, exit_s, top_n)
            if result:
                results.append({
                    'type': 'score',
                    'label': f"S {label}/N{top_n}",
                    'entry': entry_s,
                    'exit': exit_s,
                    'top_n': top_n,
                    **result,
                })

    print(f"\n완료: {len(results)}개 유효 결과")

    # ══════════════════════════════════════════
    # 종합 순위 (Return rank + Sharpe rank + MDD rank)
    # ══════════════════════════════════════════
    ret_sorted = sorted(results, key=lambda x: -x['total_return'])
    sharpe_sorted = sorted(results, key=lambda x: -x['sharpe'])
    mdd_sorted = sorted(results, key=lambda x: x['mdd'])

    for r in results:
        r['ret_rank'] = ret_sorted.index(r) + 1
        r['sharpe_rank'] = sharpe_sorted.index(r) + 1
        r['mdd_rank'] = mdd_sorted.index(r) + 1
        r['composite'] = r['ret_rank'] + r['sharpe_rank'] + r['mdd_rank']

    by_composite = sorted(results, key=lambda x: x['composite'])

    # ── 종합 TOP 20 ──
    print()
    print("=" * 95)
    print("  COMPOSITE TOP 20 (Return + Sharpe + MDD 종합)")
    print("=" * 95)
    header = f"{'#':>3} {'전략':<30} {'수익률':>8} {'Sharpe':>8} {'MDD':>8} {'승률':>6} {'거래':>5} {'종합':>5}"
    print(header)
    print("-" * 95)
    for i, r in enumerate(by_composite[:20]):
        marker = " ◀현행" if r['label'].startswith('S score72/68') else ""
        print(f"{i+1:>3} {r['label']:<30} {r['total_return']:>+7.2f}% "
              f"{r['sharpe']:>8.2f} {r['mdd']:>7.2f}% "
              f"{r['win_rate']:>5.1f}% {r['trades']:>5} {r['composite']:>5}{marker}")

    # ── 수익률 TOP 15 ──
    print()
    print("=" * 95)
    print("  RETURN TOP 15")
    print("=" * 95)
    print(header)
    print("-" * 95)
    for i, r in enumerate(ret_sorted[:15]):
        marker = " ◀현행" if r['label'].startswith('S score72/68') else ""
        print(f"{i+1:>3} {r['label']:<30} {r['total_return']:>+7.2f}% "
              f"{r['sharpe']:>8.2f} {r['mdd']:>7.2f}% "
              f"{r['win_rate']:>5.1f}% {r['trades']:>5} {r['composite']:>5}{marker}")

    # ── Sharpe TOP 15 ──
    print()
    print("=" * 95)
    print("  SHARPE TOP 15")
    print("=" * 95)
    print(header)
    print("-" * 95)
    for i, r in enumerate(sharpe_sorted[:15]):
        marker = " ◀현행" if r['label'].startswith('S score72/68') else ""
        print(f"{i+1:>3} {r['label']:<30} {r['total_return']:>+7.2f}% "
              f"{r['sharpe']:>8.2f} {r['mdd']:>7.2f}% "
              f"{r['win_rate']:>5.1f}% {r['trades']:>5} {r['composite']:>5}{marker}")

    # ══════════════════════════════════════════
    # 파라미터별 민감도 분석 (순위 기반만)
    # ══════════════════════════════════════════
    rank_results = [r for r in results if r['type'] == 'rank']
    if rank_results:
        print()
        print("=" * 95)
        print("  파라미터 민감도 (순위 기반 전략)")
        print("=" * 95)

        for param, key, values in [
            ('Entry Rank (≤N)', 'entry', entry_ranks),
            ('Exit Rank (>N)', 'exit', exit_ranks),
            ('Pipeline Size', 'top_n', top_ns),
        ]:
            print(f"\n  {param}:")
            for val in values:
                subset = [r for r in rank_results if r[key] == val]
                if not subset:
                    continue
                avg_ret = statistics.mean([r['total_return'] for r in subset])
                avg_sharpe = statistics.mean([r['sharpe'] for r in subset])
                avg_mdd = statistics.mean([r['mdd'] for r in subset])
                best = min(subset, key=lambda x: x['composite'])
                print(f"    {val:>3}: 평균수익={avg_ret:>+7.2f}%  "
                      f"sharpe={avg_sharpe:>6.2f}  mdd={avg_mdd:>6.2f}%  "
                      f"(best: {best['label']})")

    # ══════════════════════════════════════════
    # 순위 vs 점수 비교
    # ══════════════════════════════════════════
    score_results = [r for r in results if r['type'] == 'score']
    print()
    print("=" * 95)
    print("  순위 기반 vs 점수 기반 비교")
    print("=" * 95)
    if rank_results:
        best_rank = min(rank_results, key=lambda x: x['composite'])
        print(f"  순위 BEST: {best_rank['label']}")
        print(f"    수익률={best_rank['total_return']:>+.2f}%  sharpe={best_rank['sharpe']:.2f}  "
              f"mdd={best_rank['mdd']:.2f}%  승률={best_rank['win_rate']:.1f}%")
    if score_results:
        best_score = min(score_results, key=lambda x: x['composite'])
        print(f"  점수 BEST: {best_score['label']}")
        print(f"    수익률={best_score['total_return']:>+.2f}%  sharpe={best_score['sharpe']:.2f}  "
              f"mdd={best_score['mdd']:.2f}%  승률={best_score['win_rate']:.1f}%")

    # 현행 전략 위치
    current = next((r for r in results if r['label'].startswith('S score72/68/N20')), None)
    if current:
        print(f"\n  현행(score72/68/N20): 종합 {current['composite']}위/{len(results)}개")
        print(f"    수익률={current['total_return']:>+.2f}%  sharpe={current['sharpe']:.2f}  "
              f"mdd={current['mdd']:.2f}%  승률={current['win_rate']:.1f}%")

    print()
    print(f"* 주의: {len(dates)}거래일은 통계적 유의성에 부족합니다.")
    print("* 데이터가 축적될수록 결과 신뢰도가 높아집니다.")


if __name__ == '__main__':
    main()
