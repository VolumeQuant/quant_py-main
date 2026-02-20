"""과거 ranking JSON에 composite_rank 추가 + rank를 가중순위로 재계산

핵심: composite_rank = 당일 순수 점수 순위 (score 기반)
      rank = 가중순위(composite × 0.5 + T1_composite × 0.3 + T2_composite × 0.2)
      가중순위는 항상 composite_rank에서 계산 → 누적 방지
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
    files = sorted(STATE_DIR.glob('ranking_*.json'))
    dates = []
    for f in files:
        date_str = f.stem.replace('ranking_', '')
        if len(date_str) == 8 and date_str.isdigit():
            dates.append(date_str)

    print(f"총 {len(dates)}개 날짜 재계산")
    print(f"composite_rank = score 기반 순수 순위")
    print(f"rank = 가중순위(composite 기반) Top 30 + 나머지")
    print(f"PENALTY={PENALTY}")
    print()

    # 이전 날짜의 composite_rank (가중순위 계산용, 누적 없음)
    prev_composites = {}  # {date: {ticker: composite_rank}}

    for date_str in dates:
        data = load_json(date_str)
        if not data or not data.get('rankings'):
            print(f"  {date_str}: 데이터 없음 — 스킵")
            continue

        rankings = data['rankings']

        # 1. score로 정렬 → composite_rank (순수 점수 순위)
        scored = sorted(rankings, key=lambda x: x.get('score', 0), reverse=True)
        composite_map = {item['ticker']: i + 1 for i, item in enumerate(scored)}

        # composite_rank 필드 추가
        for item in rankings:
            item['composite_rank'] = composite_map.get(item['ticker'], 999)

        # 2. 이전 날짜의 composite_rank로 가중순위 계산 (누적 없음!)
        prev_dates = sorted([d for d in prev_composites.keys() if d < date_str])
        t1 = prev_dates[-1] if len(prev_dates) >= 1 else None
        t2 = prev_dates[-2] if len(prev_dates) >= 2 else None

        weighted = {}
        for ticker, cr in composite_map.items():
            r1 = prev_composites.get(t1, {}).get(ticker, PENALTY) if t1 else PENALTY
            r2 = prev_composites.get(t2, {}).get(ticker, PENALTY) if t2 else PENALTY
            weighted[ticker] = cr * 0.5 + r1 * 0.3 + r2 * 0.2

        # 3. 가중순위로 정렬 → 새 rank 부여
        sorted_tickers = sorted(weighted.items(), key=lambda x: x[1])
        new_rank_map = {ticker: i + 1 for i, (ticker, _) in enumerate(sorted_tickers)}

        for item in rankings:
            item['rank'] = new_rank_map.get(item['ticker'], 999)
        data['rankings'] = sorted(rankings, key=lambda x: x['rank'])
        save_json(date_str, data)

        # 4. 이 날짜의 composite_rank 저장 (다음 날짜 참조용)
        prev_composites[date_str] = dict(composite_map)

        # 리포트
        top5 = [f"{item['rank']}.{item['name']}(c{item['composite_rank']})" for item in data['rankings'][:5]]
        has_history = "✅" if t1 else "🆕"
        print(f"  {date_str}: {len(rankings)}개, Top5=[{', '.join(top5)}] {has_history}")

    print(f"\n완료 — {len(dates)}개 날짜 composite_rank 추가 + rank 재계산")


if __name__ == '__main__':
    migrate()
