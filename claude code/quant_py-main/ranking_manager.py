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


def _compute_exit_reason(t0_item: dict, t1_item: dict) -> str:
    """이탈 종목의 사유 태그 계산 — V/Q/M 스코어 비교"""
    tags = []
    for key, label in [('value_s', 'V'), ('quality_s', 'Q'), ('momentum_s', 'M')]:
        s0 = t0_item.get(key)
        s1 = t1_item.get(key)
        if s0 is not None and s1 is not None:
            if s0 < s1 - 0.05:  # 의미 있는 하락만
                tags.append(f"{label}↓")
    return ' '.join(tags) if tags else ''


def compute_rank_driver(t0_item: dict, t_ref_item: dict, rank_improved: bool = True) -> str:
    """
    순위 변동의 주요 원인을 사람이 읽을 수 있는 태그로 반환.

    순위 방향에 맞는 delta만 필터링 → 절대값 가장 큰 팩터 선택.
    - rank_improved=True  → 양(+) delta 중 최대 (순위 개선 원인)
    - rank_improved=False → 음(-) delta 중 최대 (순위 하락 원인)

    Returns: 태그 1개 또는 '🔄상대변동'
    """
    FACTORS = {
        'value_s':    ('V', 0.05),
        'quality_s':  ('Q', 0.04),
        'momentum_s': ('M', 0.10),
    }

    deltas = {}
    for key, (label, threshold) in FACTORS.items():
        s0 = t0_item.get(key)
        s1 = t_ref_item.get(key)
        if s0 is not None and s1 is not None:
            d = s0 - s1
            if abs(d) > threshold:
                deltas[label] = d

    if not deltas:
        return '🔄상대변동'

    # 순위 방향에 맞는 delta만 필터링
    if rank_improved:
        directed = {k: v for k, v in deltas.items() if v > 0}
    else:
        directed = {k: v for k, v in deltas.items() if v < 0}

    if not directed:
        return '🔄상대변동'

    # 절대값 가장 큰 팩터 선택
    dominant = max(directed, key=lambda k: abs(directed[k]))
    d = directed[dominant]

    TAG_MAP = {
        'V': ('💡저평가↑' if d > 0 else '📈주가↑'),
        'Q': ('💪실적↑' if d > 0 else '⚠️실적↓'),
        'M': ('📈모멘텀↑' if d > 0 else '📉모멘텀↓'),
    }
    return TAG_MAP[dominant]


def get_daily_changes(
    rankings_t0: dict,
    rankings_t1: dict,
    threshold: int = 30,
) -> Tuple[List[dict], List[dict]]:
    """
    일일 변동 — 어제 vs 오늘 Top 30 단순 set 비교

    Args:
        rankings_t0: 오늘(T-0) 순위
        rankings_t1: 어제(T-1) 순위
        threshold: 기준 (기본 30위)

    Returns:
        (entered, exited) — 신규 진입 종목, 이탈 종목
        이탈 종목에 'exit_reason' 필드 추가 ([V↓ Q↓ M↓])
    """
    # T-0 전체 맵 (이탈 종목의 현재 스코어 조회용)
    t0_all = {item['ticker']: item for item in rankings_t0.get('rankings', [])}

    t0_map = {}
    for item in rankings_t0.get('rankings', []):
        if item['rank'] <= threshold:
            t0_map[item['ticker']] = item

    t1_map = {}
    for item in rankings_t1.get('rankings', []):
        if item['rank'] <= threshold:
            t1_map[item['ticker']] = item

    entered = [t0_map[t] for t in (set(t0_map) - set(t1_map))]

    exited_tickers = set(t1_map) - set(t0_map)
    exited = []
    for t in exited_tickers:
        item = t1_map[t].copy()
        # T-0에서 해당 종목의 현재 스코어 찾기
        t0_item = t0_all.get(t)
        if t0_item:
            item['exit_reason'] = _compute_exit_reason(t0_item, item)
        else:
            item['exit_reason'] = ''
        exited.append(item)

    entered.sort(key=lambda x: x['rank'])
    exited.sort(key=lambda x: x['rank'])

    return entered, exited


def get_stock_status(rankings_t0, rankings_t1=None, rankings_t2=None, top_n=30):
    """
    Top N 종목의 연속 진입 상태 판별

    Returns:
        list of dicts sorted by rank, each with 'status' key:
        ✅ = 3일 연속 (매수 대상)
        ⏳ = 2일 연속 (관찰)
        🆕 = 신규 진입 (관찰)
    """
    top_t0 = {}
    for item in rankings_t0.get('rankings', []):
        if item['rank'] <= top_n:
            top_t0[item['ticker']] = item

    top_t1 = set()
    if rankings_t1:
        for item in rankings_t1.get('rankings', []):
            if item['rank'] <= top_n:
                top_t1.add(item['ticker'])

    top_t2 = set()
    if rankings_t2:
        for item in rankings_t2.get('rankings', []):
            if item['rank'] <= top_n:
                top_t2.add(item['ticker'])

    result = []
    for ticker, item in top_t0.items():
        entry = item.copy()
        in_t1 = ticker in top_t1
        in_t2 = ticker in top_t2

        if in_t1 and in_t2:
            entry['status'] = '✅'
        elif in_t1:
            entry['status'] = '⏳'
        else:
            entry['status'] = '🆕'
        result.append(entry)

    result.sort(key=lambda x: x['rank'])
    return result


def cleanup_old_rankings(keep_days: int = 30):
    """오래된 순위 파일 정리"""
    files = sorted(STATE_DIR.glob('ranking_*.json'))
    if len(files) > keep_days:
        for f in files[:-keep_days]:
            f.unlink()
            print(f"[정리] {f.name} 삭제")
