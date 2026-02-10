"""
일일 순위 관리 모듈 — v5.0 Slow In, Fast Out

기능:
  - 일일 순위 JSON 저장/로드 (state/ 디렉토리)
  - 3일 교집합 (3-Day Intersection) 계산
  - Death List (50위 이탈) 계산
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
    rankings_today: dict,
    rankings_yesterday: dict,
    threshold: int = 50,
) -> List[dict]:
    """
    Death List 계산 — Fast Out 핵심 로직

    어제 Top 50이었으나 오늘 51위 밖으로 이탈한 종목 추출.

    Args:
        rankings_today: 오늘(T-0) 순위
        rankings_yesterday: 어제(T-1) 순위
        threshold: 이탈 기준 (기본 50위)

    Returns:
        이탈 종목 리스트 [{"ticker", "name", "yesterday_rank", ...}]
    """
    # 어제 Top 50
    yesterday_top = {}
    for item in rankings_yesterday.get('rankings', []):
        if item['rank'] <= threshold:
            yesterday_top[item['ticker']] = item

    # 오늘 Top 50
    today_top = set()
    today_all = {}
    for item in rankings_today.get('rankings', []):
        today_all[item['ticker']] = item
        if item['rank'] <= threshold:
            today_top.add(item['ticker'])

    # 어제 Top 50에 있었는데 오늘 Top 50에 없는 종목
    death_list = []
    for ticker, item in yesterday_top.items():
        if ticker not in today_top:
            entry = {
                'ticker': ticker,
                'name': item.get('name', ticker),
                'yesterday_rank': item['rank'],
                'sector': item.get('sector', '기타'),
            }
            # 오늘 순위가 있으면 추가
            if ticker in today_all:
                entry['today_rank'] = today_all[ticker]['rank']
                # 팩터별 하락 사유 분석
                reasons = []
                y = item
                t = today_all[ticker]
                for factor, label in [('value_s', 'V'), ('quality_s', 'Q'), ('momentum_s', 'M')]:
                    y_val = y.get(factor)
                    t_val = t.get(factor)
                    if y_val is not None and t_val is not None:
                        if t_val < y_val - 0.1:  # 의미 있는 하락만
                            reasons.append(f'{label}↓')
                entry['reasons'] = reasons if reasons else None
            else:
                entry['today_rank'] = None  # 유니버스에서도 탈락
                entry['reasons'] = None

            death_list.append(entry)

    # 어제 순위 기준 정렬 (높은 순위에서 탈락한 게 더 충격적)
    death_list.sort(key=lambda x: x['yesterday_rank'])

    return death_list


def get_survivors(rankings_today: dict, threshold: int = 50) -> List[dict]:
    """
    Survivors 리스트 — Top 50 생존 종목

    Args:
        rankings_today: 오늘(T-0) 순위

    Returns:
        1~50위 종목 리스트 (순위순)
    """
    survivors = []
    for item in rankings_today.get('rankings', []):
        if item['rank'] <= threshold:
            survivors.append(item)

    survivors.sort(key=lambda x: x['rank'])
    return survivors


def cleanup_old_rankings(keep_days: int = 30):
    """오래된 순위 파일 정리"""
    files = sorted(STATE_DIR.glob('ranking_*.json'))
    if len(files) > keep_days:
        for f in files[:-keep_days]:
            f.unlink()
            print(f"[정리] {f.name} 삭제")
