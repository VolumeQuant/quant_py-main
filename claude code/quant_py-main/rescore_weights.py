"""
경량 가중치 재채점 — 기존 ranking JSON의 V/Q/G/M 점수에 새 가중치 적용

Pipeline order (strategy_b_multifactor.py 동일):
1. ROE 하드게이트: ROE < 0% → 제외
2. 과락 필터: 2개+ < -0.5 → 제외 (pre-piecewise scores)
3. Piecewise ±3 스케일링
4. 가중치: V10 + Q25 + G35 + M30
5. 순위 재산정
"""

import json
import sys
import io
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

KST = ZoneInfo('Asia/Seoul')
STATE_DIR = Path(__file__).parent / 'state'

# v53 weights
W_V, W_Q, W_G, W_M = 0.10, 0.25, 0.35, 0.30


def piecewise_scale(rankings: list, score_key: str):
    """Piecewise ±3 scaling for a category score"""
    vals = [r[score_key] for r in rankings if r.get(score_key) is not None]
    if not vals:
        return
    pos_max = max(v for v in vals if v > 0) if any(v > 0 for v in vals) else 0
    neg_min = min(v for v in vals if v < 0) if any(v < 0 for v in vals) else 0

    for r in rankings:
        v = r.get(score_key, 0)
        if v > 0 and pos_max > 0:
            r[score_key] = round(v * (3.0 / pos_max), 4)
        elif v < 0 and neg_min < 0:
            r[score_key] = round(v * (-3.0 / neg_min), 4)


def rescore_date(date_str: str) -> bool:
    ranking_path = STATE_DIR / f'ranking_{date_str}.json'
    if not ranking_path.exists():
        print(f"  [SKIP] {date_str}: 파일 없음")
        return False

    with open(ranking_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    rankings = data.get('rankings', [])
    if not rankings:
        print(f"  [SKIP] {date_str}: 빈 ranking")
        return False

    orig_count = len(rankings)

    # 1. ROE 하드게이트: ROE < 0% → 제외
    roe_excluded = []
    filtered = []
    for r in rankings:
        roe = r.get('roe')
        if roe is not None and roe < 0:
            roe_excluded.append(r.get('name', r['ticker']))
        else:
            filtered.append(r)
    rankings = filtered

    # 2. 과락 필터: 2개+ < -0.5 → 제외 (pre-piecewise scores)
    fail_excluded = []
    filtered2 = []
    for r in rankings:
        scores = [r.get('value_s', 0), r.get('quality_s', 0),
                  r.get('growth_s', 0), r.get('momentum_s', 0)]
        fail_count = sum(1 for s in scores if s < -0.5)
        if fail_count >= 2:
            fail_excluded.append(r.get('name', r['ticker']))
        else:
            filtered2.append(r)
    rankings = filtered2

    # 3. Piecewise ±3 스케일링
    for key in ['value_s', 'quality_s', 'growth_s', 'momentum_s']:
        piecewise_scale(rankings, key)

    # 4. 새 가중치로 점수 재계산
    for r in rankings:
        v = r.get('value_s', 0)
        q = r.get('quality_s', 0)
        g = r.get('growth_s', 0)
        m = r.get('momentum_s', 0)
        r['score'] = round(v * W_V + q * W_Q + g * W_G + m * W_M, 4)

    # 5. 재순위
    rankings.sort(key=lambda x: x['score'], reverse=True)
    for i, r in enumerate(rankings, 1):
        r['composite_rank'] = i
        r['rank'] = i

    # 6. 저장
    data['rankings'] = rankings
    data['generated_at'] = datetime.now(KST).isoformat()
    if 'metadata' in data:
        data['metadata']['version'] = '6.0'
        data['metadata']['scored_count'] = len(rankings)

    with open(ranking_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"  [OK] {date_str}: {orig_count} → {len(rankings)}개 "
          f"(ROE:{len(roe_excluded)}, 과락:{len(fail_excluded)})")
    return True


def main():
    if len(sys.argv) > 1:
        dates = sys.argv[1:]
    else:
        files = sorted(STATE_DIR.glob('ranking_*.json'))
        dates = []
        for f in files:
            d = f.stem.replace('ranking_', '')
            if len(d) == 8 and d.isdigit():
                dates.append(d)

    print(f"v53 재채점 — {len(dates)}개 날짜")
    print(f"ROE 하드게이트 + 과락(-0.5, 2개+) + PW±3 + V{int(W_V*100)}/Q{int(W_Q*100)}/G{int(W_G*100)}/M{int(W_M*100)}")
    print("=" * 50)

    success = 0
    for d in dates:
        if rescore_date(d):
            success += 1

    print("=" * 50)
    print(f"완료: {success}/{len(dates)}")

    # Top 5 검증
    if dates:
        last = dates[-1]
        rp = STATE_DIR / f'ranking_{last}.json'
        if rp.exists():
            with open(rp, 'r', encoding='utf-8') as f:
                data = json.load(f)
            print(f"\n[검증] {last} Top 5:")
            for r in data['rankings'][:5]:
                print(f"  {r['composite_rank']}. {r.get('name','?')} "
                      f"V={r.get('value_s',0):+.2f} Q={r.get('quality_s',0):+.2f} "
                      f"G={r.get('growth_s',0):+.2f} M={r.get('momentum_s',0):+.2f} "
                      f"= {r['score']:.4f} ROE={r.get('roe','?')}")


if __name__ == '__main__':
    main()
