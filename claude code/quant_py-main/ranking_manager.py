"""
일일 순위 관리 모듈 — v6.0 Slow In, Simple Out

기능:
  - 일일 순위 JSON 저장/로드 (state/ 디렉토리)
  - 3일 교집합 (3-Day Intersection) 계산
  - 일일 변동 (Daily Changes) — Top 30 진입/이탈
  - 종목 파이프라인 상태 (✅/⏳/🆕)
  - 콜드 스타트 처리
"""

import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')
STATE_DIR = Path(__file__).parent / 'state'
STATE_DIR.mkdir(exist_ok=True)


def get_ranking_path(date_str: str) -> Path:
    """순위 파일 경로 반환"""
    return STATE_DIR / f'ranking_{date_str}.json'


def save_ranking(date_str: str, rankings: list, metadata: dict = None):
    """
    일일 순위 저장

    Args:
        date_str: 기준일 (YYYYMMDD)
        rankings: [{"rank": 1, "ticker": "005930", "name": "삼성전자", ...}, ...]
        metadata: 추가 메타데이터 (유니버스 수, MA120 통과 수 등)
    """
    path = get_ranking_path(date_str)

    data = {
        "date": date_str,
        "generated_at": datetime.now(KST).isoformat(),
        "rankings": rankings,
    }
    if metadata:
        data["metadata"] = metadata

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[순위저장] {path.name} — {len(rankings)}개 종목")
    return True


def load_ranking(date_str: str) -> Optional[dict]:
    """
    일일 순위 로드

    Returns:
        dict with 'date', 'rankings' keys, or None if not found
    """
    path = get_ranking_path(date_str)
    if not path.exists():
        return None

    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_available_ranking_dates() -> List[str]:
    """저장된 순위 파일의 날짜 목록 (최신순)"""
    files = sorted(STATE_DIR.glob('ranking_*.json'), reverse=True)
    dates = []
    for f in files:
        # ranking_20260207.json → 20260207
        date_str = f.stem.replace('ranking_', '')
        if len(date_str) == 8 and date_str.isdigit():
            dates.append(date_str)
    return dates


def load_recent_rankings(trading_dates: List[str]) -> Dict[str, Optional[dict]]:
    """
    최근 거래일들의 순위 로드

    Args:
        trading_dates: [T-0, T-1, T-2, ...] 최신순 거래일 리스트

    Returns:
        {date_str: ranking_data or None}
    """
    result = {}
    for date_str in trading_dates:
        result[date_str] = load_ranking(date_str)
    return result


def compute_3day_intersection(
    rankings_t0: dict,
    rankings_t1: dict,
    rankings_t2: dict,
    top_n: int = 30,
    max_picks: int = 5,
) -> List[dict]:
    """
    3일 교집합 계산 — Slow In 핵심 로직

    3거래일 연속 Top N에 있었던 종목의 교집합을 구하고,
    가중 평균 순위로 정렬하여 최종 추천 종목 반환.

    가중치: T-0 × 0.5 + T-1 × 0.3 + T-2 × 0.2

    Args:
        rankings_t0: T-0 순위 데이터
        rankings_t1: T-1 순위 데이터
        rankings_t2: T-2 순위 데이터
        top_n: 교집합 기준 상위 N개 (기본 30)
        max_picks: 최종 추천 최대 수 (기본 10)

    Returns:
        가중 평균 순위로 정렬된 추천 종목 리스트
    """
    def get_top_n_map(ranking_data, n):
        """순위 데이터에서 Top N 종목의 {ticker: rank} 맵 반환"""
        top = {}
        for item in ranking_data.get('rankings', []):
            if item['rank'] <= n:
                top[item['ticker']] = item
        return top

    top_t0 = get_top_n_map(rankings_t0, top_n)
    top_t1 = get_top_n_map(rankings_t1, top_n)
    top_t2 = get_top_n_map(rankings_t2, top_n)

    # 3일 교집합
    common_tickers = set(top_t0.keys()) & set(top_t1.keys()) & set(top_t2.keys())

    if not common_tickers:
        return []

    # 가중 평균 순위 계산 — composite_rank 기반 (누적 방지)
    results = []
    for ticker in common_tickers:
        rank_t0 = top_t0[ticker].get('composite_rank', top_t0[ticker]['rank'])
        rank_t1 = top_t1[ticker].get('composite_rank', top_t1[ticker]['rank'])
        rank_t2 = top_t2[ticker].get('composite_rank', top_t2[ticker]['rank'])
        weighted_rank = rank_t0 * 0.5 + rank_t1 * 0.3 + rank_t2 * 0.2

        # T-0 데이터를 기본으로 사용 (최신 정보)
        item = top_t0[ticker].copy()
        item['weighted_rank'] = round(weighted_rank, 1)
        item['rank_t0'] = rank_t0
        item['rank_t1'] = rank_t1
        item['rank_t2'] = rank_t2
        results.append(item)

    # 가중 평균 순위로 정렬 (낮을수록 좋음)
    results.sort(key=lambda x: x['weighted_rank'])

    # 최대 picks 제한
    return results[:max_picks]


PRICE_CHANGE_THRESHOLD = 0.03   # 3% 이상 변동만 가격 태그 표시
EPS_CHANGE_THRESHOLD = 0.03     # 3% 이상 변동만 전망 태그 표시
MIN_RANK_CHANGE = 3             # |변동| < 3 → 태그 생략


def _get_forward_eps(item: dict) -> Optional[float]:
    """Forward EPS 역산: price / fwd_per"""
    price = item.get('price')
    fwd_per = item.get('fwd_per')
    if price and fwd_per and fwd_per > 0:
        return price / fwd_per
    return None


def _compute_exit_reason(t0_item: dict, t1_item: dict) -> str:
    """이탈 종목의 사유 태그 — 팩터 변화 기반

    T-0(오늘)과 T-1(어제) 팩터 점수를 비교해서
    가장 크게 하락한 팩터를 사유로 반환.

    Returns: '모멘텀↓', '가치↓', '품질↓', '성장↓', '순위밀림' 등
    """
    FACTOR_MAP = {
        'value_s':    '가치',
        'quality_s':  '품질',
        'growth_s':   '성장',
        'momentum_s': '모멘텀',
    }

    # 팩터 점수 변화량 계산 (T-0 - T-1)
    deltas = {}
    for key, label in FACTOR_MAP.items():
        v0 = t0_item.get(key)
        v1 = t1_item.get(key)
        if v0 is not None and v1 is not None:
            deltas[label] = v0 - v1

    if deltas:
        # 가장 크게 하락한 팩터
        worst_factor = min(deltas, key=deltas.get)
        worst_delta = deltas[worst_factor]
        if worst_delta < -0.1:
            return f'{worst_factor}↓'

    return '순위밀림'


def compute_rank_driver(t0_item: dict, t_ref_item: dict,
                        rank_improved: bool = True,
                        multi_day: bool = False) -> str:
    """
    종목의 전망/가격 변화를 태그로 반환.

    방향 필터 없이 실제 변화를 있는 그대로 표시:
      💪전망↑ / ⚠️전망↓ — Forward EPS 컨센서스 변화
      📈가격↑ / 📉가격↓ — 실제 주가 변화

    Returns: 0~2개 태그 문자열 또는 ''
    """
    tags = []

    # --- 전망 축 (Forward EPS 컨센서스) ---
    eps0 = _get_forward_eps(t0_item)
    eps1 = _get_forward_eps(t_ref_item)
    if eps0 is not None and eps1 is not None and eps1 != 0:
        eps_chg = (eps0 - eps1) / abs(eps1)
        if abs(eps_chg) >= EPS_CHANGE_THRESHOLD:
            tags.append('💪전망↑' if eps_chg > 0 else '⚠️전망↓')

    # --- 가격 축 (실제 주가 비교) ---
    p0 = t0_item.get('price')
    p1 = t_ref_item.get('price')
    if p0 and p1 and p1 > 0:
        pct = (p0 - p1) / p1
        if abs(pct) >= PRICE_CHANGE_THRESHOLD:
            tags.append('📈가격↑' if pct > 0 else '📉가격↓')

    return ' '.join(tags)


def get_daily_changes(
    pipeline: List[dict],
    rankings_t0: dict,
    rankings_t1: dict,
    threshold: int = 30,
) -> Tuple[List[dict], List[dict]]:
    """
    일일 변동 — 가중순위 기반 Top 30 비교

    오늘의 가중순위 Top 30(pipeline)과 어제의 단일일 Top 30을 비교.
    pipeline은 get_stock_status()가 이미 가중순위로 계산한 결과.

    Args:
        pipeline: 오늘의 가중순위 Top 30 (get_stock_status 결과)
        rankings_t0: 오늘(T-0) 원본 순위 (exit_reason 계산용)
        rankings_t1: 어제(T-1) 순위
        threshold: 기준 (기본 30위)

    Returns:
        (entered, exited) — 신규 진입 종목, 이탈 종목
        이탈 종목에 'exit_reason' 필드 추가 ([V↓ Q↓ M↓])
    """
    # 오늘의 가중순위 Top 30 ticker set
    today_tickers = {s['ticker'] for s in pipeline}
    today_map = {s['ticker']: s for s in pipeline}

    # T-0 전체 맵 (exit_reason 계산용)
    t0_all = {item['ticker']: item for item in rankings_t0.get('rankings', [])}

    # 어제의 단일일 Top 30
    t1_map = {}
    for item in rankings_t1.get('rankings', []):
        if item['rank'] <= threshold:
            t1_map[item['ticker']] = item
    yesterday_tickers = set(t1_map)

    # 진입: 오늘 가중 Top 30에 있는데 어제 Top 30에 없었던 종목
    entered = [today_map[t] for t in (today_tickers - yesterday_tickers)]

    # 이탈: 어제 Top 30에 있었는데 오늘 가중 Top 30에 없는 종목
    exited_tickers = yesterday_tickers - today_tickers
    meta = rankings_t0.get('metadata') or {}
    ma120_failed = set(meta.get('ma120_failed', []))
    has_ma120_data = 'ma120_failed' in meta
    exited = []
    for t in exited_tickers:
        item = t1_map[t].copy()
        t0_item = t0_all.get(t)
        if t0_item:
            item['exit_reason'] = _compute_exit_reason(t0_item, item)
            item['t0_rank'] = t0_item.get('composite_rank')
        elif has_ma120_data and t in ma120_failed:
            item['exit_reason'] = '120일선하락'
            item['t0_rank'] = None
        elif has_ma120_data and t not in ma120_failed:
            item['exit_reason'] = '거래부족'
            item['t0_rank'] = None
        else:
            # ma120_failed 데이터 없음 — ranking에 아예 없으면 120일선 탈락이 대부분
            item['exit_reason'] = '120일선하락'
            item['t0_rank'] = None
        exited.append(item)

    entered.sort(key=lambda x: x.get('weighted_rank', x['rank']))
    exited.sort(key=lambda x: x['rank'])

    return entered, exited


def get_stock_status(rankings_t0, rankings_t1=None, rankings_t2=None, top_n=30):
    """
    3일 가중순위 기반 Top N 종목 + 연속 진입 상태 판별

    가중순위: T-0 × 0.5 + T-1 × 0.3 + T-2 × 0.2
    Top N 여부와 정렬 모두 가중순위 기반.
    상태(✅/⏳/🆕)는 각 날의 개별 Top N 포함 여부로 판별.

    Returns:
        list of dicts sorted by weighted_rank, each with:
        - 'weighted_rank': 가중순위 (정렬·Top N 기준)
        - 'rank': T-0 단일일 순위 (추이 표시용)
        - 'status': ✅/⏳/🆕
    """
    # 전체 종목 맵 (Top N 제한 없이)
    all_t0 = {item['ticker']: item for item in rankings_t0.get('rankings', [])}
    all_t1 = {}
    top_t1_set = set()
    if rankings_t1:
        for item in rankings_t1.get('rankings', []):
            all_t1[item['ticker']] = item
            if item['rank'] <= top_n:
                top_t1_set.add(item['ticker'])

    all_t2 = {}
    top_t2_set = set()
    if rankings_t2:
        for item in rankings_t2.get('rankings', []):
            all_t2[item['ticker']] = item
            if item['rank'] <= top_n:
                top_t2_set.add(item['ticker'])

    # 모든 T-0 종목에 대해 가중순위 계산
    scored = []
    for ticker, item in all_t0.items():
        entry = item.copy()
        rank_t0 = item.get('composite_rank', item['rank'])

        if rankings_t1 and rankings_t2:
            rank_t1 = all_t1[ticker].get('composite_rank', all_t1[ticker]['rank']) if ticker in all_t1 else rank_t0
            rank_t2 = all_t2[ticker].get('composite_rank', all_t2[ticker]['rank']) if ticker in all_t2 else rank_t0
            weighted = rank_t0 * 0.5 + rank_t1 * 0.3 + rank_t2 * 0.2
        elif rankings_t1:
            rank_t1 = all_t1[ticker].get('composite_rank', all_t1[ticker]['rank']) if ticker in all_t1 else rank_t0
            weighted = rank_t0 * 0.6 + rank_t1 * 0.4
        else:
            weighted = float(rank_t0)

        entry['weighted_rank'] = round(weighted, 1)

        # 상태: 각 날의 개별 Top N 포함 여부
        in_t1 = ticker in top_t1_set
        in_t2 = ticker in top_t2_set

        if in_t1 and in_t2:
            entry['status'] = '✅'
        elif in_t1:
            entry['status'] = '⏳'
        else:
            entry['status'] = '🆕'
        scored.append(entry)

    # 가중순위 기준 Top N 선택
    scored.sort(key=lambda x: x['weighted_rank'])
    return scored[:top_n]


def cleanup_old_rankings(keep_days: int = 30):
    """오래된 순위 파일 정리"""
    files = sorted(STATE_DIR.glob('ranking_*.json'))
    if len(files) > keep_days:
        for f in files[:-keep_days]:
            f.unlink()
            print(f"[정리] {f.name} 삭제")
