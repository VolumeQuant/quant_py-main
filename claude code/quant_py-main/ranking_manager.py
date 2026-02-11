"""
일일 순위 관리 모듈 — v5.1 Slow In, Fast Out

기능:
  - 일일 순위 JSON 저장/로드 (state/ 디렉토리)
  - 3일 교집합 (3-Day Intersection) 계산
  - Death List (50위 이탈) 계산
  - 종목 파이프라인 상태 (✅/🔸/🆕)
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
        metadata: 추가 메타데이터 (유니버스 수, MA60 통과 수 등)
    """
    data = {
        "date": date_str,
        "generated_at": datetime.now(KST).isoformat(),
        "rankings": rankings,
    }
    if metadata:
        data["metadata"] = metadata

    path = get_ranking_path(date_str)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[순위저장] {path.name} — {len(rankings)}개 종목")


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

    # 가중 평균 순위 계산
    results = []
    for ticker in common_tickers:
        rank_t0 = top_t0[ticker]['rank']
        rank_t1 = top_t1[ticker]['rank']
        rank_t2 = top_t2[ticker]['rank']
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


def compute_death_list(
    rankings_t0: dict,
    rankings_t1: dict,
    rankings_t2: dict = None,
    threshold: int = 30,
) -> List[dict]:
    """
    Death List 계산 — 2일 연속 Top 30 밖

    T-2에서 Top 30이었으나, T-1과 T-0 모두 Top 30 밖인 종목 추출.
    rankings_t2가 없으면 빈 리스트 반환 (3일 데이터 필요).

    Args:
        rankings_t0: 오늘(T-0) 순위
        rankings_t1: 어제(T-1) 순위
        rankings_t2: 그저께(T-2) 순위
        threshold: 이탈 기준 (기본 30위)

    Returns:
        이탈 종목 리스트 [{"ticker", "name", "ref_rank", "today_rank", ...}]
    """
    if rankings_t2 is None:
        return []

    # T-2 Top N (기준: 보유 가능 종목)
    ref_top = {}
    for item in rankings_t2.get('rankings', []):
        if item['rank'] <= threshold:
            ref_top[item['ticker']] = item

    # T-1 Top N
    t1_top = set()
    for item in rankings_t1.get('rankings', []):
        if item['rank'] <= threshold:
            t1_top.add(item['ticker'])

    # T-0 Top N + 전체
    t0_top = set()
    t0_all = {}
    for item in rankings_t0.get('rankings', []):
        t0_all[item['ticker']] = item
        if item['rank'] <= threshold:
            t0_top.add(item['ticker'])

    # Death List: T-2 Top N → T-1 밖 AND T-0 밖 (2일 연속 이탈)
    death_list = []
    for ticker, ref_item in ref_top.items():
        if ticker not in t1_top and ticker not in t0_top:
            entry = {
                'ticker': ticker,
                'name': ref_item.get('name', ticker),
                'ref_rank': ref_item['rank'],
                'sector': ref_item.get('sector', '기타'),
            }
            if ticker in t0_all:
                entry['today_rank'] = t0_all[ticker]['rank']
                # 팩터별 하락 사유 분석
                reasons = []
                for factor, label in [('value_s', 'V'), ('quality_s', 'Q'), ('momentum_s', 'M')]:
                    ref_val = ref_item.get(factor)
                    t_val = t0_all[ticker].get(factor)
                    if ref_val is not None and t_val is not None:
                        if t_val < ref_val - 0.1:
                            reasons.append(f'{label}↓')
                entry['reasons'] = reasons if reasons else None
            else:
                entry['today_rank'] = None  # 유니버스 이탈
                entry['reasons'] = None

            death_list.append(entry)

    # 기준 순위 기준 정렬 (높은 순위에서 탈락한 게 더 충격적)
    death_list.sort(key=lambda x: x['ref_rank'])

    return death_list


def get_survivors(rankings_today: dict, threshold: int = 30) -> List[dict]:
    """
    Survivors 리스트 — Top 30 생존 종목

    Args:
        rankings_today: 오늘(T-0) 순위

    Returns:
        1~30위 종목 리스트 (순위순)
    """
    survivors = []
    for item in rankings_today.get('rankings', []):
        if item['rank'] <= threshold:
            survivors.append(item)

    survivors.sort(key=lambda x: x['rank'])
    return survivors


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
