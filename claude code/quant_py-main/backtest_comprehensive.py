"""
종합 백테스트 — 진입/퇴출 기준 최적화
v1.0 (2026-03-19)

전략 유형:
  A. Score-based: score_100 >= entry_thr 진입 / < exit_thr 퇴출
  B. Rank-based:  weighted_rank <= top_n 진입 / > top_n 퇴출
  C. Hybrid:      score 진입 + rank 퇴출, 또는 rank 진입 + score 퇴출

핵심 규칙:
  - 3일 교집합(Slow In): T-0, T-1, T-2 모두 top_pool_n 이내여야 후보 자격
  - 시그널은 장 마감 후 → 다음 날 가격으로 거래
  - 동일 비중 포트폴리오
  - 일일 리밸런싱
"""

import json
import os
import glob
import math
import itertools
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ── 설정 ─────────────────────────────────────────────────────────────────────
STATE_DIR = Path("C:/dev/claude-code/quant_py-main/claude code/quant_py-main/state")
OUTPUT_DIR = Path("C:/dev/claude-code/quant_py-main/claude code/quant_py-main")
RISK_FREE_RATE = 0.035  # 연 3.5% (한국 무위험수익률 근사)

# 3일 교집합 풀 크기 (Slow In 기준)
SLOW_IN_POOL_N = 20  # 상위 20개 중 3일 연속 포함돼야 후보 자격

# ── 데이터 로딩 ───────────────────────────────────────────────────────────────

def load_all_rankings() -> List[Dict]:
    """모든 ranking JSON 로드 (날짜 오름차순)"""
    files = sorted(glob.glob(str(STATE_DIR / "ranking_*.json")))
    results = []
    for f in files:
        date_str = Path(f).stem.replace("ranking_", "")
        if len(date_str) == 8 and date_str.isdigit():
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            data["_date"] = date_str
            results.append(data)
    return results


def build_ticker_map(ranking_data: Dict) -> Dict[str, Dict]:
    """ticker → item 맵"""
    return {r["ticker"]: r for r in ranking_data.get("rankings", [])}


def get_composite_rank(item: Dict) -> float:
    """composite_rank 우선, 없으면 rank"""
    return item.get("composite_rank", item.get("rank", 9999))


def compute_weighted_score_100(ticker: str, t0: Dict, t1: Optional[Dict], t2: Optional[Dict]) -> float:
    """
    weighted_score_100 계산 — ranking_manager.py 의 로직과 동일
    ws = s0*0.5 + s1*0.3 + s2*0.2
    score_100 = max(0, min(100, (ws + 3.0) / 6.0 * 100))
    """
    DEFAULT_MISSING_RANK = 50

    def get_score(rankings, fallback_score=0.0):
        if not rankings:
            return fallback_score
        rlist = rankings.get("rankings", [])
        ticker_map = {r["ticker"]: r["score"] for r in rlist}
        rank_map = {r.get("composite_rank", r["rank"]): r["score"] for r in rlist}
        fallback = rank_map.get(DEFAULT_MISSING_RANK, fallback_score)
        return ticker_map.get(ticker, fallback)

    s0 = get_score(t0)
    s1 = get_score(t1) if t1 else 0.0
    s2 = get_score(t2) if t2 else 0.0

    if t1 and t2:
        ws = s0 * 0.5 + s1 * 0.3 + s2 * 0.2
    elif t1:
        ws = s0 * 0.6 + s1 * 0.4
    else:
        ws = s0

    return max(0.0, min(100.0, (ws + 3.0) / 6.0 * 100))


def compute_weighted_rank(ticker: str, t0: Dict, t1: Optional[Dict], t2: Optional[Dict]) -> float:
    """
    가중순위 계산 — ranking_manager.py get_stock_status() 와 동일
    weighted = rank_t0*0.5 + rank_t1*0.3 + rank_t2*0.2
    """
    DEFAULT = 50

    def get_rank(rankings, tk):
        if not rankings:
            return DEFAULT
        rlist = rankings.get("rankings", [])
        for r in rlist:
            if r["ticker"] == tk:
                return get_composite_rank(r)
        return DEFAULT

    r0 = get_rank(t0, ticker)
    r1 = get_rank(t1, ticker) if t1 else DEFAULT
    r2 = get_rank(t2, ticker) if t2 else DEFAULT

    if t1 and t2:
        return r0 * 0.5 + r1 * 0.3 + r2 * 0.2
    elif t1:
        return r0 * 0.6 + r1 * 0.4
    else:
        return float(r0)


def get_slow_in_candidates(t0: Dict, t1: Optional[Dict], t2: Optional[Dict], pool_n: int = 20) -> List[str]:
    """
    3일 교집합(Slow In) 후보 반환
    t0, t1, t2 각각 composite_rank <= pool_n 인 종목들의 교집합
    """
    def top_set(rankings, n):
        if not rankings:
            return set()
        return {r["ticker"] for r in rankings.get("rankings", [])
                if get_composite_rank(r) <= n}

    s0 = top_set(t0, pool_n)
    s1 = top_set(t1, pool_n) if t1 else set()
    s2 = top_set(t2, pool_n) if t2 else set()

    if t1 and t2:
        return list(s0 & s1 & s2)
    elif t1:
        return list(s0 & s1)
    else:
        return list(s0)


# ── 포트폴리오 시뮬레이터 ─────────────────────────────────────────────────────

def simulate_portfolio(
    all_rankings: List[Dict],
    strategy_type: str,         # "score", "rank", "hybrid_se", "hybrid_re"
    entry_param: float,         # score threshold OR rank top_n (entry)
    exit_param: float,          # score threshold OR rank top_n (exit)
    pool_n: int = 20,           # Slow In 풀 크기
    max_holdings: int = 999,    # 최대 보유 종목 수 제한
) -> Dict:
    """
    포트폴리오 시뮬레이션.

    strategy_type:
      "score"     : score_100 >= entry_param 진입, < exit_param 퇴출
      "rank"      : weighted_rank <= entry_param 진입, > exit_param 퇴출
      "hybrid_se" : score 진입 + rank 퇴출 (score entry, rank exit)
      "hybrid_re" : rank 진입 + score 퇴출 (rank entry, score exit)

    Returns:
      dict with performance metrics
    """
    n = len(all_rankings)
    if n < 4:
        return {"error": "데이터 부족"}

    # 포트폴리오 상태
    holdings = set()  # 현재 보유 종목
    portfolio_value = 1_000_000.0  # 초기 자산 100만원 (비율 계산이므로 크기 무관)
    daily_returns = []
    daily_holdings_count = []
    turnover_list = []

    # 첫 3일은 Slow In 워밍업 기간 — 시그널 생성은 day_idx=2부터
    # 실제 거래는 day_idx=3(다음날 가격)부터

    # 가격 맵: {date: {ticker: price}}
    price_map = {}
    for rd in all_rankings:
        d = rd["_date"]
        price_map[d] = {r["ticker"]: r["price"] for r in rd.get("rankings", []) if r.get("price")}

    dates = [rd["_date"] for rd in all_rankings]

    # signal_dates[i] = i번째 날 장마감 후 생성한 시그널 → i+1 날 거래
    # 시그널을 day=2(세 번째 날)부터 생성 (t0=2, t1=1, t2=0)

    equity_curve = [portfolio_value]
    prev_holdings = set()

    for sig_idx in range(2, n):  # 시그널 생성일 인덱스
        t0 = all_rankings[sig_idx]
        t1 = all_rankings[sig_idx - 1]
        t2 = all_rankings[sig_idx - 2]

        t0_map = build_ticker_map(t0)
        t1_map = build_ticker_map(t1)
        t2_map = build_ticker_map(t2)

        # 3일 교집합 후보
        candidates = get_slow_in_candidates(t0, t1, t2, pool_n)

        # 각 후보의 점수/순위 계산
        candidate_metrics = {}
        for tk in candidates:
            score = compute_weighted_score_100(tk, t0, t1, t2)
            wr = compute_weighted_rank(tk, t0, t1, t2)
            candidate_metrics[tk] = {"score": score, "weighted_rank": wr}

        # 현재 보유 종목의 점수/순위 (퇴출 판단)
        # 보유 종목은 3일 교집합 요건 면제 — 점수/순위로만 퇴출
        held_metrics = {}
        for tk in prev_holdings:
            if tk in t0_map:
                score = compute_weighted_score_100(tk, t0, t1, t2)
                wr = compute_weighted_rank(tk, t0, t1, t2)
                held_metrics[tk] = {"score": score, "weighted_rank": wr}
            else:
                # 유니버스 이탈 → 강제 퇴출 (점수 0, 순위 999)
                held_metrics[tk] = {"score": 0.0, "weighted_rank": 999.0}

        # 새 포트폴리오 계산
        new_holdings = set()

        # 1. 기존 보유 종목 중 퇴출 조건 미충족 → 유지
        for tk, m in held_metrics.items():
            keep = False
            if strategy_type == "score":
                keep = m["score"] >= exit_param
            elif strategy_type == "rank":
                keep = m["weighted_rank"] <= exit_param
            elif strategy_type == "hybrid_se":
                # score 진입, rank 퇴출
                keep = m["weighted_rank"] <= exit_param
            elif strategy_type == "hybrid_re":
                # rank 진입, score 퇴출
                keep = m["score"] >= exit_param
            if keep:
                new_holdings.add(tk)

        # 2. 후보 중 진입 조건 충족 → 추가
        for tk, m in candidate_metrics.items():
            enter = False
            if strategy_type == "score":
                enter = m["score"] >= entry_param
            elif strategy_type == "rank":
                enter = m["weighted_rank"] <= entry_param
            elif strategy_type == "hybrid_se":
                enter = m["score"] >= entry_param
            elif strategy_type == "hybrid_re":
                enter = m["weighted_rank"] <= entry_param
            if enter:
                new_holdings.add(tk)

        # 최대 보유 수 제한 (있을 경우)
        if len(new_holdings) > max_holdings:
            # score 높은 순으로 제한
            all_scored = []
            for tk in new_holdings:
                m = candidate_metrics.get(tk) or held_metrics.get(tk, {"score": 0.0, "weighted_rank": 999.0})
                all_scored.append((tk, m["score"]))
            all_scored.sort(key=lambda x: -x[1])
            new_holdings = {tk for tk, _ in all_scored[:max_holdings]}

        # 다음 날 가격으로 수익률 계산
        trade_idx = sig_idx + 1
        if trade_idx >= n:
            break

        trade_date = dates[trade_idx]
        prices_trade = price_map.get(trade_date, {})

        # 시그널 날 가격 (보유 기준가)
        sig_date = dates[sig_idx]
        prices_sig = price_map.get(sig_date, {})

        # 포트폴리오 수익률: 다음날 매매 기준
        # 기존 보유 종목: 오늘 종가 → 내일 종가 수익률
        # 신규 진입: 내일 시가 ≈ 내일 종가(단순화)
        # 퇴출: 내일 종가로 청산

        if not new_holdings:
            # 현금 보유 — 수익률 0
            daily_returns.append(0.0)
            daily_holdings_count.append(0)
        else:
            # 동일 비중 포트폴리오
            # 각 종목: 시그널날 종가 → 다음날 종가 수익률
            # (시그널 후 다음날 매수/매도 가정 — 가격 데이터가 종가만 있으므로)
            stock_returns = []
            for tk in new_holdings:
                p_sig = prices_sig.get(tk)
                p_trade = prices_trade.get(tk)
                if p_sig and p_trade and p_sig > 0:
                    r = (p_trade - p_sig) / p_sig
                    stock_returns.append(r)
                else:
                    stock_returns.append(0.0)  # 가격 없으면 0
            port_return = sum(stock_returns) / len(stock_returns) if stock_returns else 0.0
            daily_returns.append(port_return)
            daily_holdings_count.append(len(new_holdings))

        # 턴오버 계산
        added = new_holdings - prev_holdings
        removed = prev_holdings - new_holdings
        total_unique = len(new_holdings | prev_holdings)
        turnover = (len(added) + len(removed)) / max(total_unique * 2, 1)
        turnover_list.append(turnover)

        # 자산 업데이트
        portfolio_value *= (1 + daily_returns[-1])
        equity_curve.append(portfolio_value)
        prev_holdings = new_holdings

    if not daily_returns:
        return {"error": "수익률 데이터 없음"}

    # ── 성과 지표 계산 ─────────────────────────────────────────────────────
    returns = daily_returns
    n_days = len(returns)

    # 총 수익률
    total_return = (portfolio_value / 1_000_000.0) - 1.0

    # 연환산 수익률 (거래일 기준 252일)
    if n_days > 0:
        annualized_return = (1 + total_return) ** (252 / n_days) - 1
    else:
        annualized_return = 0.0

    # 최대 낙폭 (MDD)
    peak = equity_curve[0]
    max_dd = 0.0
    for v in equity_curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak
        if dd > max_dd:
            max_dd = dd

    # 샤프 지수 (일간 → 연환산)
    if n_days > 1:
        mean_r = sum(returns) / n_days
        var_r = sum((r - mean_r) ** 2 for r in returns) / (n_days - 1)
        std_r = math.sqrt(var_r) if var_r > 0 else 0.0
        rf_daily = (1 + RISK_FREE_RATE) ** (1 / 252) - 1
        if std_r > 0:
            sharpe = (mean_r - rf_daily) / std_r * math.sqrt(252)
        else:
            sharpe = 0.0
    else:
        sharpe = 0.0

    # 평균 보유 종목 수
    avg_holdings = sum(daily_holdings_count) / len(daily_holdings_count) if daily_holdings_count else 0

    # 평균 턴오버
    avg_turnover = sum(turnover_list) / len(turnover_list) if turnover_list else 0

    # 현금 보유일 수 (보유 0개인 날)
    cash_days = sum(1 for c in daily_holdings_count if c == 0)

    return {
        "total_return": round(total_return * 100, 2),          # %
        "annualized_return": round(annualized_return * 100, 2), # %
        "mdd": round(max_dd * 100, 2),                          # %
        "sharpe": round(sharpe, 3),
        "avg_holdings": round(avg_holdings, 1),
        "avg_turnover": round(avg_turnover * 100, 1),           # %
        "cash_days": cash_days,
        "n_trading_days": n_days,
        "calmar": round(annualized_return / max_dd, 3) if max_dd > 0 else 999.0,
    }


# ── 벤치마크 ──────────────────────────────────────────────────────────────────

def compute_benchmark(all_rankings: List[Dict]) -> Dict:
    """
    Buy & Hold 벤치마크: 첫날 Top 20 종목을 동일 비중으로 보유하고 끝까지 유지
    """
    if len(all_rankings) < 2:
        return {}

    dates = [rd["_date"] for rd in all_rankings]
    price_map = {}
    for rd in all_rankings:
        d = rd["_date"]
        price_map[d] = {r["ticker"]: r["price"] for r in rd.get("rankings", []) if r.get("price")}

    # 첫날 Top 20
    first = all_rankings[0]
    holdings = [r["ticker"] for r in first.get("rankings", []) if get_composite_rank(r) <= 20][:20]
    if not holdings:
        return {}

    prices_start = price_map.get(dates[0], {})
    prices_end = price_map.get(dates[-1], {})

    rets = []
    for tk in holdings:
        p0 = prices_start.get(tk)
        p1 = prices_end.get(tk)
        if p0 and p1 and p0 > 0:
            rets.append((p1 - p0) / p0)

    if not rets:
        return {}

    total = sum(rets) / len(rets)
    n_days = len(dates) - 1
    annualized = (1 + total) ** (252 / n_days) - 1 if n_days > 0 else 0

    # 일별 수익률로 MDD, Sharpe 계산
    daily_returns = []
    eq = [1.0]
    for i in range(1, len(dates)):
        d_prev = dates[i - 1]
        d_cur = dates[i]
        pp = price_map.get(d_prev, {})
        pc = price_map.get(d_cur, {})
        day_rets = []
        for tk in holdings:
            p0 = pp.get(tk)
            p1 = pc.get(tk)
            if p0 and p1 and p0 > 0:
                day_rets.append((p1 - p0) / p0)
        r = sum(day_rets) / len(day_rets) if day_rets else 0.0
        daily_returns.append(r)
        eq.append(eq[-1] * (1 + r))

    peak = eq[0]
    max_dd = 0.0
    for v in eq:
        if v > peak:
            peak = v
        dd = (peak - v) / peak
        max_dd = max(max_dd, dd)

    mean_r = sum(daily_returns) / len(daily_returns) if daily_returns else 0
    var_r = sum((r - mean_r) ** 2 for r in daily_returns) / max(len(daily_returns) - 1, 1)
    std_r = math.sqrt(var_r) if var_r > 0 else 0.0
    rf_daily = (1 + RISK_FREE_RATE) ** (1 / 252) - 1
    sharpe = (mean_r - rf_daily) / std_r * math.sqrt(252) if std_r > 0 else 0.0

    return {
        "total_return": round(total * 100, 2),
        "annualized_return": round(annualized * 100, 2),
        "mdd": round(max_dd * 100, 2),
        "sharpe": round(sharpe, 3),
        "avg_holdings": 20,
        "label": "Buy&Hold Top20",
    }


def compute_equal_weight_daily_rebalance(all_rankings: List[Dict], top_n: int = 20) -> Dict:
    """
    단순 Top-N 매일 리밸런싱 (Slow In 없음) 벤치마크
    """
    n = len(all_rankings)
    if n < 2:
        return {}

    dates = [rd["_date"] for rd in all_rankings]
    price_map = {}
    for rd in all_rankings:
        d = rd["_date"]
        price_map[d] = {r["ticker"]: r["price"] for r in rd.get("rankings", []) if r.get("price")}

    daily_returns = []
    eq = [1.0]
    prev_holdings = set()

    for i in range(1, n):
        t0 = all_rankings[i - 1]
        holdings = {r["ticker"] for r in t0.get("rankings", []) if get_composite_rank(r) <= top_n}

        d_sig = dates[i - 1]
        d_trade = dates[i]
        pp = price_map.get(d_sig, {})
        pc = price_map.get(d_trade, {})

        day_rets = []
        for tk in holdings:
            p0 = pp.get(tk)
            p1 = pc.get(tk)
            if p0 and p1 and p0 > 0:
                day_rets.append((p1 - p0) / p0)
        r = sum(day_rets) / len(day_rets) if day_rets else 0.0
        daily_returns.append(r)
        eq.append(eq[-1] * (1 + r))

    total = eq[-1] - 1.0
    n_days = len(daily_returns)
    annualized = (1 + total) ** (252 / n_days) - 1 if n_days > 0 else 0

    peak = eq[0]
    max_dd = 0.0
    for v in eq:
        if v > peak:
            peak = v
        dd = (peak - v) / peak
        max_dd = max(max_dd, dd)

    mean_r = sum(daily_returns) / len(daily_returns) if daily_returns else 0
    var_r = sum((r - mean_r) ** 2 for r in daily_returns) / max(len(daily_returns) - 1, 1)
    std_r = math.sqrt(var_r) if var_r > 0 else 0.0
    rf_daily = (1 + RISK_FREE_RATE) ** (1 / 252) - 1
    sharpe = (mean_r - rf_daily) / std_r * math.sqrt(252) if std_r > 0 else 0.0

    return {
        "total_return": round(total * 100, 2),
        "annualized_return": round(annualized * 100, 2),
        "mdd": round(max_dd * 100, 2),
        "sharpe": round(sharpe, 3),
        "avg_holdings": top_n,
        "label": f"Simple Top{top_n} Daily Rebalance",
    }


# ── 그리드 탐색 ───────────────────────────────────────────────────────────────

def run_grid_search(all_rankings: List[Dict]) -> Dict:
    """전략별 파라미터 그리드 탐색"""
    results = []

    # A. Score-based
    print("▶ Score-based 전략 탐색 중...")
    entry_scores = [60, 63, 65, 68, 70, 72, 74, 75, 78, 80]
    exit_scores  = [50, 55, 58, 60, 62, 65, 67, 68, 70, 72]

    for ent in entry_scores:
        for ext in exit_scores:
            if ext >= ent:
                continue  # 퇴출 >= 진입이면 의미 없음
            res = simulate_portfolio(all_rankings, "score", ent, ext, SLOW_IN_POOL_N)
            if "error" not in res:
                res["strategy"] = "Score"
                res["entry"] = f"score≥{ent}"
                res["exit"] = f"score<{ext}"
                res["params"] = f"E={ent}/X={ext}"
                results.append(res)

    # B. Rank-based (entry top_n = exit top_n)
    print("▶ Rank-based 전략 탐색 중...")
    rank_ns = [3, 5, 7, 10, 12, 15, 18, 20]
    for n in rank_ns:
        res = simulate_portfolio(all_rankings, "rank", n, n, SLOW_IN_POOL_N)
        if "error" not in res:
            res["strategy"] = "Rank"
            res["entry"] = f"rank≤{n}"
            res["exit"] = f"rank>{n}"
            res["params"] = f"N={n}"
            results.append(res)

    # Rank-based with asymmetric exit
    rank_entry_ns = [5, 10, 15, 20]
    rank_exit_ns  = [7, 12, 18, 25, 30]
    for ent in rank_entry_ns:
        for ext in rank_exit_ns:
            if ext <= ent:
                continue
            res = simulate_portfolio(all_rankings, "rank", ent, ext, SLOW_IN_POOL_N)
            if "error" not in res:
                res["strategy"] = "Rank-Asym"
                res["entry"] = f"rank≤{ent}"
                res["exit"] = f"rank>{ext}"
                res["params"] = f"E≤{ent}/X>{ext}"
                results.append(res)

    # C. Hybrid: Score entry + Rank exit
    print("▶ Hybrid(Score진입+Rank퇴출) 탐색 중...")
    h_score_entries = [65, 68, 70, 72, 75]
    h_rank_exits = [10, 15, 20, 25, 30]
    for ent in h_score_entries:
        for ext in h_rank_exits:
            res = simulate_portfolio(all_rankings, "hybrid_se", ent, ext, SLOW_IN_POOL_N)
            if "error" not in res:
                res["strategy"] = "Hybrid-SE"
                res["entry"] = f"score≥{ent}"
                res["exit"] = f"rank>{ext}"
                res["params"] = f"Esc{ent}/Xrk{ext}"
                results.append(res)

    # D. Hybrid: Rank entry + Score exit
    print("▶ Hybrid(Rank진입+Score퇴출) 탐색 중...")
    h_rank_entries = [5, 10, 15, 20]
    h_score_exits = [55, 60, 63, 65, 68]
    for ent in h_rank_entries:
        for ext in h_score_exits:
            res = simulate_portfolio(all_rankings, "hybrid_re", ent, ext, SLOW_IN_POOL_N)
            if "error" not in res:
                res["strategy"] = "Hybrid-RE"
                res["entry"] = f"rank≤{ent}"
                res["exit"] = f"score<{ext}"
                res["params"] = f"Erk{ent}/Xsc{ext}"
                results.append(res)

    return results


# ── 결과 포맷 ─────────────────────────────────────────────────────────────────

def fmt(results: List[Dict], sort_by: str = "sharpe", top_n: int = 15) -> str:
    """결과 테이블 포맷"""
    if not results:
        return "(결과 없음)"
    sorted_res = sorted(results, key=lambda x: x.get(sort_by, -999), reverse=True)

    header = f"{'전략':<12} {'파라미터':<16} {'총수익%':>8} {'연수익%':>8} {'MDD%':>7} {'Sharpe':>7} {'Calmar':>7} {'평균보유':>7} {'턴오버%':>8} {'현금일':>6}"
    sep = "-" * len(header)
    lines = [header, sep]
    for r in sorted_res[:top_n]:
        lines.append(
            f"{r.get('strategy',''):<12} {r.get('params',''):<16} "
            f"{r.get('total_return', 0):>8.1f} {r.get('annualized_return', 0):>8.1f} "
            f"{r.get('mdd', 0):>7.1f} {r.get('sharpe', 0):>7.3f} "
            f"{r.get('calmar', 0):>7.3f} {r.get('avg_holdings', 0):>7.1f} "
            f"{r.get('avg_turnover', 0):>8.1f} {r.get('cash_days', 0):>6}"
        )
    return "\n".join(lines)


def find_current_strategy(results: List[Dict]) -> Optional[Dict]:
    """현행 전략(Score, E=72/X=68) 결과 찾기"""
    for r in results:
        if r.get("strategy") == "Score" and r.get("params") == "E=72/X=68":
            return r
    return None


def find_best_by(results: List[Dict], metric: str) -> Optional[Dict]:
    valid = [r for r in results if metric in r and not math.isnan(r[metric]) and r[metric] != 999.0]
    if not valid:
        return None
    return max(valid, key=lambda x: x[metric])


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  종합 백테스트 — 진입/퇴출 기준 최적화")
    print("=" * 60)

    all_rankings = load_all_rankings()
    n = len(all_rankings)
    dates = [rd["_date"] for rd in all_rankings]
    print(f"\n데이터: {n}개 거래일 ({dates[0]} ~ {dates[-1]})")
    print(f"Slow In 풀 크기: Top {SLOW_IN_POOL_N}")
    print(f"시뮬레이션 방식: 시그널날 종가 → 다음 거래일 종가")
    print()

    # 벤치마크
    bm_bh = compute_benchmark(all_rankings)
    bm_simple = compute_equal_weight_daily_rebalance(all_rankings, top_n=20)

    # 그리드 탐색
    results = run_grid_search(all_rankings)
    print(f"\n총 {len(results)}개 전략 시뮬레이션 완료\n")

    # 현행 전략
    current = find_current_strategy(results)

    # 메트릭별 최적
    best_sharpe = find_best_by(results, "sharpe")
    best_total  = find_best_by(results, "total_return")
    best_calmar = find_best_by(results, "calmar")
    best_mdd    = min((r for r in results if "mdd" in r), key=lambda x: x["mdd"], default=None)

    # 카테고리별 최적
    score_results = [r for r in results if r["strategy"] == "Score"]
    rank_results  = [r for r in results if r["strategy"] in ("Rank", "Rank-Asym")]
    hybrid_results = [r for r in results if r["strategy"].startswith("Hybrid")]

    # ── 보고서 작성 ──────────────────────────────────────────────────────────
    lines = []
    lines.append("# 종합 백테스트 결과 보고서")
    lines.append(f"생성일: 2026-03-19")
    lines.append(f"데이터: {n}개 거래일 ({dates[0]} ~ {dates[-1]})")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## ⚠️ 중요 한계 사항")
    lines.append("")
    lines.append("**데이터 기간: 24 거래일 (약 1.2개월)**")
    lines.append("")
    lines.append("이 백테스트는 극도로 짧은 기간에 기반하며, 다음 한계가 있습니다:")
    lines.append("")
    lines.append("1. **심각한 과적합 위험**: 24일 데이터로 최적화된 파라미터는 미래에 일반화되지 않을 가능성이 매우 높습니다.")
    lines.append("2. **시장 국면 편향**: 2026년 2~3월의 특정 시장 상황(반도체 반등 등)만 반영합니다.")
    lines.append("3. **통계적 신뢰도 부족**: 최소 1~2년(252~504 거래일) 데이터가 필요합니다.")
    lines.append("4. **거래비용 미반영**: 슬리피지, 수수료 등 미포함 — 실제 수익률은 낮을 수 있습니다.")
    lines.append("5. **가격 데이터 한계**: 시그널날 종가 → 다음날 종가로 단순화. 실제는 다음날 시가/종가 혼용.")
    lines.append("")
    lines.append("**결론: 파라미터 선택보다 전략 구조(Slow In, 팩터 구성)의 논리적 타당성이 훨씬 중요합니다.**")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 벤치마크
    lines.append("## 벤치마크")
    lines.append("")
    lines.append("| 벤치마크 | 총수익% | 연수익% | MDD% | Sharpe |")
    lines.append("|---------|--------|--------|------|--------|")
    if bm_bh:
        lines.append(f"| {bm_bh.get('label','')} | {bm_bh.get('total_return',0):.1f}% | {bm_bh.get('annualized_return',0):.1f}% | {bm_bh.get('mdd',0):.1f}% | {bm_bh.get('sharpe',0):.3f} |")
    if bm_simple:
        lines.append(f"| {bm_simple.get('label','')} | {bm_simple.get('total_return',0):.1f}% | {bm_simple.get('annualized_return',0):.1f}% | {bm_simple.get('mdd',0):.1f}% | {bm_simple.get('sharpe',0):.3f} |")
    lines.append("")

    # 현행 전략
    lines.append("## 현행 전략 (Score E=72/X=68)")
    lines.append("")
    if current:
        lines.append("| 지표 | 값 |")
        lines.append("|-----|---|")
        lines.append(f"| 총수익률 | {current['total_return']:.1f}% |")
        lines.append(f"| 연환산수익률 | {current['annualized_return']:.1f}% |")
        lines.append(f"| MDD | {current['mdd']:.1f}% |")
        lines.append(f"| Sharpe | {current['sharpe']:.3f} |")
        lines.append(f"| Calmar | {current['calmar']:.3f} |")
        lines.append(f"| 평균 보유종목 수 | {current['avg_holdings']:.1f}개 |")
        lines.append(f"| 평균 턴오버 | {current['avg_turnover']:.1f}% |")
        lines.append(f"| 현금 보유일 | {current['cash_days']}일 |")
    else:
        lines.append("(현행 전략 결과 없음 — 해당 파라미터 후보 없음)")
    lines.append("")

    # Sharpe 기준 Top 15 전체
    lines.append("## Sharpe 기준 상위 15개 전략")
    lines.append("")
    lines.append("```")
    lines.append(fmt(results, sort_by="sharpe", top_n=15))
    lines.append("```")
    lines.append("")

    # 전략 유형별 최적
    lines.append("## 전략 유형별 Sharpe 최고")
    lines.append("")
    lines.append("| 유형 | 파라미터 | 총수익% | MDD% | Sharpe | Calmar | 평균보유 |")
    lines.append("|-----|---------|--------|------|--------|--------|--------|")
    for label, subset in [("Score", score_results), ("Rank", rank_results), ("Hybrid", hybrid_results)]:
        best = find_best_by(subset, "sharpe")
        if best:
            lines.append(f"| {label} | {best['params']} | {best['total_return']:.1f}% | {best['mdd']:.1f}% | {best['sharpe']:.3f} | {best['calmar']:.3f} | {best['avg_holdings']:.1f} |")
    lines.append("")

    # 절대 최고 전략들
    lines.append("## 메트릭별 절대 최고 전략")
    lines.append("")
    lines.append("| 메트릭 | 전략 | 파라미터 | 값 | 총수익% | MDD% |")
    lines.append("|-------|-----|---------|---|--------|------|")
    if best_sharpe:
        lines.append(f"| 최고 Sharpe | {best_sharpe['strategy']} | {best_sharpe['params']} | {best_sharpe['sharpe']:.3f} | {best_sharpe['total_return']:.1f}% | {best_sharpe['mdd']:.1f}% |")
    if best_total:
        lines.append(f"| 최고 총수익 | {best_total['strategy']} | {best_total['params']} | {best_total['total_return']:.1f}% | {best_total['total_return']:.1f}% | {best_total['mdd']:.1f}% |")
    if best_calmar:
        lines.append(f"| 최고 Calmar | {best_calmar['strategy']} | {best_calmar['params']} | {best_calmar['calmar']:.3f} | {best_calmar['total_return']:.1f}% | {best_calmar['mdd']:.1f}% |")
    if best_mdd:
        lines.append(f"| 최소 MDD | {best_mdd['strategy']} | {best_mdd['params']} | {best_mdd['mdd']:.1f}% | {best_mdd['total_return']:.1f}% | {best_mdd['mdd']:.1f}% |")
    lines.append("")

    # Score 전략 전체 Heat map 스타일
    lines.append("## Score 전략 상세 (Entry × Exit 행렬)")
    lines.append("")
    lines.append("*Sharpe 기준 정렬*")
    lines.append("")
    lines.append("```")
    lines.append(fmt(score_results, sort_by="sharpe", top_n=20))
    lines.append("```")
    lines.append("")

    # Rank 전략 전체
    lines.append("## Rank 전략 상세")
    lines.append("")
    lines.append("```")
    lines.append(fmt(rank_results, sort_by="sharpe", top_n=15))
    lines.append("```")
    lines.append("")

    # Hybrid 전략 전체
    lines.append("## Hybrid 전략 상세")
    lines.append("")
    lines.append("*Score 진입 + Rank 퇴출 (SE), Rank 진입 + Score 퇴출 (RE)*")
    lines.append("")
    lines.append("```")
    lines.append(fmt(hybrid_results, sort_by="sharpe", top_n=20))
    lines.append("```")
    lines.append("")

    # 분석 및 권고
    lines.append("## 분석 및 권고")
    lines.append("")
    lines.append("### 현행 전략(72/68) 평가")
    lines.append("")
    if current and best_sharpe:
        diff_sharpe = best_sharpe["sharpe"] - current["sharpe"]
        diff_total = best_sharpe["total_return"] - current["total_return"]
        lines.append(f"- 현행 전략 Sharpe: **{current['sharpe']:.3f}**")
        lines.append(f"- 백테스트 최고 Sharpe: **{best_sharpe['sharpe']:.3f}** ({best_sharpe['strategy']} {best_sharpe['params']})")
        lines.append(f"- 차이: {diff_sharpe:+.3f} Sharpe, {diff_total:+.1f}pp 총수익")
        lines.append("")
    lines.append("### 구조적 분석")
    lines.append("")
    lines.append("**Score vs Rank 핵심 차이:**")
    lines.append("")
    lines.append("- **Score 기반**: 절대적 품질 기준. 시장 약세기에 자연스럽게 전종목 퇴출(현금 보유) 가능.")
    lines.append("  → 하락장 방어력 우수. 그러나 유니버스 크기에 따라 score 분포가 변동.")
    lines.append("- **Rank 기반**: 상대적 순위 기준. 항상 상위 N개 보유 — 시장 하락기에도 강제 보유.")
    lines.append("  → 상승장에서 풀 투자. 그러나 하락장 방어 불가.")
    lines.append("- **Hybrid**: 진입은 엄격(score 또는 좁은 rank), 퇴출은 느슨(score 또는 넓은 rank).")
    lines.append("  → 이론적으로 좋지만 24일 데이터로는 검증 불가.")
    lines.append("")
    lines.append("### 24일 데이터 기반 권고")
    lines.append("")
    lines.append("1. **현행 72/68 유지 권장**: 시스템 설계 철학(EDA 기반, 하락장 방어)과 일치.")
    lines.append("2. **최적화 수치에 과도하게 의존 금지**: 24일 = 1년의 1/10 수준. 통계적 신뢰 없음.")
    lines.append("3. **실질적 차별화 요소는 파라미터가 아닌 팩터**: V10/Q25/G35/M30 비중, ROE 게이트 등")
    lines.append("   이 장기적으로 알파를 결정하는 핵심 요소입니다.")
    lines.append("4. **추적 관찰 필요**: 최소 6개월(126 거래일) 실적 후 파라미터 재검토 권장.")
    lines.append("")

    # 세부 전체 결과
    lines.append("## 전체 결과 (Sharpe 내림차순)")
    lines.append("")
    lines.append("```")
    lines.append(fmt(results, sort_by="sharpe", top_n=999))
    lines.append("```")
    lines.append("")

    # 저장
    report_path = OUTPUT_DIR / "backtest_results.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n보고서 저장 완료: {report_path}")

    # 콘솔 요약
    print("\n" + "=" * 60)
    print("  핵심 결과 요약")
    print("=" * 60)
    if bm_bh:
        print(f"[벤치마크] Buy&Hold Top20: 총수익 {bm_bh['total_return']:.1f}%, Sharpe {bm_bh['sharpe']:.3f}")
    if bm_simple:
        print(f"[벤치마크] Simple Top20 Daily: 총수익 {bm_simple['total_return']:.1f}%, Sharpe {bm_simple['sharpe']:.3f}")
    if current:
        print(f"[현행] Score E=72/X=68: 총수익 {current['total_return']:.1f}%, MDD {current['mdd']:.1f}%, Sharpe {current['sharpe']:.3f}")
    if best_sharpe:
        print(f"[최고Sharpe] {best_sharpe['strategy']} {best_sharpe['params']}: 총수익 {best_sharpe['total_return']:.1f}%, MDD {best_sharpe['mdd']:.1f}%, Sharpe {best_sharpe['sharpe']:.3f}")
    if best_total:
        print(f"[최고수익] {best_total['strategy']} {best_total['params']}: 총수익 {best_total['total_return']:.1f}%, MDD {best_total['mdd']:.1f}%, Sharpe {best_total['sharpe']:.3f}")
    print()


if __name__ == "__main__":
    import sys
    import io
    # Windows cp949 환경에서 유니코드 출력 강제
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    main()
