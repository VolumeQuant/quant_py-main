"""
백테스트: v61 점수 기반 진입/퇴출 전략
- Entry: weighted_score_100 >= 72
- Exit: weighted_score_100 < 68
- 3일 가중점수: T0×0.5 + T1×0.3 + T2×0.2
- 동일비중, 다음날 종가 리밸런싱
"""

import json
from pathlib import Path
from pykrx import stock as pykrx_stock
import pandas as pd
from datetime import datetime

STATE_DIR = Path(__file__).parent / 'state'
ENTRY_SCORE = 72
EXIT_SCORE = 68
DEFAULT_MISSING_RANK = 50


def load_ranking(date_str):
    path = STATE_DIR / f'ranking_{date_str}.json'
    if not path.exists():
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def weighted_score_100(ticker, r_t0, r_t1=None, r_t2=None):
    """ranking_manager.py와 동일 로직"""
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


def get_all_dates():
    files = sorted(STATE_DIR.glob('ranking_*.json'))
    return [f.stem.replace('ranking_', '') for f in files]


def get_price_map(ranking_data):
    """ranking JSON에서 {ticker: price} 추출"""
    return {r['ticker']: r['price'] for r in ranking_data.get('rankings', []) if r.get('price')}


def main():
    dates = get_all_dates()
    print(f"전체 랭킹 데이터: {dates[0]} ~ {dates[-1]} ({len(dates)}일)")
    print(f"진입 기준: score_100 >= {ENTRY_SCORE}")
    print(f"퇴출 기준: score_100 < {EXIT_SCORE}")
    print("=" * 70)

    # 최소 3일 필요
    if len(dates) < 3:
        print("ERROR: 3일 이상 데이터 필요")
        return

    # 전체 랭킹 로드
    all_rankings = {}
    for d in dates:
        all_rankings[d] = load_ranking(d)

    # ── 시그널 생성 (3일째부터) ──
    # signal_date: 시그널 발생일, exec_date: 다음 거래일(실행일)
    signals = []  # [(signal_date, picks_set)]

    for i in range(2, len(dates)):
        d0, d1, d2 = dates[i], dates[i-1], dates[i-2]
        r0, r1, r2 = all_rankings[d0], all_rankings[d1], all_rankings[d2]

        # 모든 종목 score 계산
        all_tickers = set(r['ticker'] for r in r0.get('rankings', []))
        scored = {}
        for t in all_tickers:
            scored[t] = weighted_score_100(t, r0, r1, r2)

        signals.append((d0, scored))

    # ── 포트폴리오 시뮬레이션 ──
    portfolio = set()  # 현재 보유 종목
    daily_returns = []  # (date, return, n_stocks, holdings_info)
    trade_log = []

    for sig_idx in range(len(signals)):
        signal_date = signals[sig_idx][0]
        scores = signals[sig_idx][1]

        # 현재 보유 종목 중 exit 조건 체크
        exits = set()
        for t in portfolio:
            sc = scores.get(t, 0)
            if sc < EXIT_SCORE:
                exits.add(t)

        # 신규 진입 (entry 조건)
        entries = set()
        for t, sc in scores.items():
            if t not in portfolio and sc >= ENTRY_SCORE:
                entries.add(t)

        # 포트폴리오 업데이트
        portfolio = (portfolio - exits) | entries

        if exits:
            trade_log.append(f"[{signal_date}] EXIT: {exits}")
        if entries:
            trade_log.append(f"[{signal_date}] ENTRY: {entries}")

        # 수익률 계산: signal_date의 가격 → 다음 거래일의 가격
        if sig_idx + 1 < len(signals):
            next_date = signals[sig_idx + 1][0]
        elif signal_date != dates[-1]:
            next_date = dates[-1]
        else:
            # 마지막 날 — 수익률 계산 불가
            continue

        # 가격 데이터
        price_today = get_price_map(all_rankings[signal_date])
        price_next = get_price_map(all_rankings[next_date]) if next_date in all_rankings else {}

        if not portfolio:
            daily_returns.append((signal_date, next_date, 0.0, 0, []))
            continue

        # 동일비중 수익률
        returns_list = []
        holdings_detail = []
        for t in portfolio:
            p0 = price_today.get(t)
            p1 = price_next.get(t)
            if p0 and p1 and p0 > 0:
                ret = (p1 - p0) / p0
                returns_list.append(ret)
                # 종목명 찾기
                name = t
                for r in all_rankings[signal_date]['rankings']:
                    if r['ticker'] == t:
                        name = r['name']
                        break
                holdings_detail.append((name, t, scores.get(t, 0), ret))

        if returns_list:
            avg_ret = sum(returns_list) / len(returns_list)
        else:
            avg_ret = 0.0

        daily_returns.append((signal_date, next_date, avg_ret, len(portfolio), holdings_detail))

    # ── 결과 출력 ──
    print("\n📊 일별 포트폴리오 수익률")
    print("-" * 70)

    cum_ret = 1.0
    for (sig_d, next_d, ret, n, details) in daily_returns:
        cum_ret *= (1 + ret)
        print(f"  {sig_d}→{next_d}  보유 {n:2d}종목  일수익 {ret:+.2%}  누적 {cum_ret-1:+.2%}")
        if details:
            # 상위 기여/손실 표시
            details.sort(key=lambda x: x[3], reverse=True)
            top = details[:3]
            bottom = details[-2:] if len(details) > 3 else []
            top_str = ", ".join(f"{d[0]}({d[3]:+.1%})" for d in top)
            print(f"           ↳ Top: {top_str}")

    total_ret = cum_ret - 1
    n_periods = len([d for d in daily_returns if d[3] > 0])
    win_periods = len([d for d in daily_returns if d[2] > 0])

    print("\n" + "=" * 70)
    print(f"📈 전략 누적수익률: {total_ret:+.2%}")
    print(f"   기간: {daily_returns[0][0]} → {daily_returns[-1][1]}")
    print(f"   거래일: {len(daily_returns)}일")
    print(f"   승률: {win_periods}/{n_periods} ({win_periods/n_periods*100:.0f}%)" if n_periods > 0 else "")

    # ── 매매 로그 ──
    print("\n📋 매매 로그")
    print("-" * 70)
    for log in trade_log:
        print(f"  {log}")

    # ── KOSPI / KOSDAQ 비교 ──
    print("\n" + "=" * 70)
    print("📊 벤치마크 비교 (같은 기간)")
    print("-" * 70)

    start_date = daily_returns[0][0]
    end_date = daily_returns[-1][1]

    try:
        # KODEX 200 (069500) → KOSPI 대용, KODEX 코스닥150 (229200) → KOSDAQ 대용
        benchmarks = [
            ("KOSPI (KODEX200)", "069500"),
            ("KOSDAQ (KODEX코스닥150)", "229200"),
        ]
        bench_rets = {}
        for name, ticker in benchmarks:
            df = pykrx_stock.get_market_ohlcv_by_date(start_date, end_date, ticker)
            if len(df) >= 2:
                ret = (df['종가'].iloc[-1] / df['종가'].iloc[0]) - 1
                bench_rets[name] = ret
                print(f"  {name}: {df['종가'].iloc[0]:,.0f} → {df['종가'].iloc[-1]:,.0f}  ({ret:+.2%})")
            else:
                print(f"  {name}: 데이터 부족")

        # 초과수익률
        for name, ret in bench_rets.items():
            print(f"\n  ⚡ 전략 vs {name} 초과수익: {total_ret - ret:+.2%}")

    except Exception as e:
        print(f"  벤치마크 조회 실패: {e}")


if __name__ == '__main__':
    main()
