"""
v68 진입/퇴출 EDA — 재계산 데이터 기반 분석

분석 항목:
1. 점수 분포 (score_100) — 24일간 통계
2. 순위 안정성 — Top 5/10/20 연속 유지 일수, 턴오버
3. 진입/퇴출 시뮬레이션 — 순위/점수 기반 다양한 threshold
4. 간이 백테스트 — 조합별 상대 비교 (Sharpe, MDD, 턴오버)
"""
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import numpy as np
import pandas as pd
from pathlib import Path
from collections import Counter, defaultdict

STATE_DIR = Path(__file__).parent / 'state'


def load_all_rankings():
    """모든 ranking JSON 로드 → {date: data}"""
    files = sorted(STATE_DIR.glob('ranking_*.json'))
    all_data = {}
    for f in files:
        date = f.stem.split('_')[1]
        with open(f, 'r', encoding='utf-8') as fp:
            all_data[date] = json.load(fp)
    return all_data


def weighted_score_100(ticker, r_t0, r_t1=None, r_t2=None):
    """원본 멀티팩터 점수 가중(T0×0.5+T1×0.3+T2×0.2) → 100점 환산"""
    DEFAULT_RANK = 50

    def _build_maps(rankings):
        if not rankings:
            return {}, 0
        rlist = rankings.get('rankings', [])
        ticker_map = {r['ticker']: r['score'] for r in rlist}
        rank_map = {r.get('composite_rank', r['rank']): r['score'] for r in rlist}
        fallback = rank_map.get(DEFAULT_RANK, 0)
        return ticker_map, fallback

    t0_map, _ = _build_maps(r_t0)
    t1_map, t1_fb = _build_maps(r_t1)
    t2_map, t2_fb = _build_maps(r_t2)

    s0 = t0_map.get(ticker, 0)
    s1 = t1_map.get(ticker, t1_fb)
    s2 = t2_map.get(ticker, t2_fb)
    ws = s0 * 0.5 + s1 * 0.3 + s2 * 0.2
    return max(0.0, min(100.0, (ws + 3.0) / 6.0 * 100))


def analyze_score_distribution(all_data):
    """1. 점수 분포 분석"""
    print("\n" + "=" * 70)
    print("1. SCORE_100 분포 분석")
    print("=" * 70)

    dates = sorted(all_data.keys())

    # 날짜별 Top 20의 score_100 통계
    print(f"\n{'날짜':>10} {'scored':>6} {'평균':>7} {'중위':>7} {'최소':>7} {'최대':>7} {'≥72점':>5} {'≥68점':>5}")
    print("-" * 70)

    all_scores_top20 = []
    for i, d in enumerate(dates):
        rankings = all_data[d]['rankings']
        # 과거 2일 데이터 가져오기
        t1 = all_data.get(dates[i-1]) if i >= 1 else None
        t2 = all_data.get(dates[i-2]) if i >= 2 else None

        scores = []
        for r in rankings[:20]:
            s = weighted_score_100(r['ticker'], all_data[d], t1, t2)
            scores.append(s)

        scores = np.array(scores)
        all_scores_top20.extend(scores)
        ge72 = (scores >= 72).sum()
        ge68 = (scores >= 68).sum()
        print(f"{d:>10} {len(rankings):>6} {scores.mean():>7.1f} {np.median(scores):>7.1f} "
              f"{scores.min():>7.1f} {scores.max():>7.1f} {ge72:>5} {ge68:>5}")

    all_scores_top20 = np.array(all_scores_top20)
    print(f"\n{'전체 평균':>10} {'':>6} {all_scores_top20.mean():>7.1f} {np.median(all_scores_top20):>7.1f} "
          f"{all_scores_top20.min():>7.1f} {all_scores_top20.max():>7.1f}")

    # 적정 threshold 후보
    print("\n--- threshold별 Top 20 진입 종목 수 (평균) ---")
    for threshold in [65, 68, 70, 72, 75, 78, 80]:
        counts = []
        for i, d in enumerate(dates):
            rankings = all_data[d]['rankings']
            t1 = all_data.get(dates[i-1]) if i >= 1 else None
            t2 = all_data.get(dates[i-2]) if i >= 2 else None
            cnt = sum(1 for r in rankings[:20]
                      if weighted_score_100(r['ticker'], all_data[d], t1, t2) >= threshold)
            counts.append(cnt)
        print(f"  score_100 ≥ {threshold}: 평균 {np.mean(counts):.1f}개, "
              f"최소 {min(counts)}, 최대 {max(counts)}")


def analyze_rank_stability(all_data):
    """2. 순위 안정성 분석"""
    print("\n" + "=" * 70)
    print("2. 순위 안정성 분석")
    print("=" * 70)

    dates = sorted(all_data.keys())

    # Top N 일일 턴오버
    print(f"\n{'기준':>10} {'평균턴오버':>10} {'최소':>6} {'최대':>6} {'평균교체':>8}")
    print("-" * 50)
    for top_n in [5, 10, 15, 20]:
        turnovers = []
        for i in range(1, len(dates)):
            prev_tickers = set(r['ticker'] for r in all_data[dates[i-1]]['rankings'][:top_n])
            curr_tickers = set(r['ticker'] for r in all_data[dates[i]]['rankings'][:top_n])
            exited = len(prev_tickers - curr_tickers)
            turnover = exited / top_n * 100
            turnovers.append(turnover)
        avg_chg = np.mean(turnovers) * top_n / 100
        print(f"Top {top_n:>3}    {np.mean(turnovers):>8.1f}% {min(turnovers):>5.0f}% "
              f"{max(turnovers):>5.0f}% {avg_chg:>7.1f}개/일")

    # Top 5 종목 연속 유지 일수
    print("\n--- Top 5 종목별 연속 유지 일수 ---")
    streak_data = defaultdict(list)
    for ticker_set_dates in []:
        pass

    # 모든 날짜에서 Top 5였던 종목 + 연속 일수
    all_top5 = set()
    for d in dates:
        for r in all_data[d]['rankings'][:5]:
            all_top5.add(r['ticker'])

    for ticker in all_top5:
        streaks = []
        current_streak = 0
        name = ''
        for d in dates:
            top5_tickers = [r['ticker'] for r in all_data[d]['rankings'][:5]]
            if ticker in top5_tickers:
                current_streak += 1
                name = next(r['name'] for r in all_data[d]['rankings'] if r['ticker'] == ticker)
            else:
                if current_streak > 0:
                    streaks.append(current_streak)
                current_streak = 0
        if current_streak > 0:
            streaks.append(current_streak)
        if streaks:
            streak_data[ticker] = (name, max(streaks), sum(streaks))

    sorted_streaks = sorted(streak_data.items(), key=lambda x: x[1][2], reverse=True)
    for ticker, (name, max_s, total) in sorted_streaks[:15]:
        print(f"  {name:12s} ({ticker}): 최대 {max_s}일 연속, 총 {total}일")


def simulate_entry_exit(all_data):
    """3. 진입/퇴출 시뮬레이션"""
    print("\n" + "=" * 70)
    print("3. 진입/퇴출 시뮬레이션 (순위 기반)")
    print("=" * 70)

    dates = sorted(all_data.keys())

    print(f"\n{'ENTRY':>7} {'EXIT':>5} {'평균보유':>8} {'평균턴오버':>10} {'총교체':>6} {'현금일':>6}")
    print("-" * 55)

    for entry_rank in [3, 5, 7]:
        for exit_rank in [10, 15, 20, 25]:
            if exit_rank <= entry_rank:
                continue

            portfolio = set()
            total_turnover = 0
            holding_counts = []
            cash_days = 0

            for i, d in enumerate(dates):
                rankings = all_data[d]['rankings']
                # 현재 Top N
                top_n_tickers = set(r['ticker'] for r in rankings[:20])
                rank_map = {r['ticker']: r.get('composite_rank', r['rank']) for r in rankings}

                # 퇴출: 현재 포트폴리오 중 exit_rank 밖
                exits = set()
                for t in portfolio:
                    if rank_map.get(t, 999) > exit_rank:
                        exits.add(t)
                portfolio -= exits

                # 3일 검증 체크 (간이: 3일 연속 Top 20에 있었는지)
                if i >= 2:
                    t1_top20 = set(r['ticker'] for r in all_data[dates[i-1]]['rankings'][:20])
                    t2_top20 = set(r['ticker'] for r in all_data[dates[i-2]]['rankings'][:20])
                    verified = top_n_tickers & t1_top20 & t2_top20
                else:
                    verified = set()

                # 진입: 검증된 종목 중 상위 entry_rank개
                verified_ranked = sorted(
                    [r for r in rankings if r['ticker'] in verified],
                    key=lambda x: x.get('composite_rank', x['rank'])
                )
                candidates = [r['ticker'] for r in verified_ranked[:entry_rank]]

                entries = set(candidates) - portfolio
                portfolio |= entries

                total_turnover += len(exits) + len(entries)
                holding_counts.append(len(portfolio))
                if len(portfolio) == 0:
                    cash_days += 1

            avg_holding = np.mean(holding_counts)
            avg_turnover = total_turnover / len(dates)
            print(f"E≤{entry_rank:>2}/X>{exit_rank:<3} {avg_holding:>7.1f}개 "
                  f"{avg_turnover:>9.1f}개/일 {total_turnover:>5}회 {cash_days:>5}일")


def simple_backtest(all_data):
    """4. 간이 백테스트 — 순위 기반 조합별 비교"""
    print("\n" + "=" * 70)
    print("4. 간이 백테스트 (순위 기반, 동일 비중)")
    print("=" * 70)

    dates = sorted(all_data.keys())

    # 날짜별 종목 수익률 맵 (T일 종가 → T+1일 종가)
    daily_returns = {}
    for i in range(len(dates) - 1):
        d0, d1 = dates[i], dates[i+1]
        r0_map = {r['ticker']: r.get('price', 0) for r in all_data[d0]['rankings']}
        r1_map = {r['ticker']: r.get('price', 0) for r in all_data[d1]['rankings']}

        rets = {}
        for ticker in r0_map:
            p0, p1 = r0_map[ticker], r1_map.get(ticker, 0)
            if p0 and p1 and p0 > 0:
                rets[ticker] = (p1 / p0 - 1)
        daily_returns[d0] = rets

    print(f"\n{'전략':>15} {'총수익%':>8} {'MDD%':>7} {'Sharpe':>7} {'평균보유':>8} {'턴오버':>7}")
    print("-" * 60)

    results = []
    for entry_rank in [3, 5, 7]:
        for exit_rank in [10, 15, 20]:
            if exit_rank <= entry_rank:
                continue

            portfolio = set()
            nav = [1.0]
            total_turnover = 0

            for i, d in enumerate(dates[:-1]):
                rankings = all_data[d]['rankings']
                rank_map = {r['ticker']: r.get('composite_rank', r['rank']) for r in rankings}

                # 퇴출
                exits = {t for t in portfolio if rank_map.get(t, 999) > exit_rank}
                portfolio -= exits

                # 3일 검증 진입
                top20 = set(r['ticker'] for r in rankings[:20])
                if i >= 2:
                    t1_top20 = set(r['ticker'] for r in all_data[dates[i-1]]['rankings'][:20])
                    t2_top20 = set(r['ticker'] for r in all_data[dates[i-2]]['rankings'][:20])
                    verified = top20 & t1_top20 & t2_top20
                else:
                    verified = set()

                candidates = sorted(
                    [r for r in rankings if r['ticker'] in verified],
                    key=lambda x: x.get('composite_rank', x['rank'])
                )[:entry_rank]
                entries = set(r['ticker'] for r in candidates) - portfolio
                portfolio |= entries
                total_turnover += len(exits) + len(entries)

                # 일일 수익률 계산
                if portfolio:
                    rets = daily_returns.get(d, {})
                    port_ret = np.mean([rets.get(t, 0) for t in portfolio])
                else:
                    port_ret = 0

                nav.append(nav[-1] * (1 + port_ret))

            nav = np.array(nav)
            total_ret = (nav[-1] / nav[0] - 1) * 100
            peak = np.maximum.accumulate(nav)
            dd = (nav - peak) / peak
            mdd = dd.min() * 100
            daily_rets = np.diff(nav) / nav[:-1]
            sharpe = (daily_rets.mean() / daily_rets.std() * np.sqrt(252)) if daily_rets.std() > 0 else 0
            avg_turnover = total_turnover / len(dates)

            label = f"E≤{entry_rank}/X>{exit_rank}"
            print(f"{label:>15} {total_ret:>7.1f}% {mdd:>6.1f}% {sharpe:>6.3f} "
                  f"{'':>8} {avg_turnover:>6.1f}")
            results.append((label, total_ret, mdd, sharpe, avg_turnover))

    # Sharpe 상위 3개
    results.sort(key=lambda x: x[3], reverse=True)
    print(f"\nSharpe 상위 3:")
    for label, ret, mdd, sharpe, to in results[:3]:
        print(f"  {label}: Sharpe={sharpe:.3f}, 수익={ret:.1f}%, MDD={mdd:.1f}%")


def sector_distribution(all_data):
    """5. Top 20 섹터 분포 변화"""
    print("\n" + "=" * 70)
    print("5. Top 20 섹터 분포 (날짜별)")
    print("=" * 70)

    dates = sorted(all_data.keys())
    sector_timeline = {}

    for d in dates:
        sectors = Counter(r.get('sector', '기타') for r in all_data[d]['rankings'][:20])
        sector_timeline[d] = sectors

    # 가장 빈번한 섹터 상위 5개
    all_sectors = Counter()
    for d in dates:
        all_sectors.update(sector_timeline[d])

    top_sectors = [s for s, _ in all_sectors.most_common(6)]

    print(f"\n{'날짜':>10}", end='')
    for s in top_sectors:
        print(f" {s[:4]:>5}", end='')
    print()
    print("-" * (10 + 6 * len(top_sectors)))

    for d in dates:
        print(f"{d:>10}", end='')
        for s in top_sectors:
            cnt = sector_timeline[d].get(s, 0)
            print(f" {cnt:>5}", end='')
        print()


def main():
    print("v68 진입/퇴출 EDA")
    print("=" * 70)

    all_data = load_all_rankings()
    dates = sorted(all_data.keys())
    print(f"로드된 날짜: {len(dates)}개 ({dates[0]} ~ {dates[-1]})")

    # v68 여부 확인 (growth_s 필드 없으면 v68)
    latest = all_data[dates[-1]]
    has_growth = any('growth_s' in r for r in latest['rankings'])
    print(f"v68 확인: growth_s {'있음 (v66!)' if has_growth else '없음 (v68 OK)'}")

    analyze_score_distribution(all_data)
    analyze_rank_stability(all_data)
    simulate_entry_exit(all_data)
    simple_backtest(all_data)
    sector_distribution(all_data)

    print("\n" + "=" * 70)
    print("EDA 완료")
    print("=" * 70)


if __name__ == '__main__':
    main()
