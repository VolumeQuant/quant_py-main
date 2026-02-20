"""과거 ranking JSON의 rank를 가중순위 기반으로 재계산

가중순위 = T0(멀티팩터 점수순) × 0.5 + T1(prev_rank) × 0.3 + T2(prev2_rank) × 0.2
날짜 순서대로 처리하여 이전 날짜의 가중순위가 다음 날짜에 반영됨.
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

STATE_DIR = Path(__file__).parent / 'state'
PENALTY = 50
TOP_N = 30


def load_json(date_str):
    path = STATE_DIR / f'ranking_{date_str}.json'
    if not path.exists():
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(date_str, data):
    path = STATE_DIR / f'ranking_{date_str}.json'
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def migrate():
    # 모든 ranking JSON 날짜 (오래된 순)
    files = sorted(STATE_DIR.glob('ranking_*.json'))
    dates = []
    for f in files:
        date_str = f.stem.replace('ranking_', '')
        if len(date_str) == 8 and date_str.isdigit():
            dates.append(date_str)

    print(f"총 {len(dates)}개 날짜 재계산")
    print(f"가중순위: T0×0.5 + T1×0.3 + T2×0.2 (PENALTY={PENALTY})")
    print()

    # 이전 날짜의 Top 30 rank 저장 (재계산된 값)
    prev_ranks = {}  # {date: {ticker: rank}}

    for date_str in dates:
        data = load_json(date_str)
        if not data or not data.get('rankings'):
            print(f"  {date_str}: 데이터 없음 — 스킵")
            continue

        rankings = data['rankings']

        # 1. 멀티팩터 점수(score)로 정렬 → composite 순위 (T0)
        #    score가 높을수록 좋음 → descending
        scored = sorted(rankings, key=lambda x: x.get('score', 0), reverse=True)
        composite_ranks = {item['ticker']: i + 1 for i, item in enumerate(scored)}

        # 2. 이전 2일의 Top 30 rank
        prev_dates = sorted([d for d in prev_ranks.keys() if d < date_str])
        t1 = prev_dates[-1] if len(prev_dates) >= 1 else None
        t2 = prev_dates[-2] if len(prev_dates) >= 2 else None

        t1_map = prev_ranks.get(t1, {}) if t1 else {}
        t2_map = prev_ranks.get(t2, {}) if t2 else {}

        # 3. 가중순위 계산
        weighted = {}
        for ticker, r0 in composite_ranks.items():
            r1 = t1_map.get(ticker, PENALTY) if t1 else PENALTY
            r2 = t2_map.get(ticker, PENALTY) if t2 else PENALTY
            weighted[ticker] = r0 * 0.5 + r1 * 0.3 + r2 * 0.2

        # 4. 가중순위로 정렬 → 새 rank 부여
        sorted_tickers = sorted(weighted.items(), key=lambda x: x[1])
        new_rank_map = {ticker: i + 1 for i, (ticker, _) in enumerate(sorted_tickers)}

        # 5. JSON 업데이트
        for item in rankings:
            item['rank'] = new_rank_map.get(item['ticker'], 999)
        data['rankings'] = sorted(rankings, key=lambda x: x['rank'])
        save_json(date_str, data)

        # 6. 재계산된 Top 30 저장 (다음 날짜 참조용)
        prev_ranks[date_str] = {
            ticker: rank for ticker, rank in new_rank_map.items() if rank <= TOP_N
        }

        # 리포트
        top5 = [f"{item['rank']}.{item['name']}" for item in data['rankings'][:5]]
        has_history = "✅" if t1 else "🆕"
        print(f"  {date_str}: {len(rankings)}개, Top5=[{', '.join(top5)}] {has_history}")

    print(f"\n완료 — {len(dates)}개 날짜 rank 가중순위로 재계산")


if __name__ == '__main__':
    migrate()
