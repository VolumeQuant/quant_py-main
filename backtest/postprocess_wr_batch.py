"""wr batch 후처리 — state/ + state/defense/ 1294일 전체에 weighted_rank 필드 추가

run_daily.py의 _postprocess_ranking은 "당일 파일"만 처리. 과거 파일엔 wr 없음.
v79 재생성 기회에 과거 파일 전부에 wr 붙임 (시스템 수익률 정확도 향상).

wr 공식: T0 × 0.5 + T1 × 0.3 + T2 × 0.2  (PENALTY = 50, run_daily와 동일)

처리 순서: 날짜 오름차순 (T-1/T-2 참조 위해)
"""
import sys, os, json, time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
sys.stdout.reconfigure(encoding='utf-8')

_PROJECT = Path(__file__).parent.parent
STATE_DIRS = [
    _PROJECT / 'state',
    _PROJECT / 'state' / 'defense',
    _PROJECT / 'backtest' / 'bt_extended',
    _PROJECT / 'backtest' / 'bt_extended_defense',
]

PENALTY = 50


def postprocess_dir(state_dir):
    """state_dir의 모든 ranking 파일에 wr 추가 (날짜순)"""
    files = sorted(state_dir.glob('ranking_*.json'))
    # 날짜 필터: 정확한 YYYYMMDD 8자리만
    files = [f for f in files if len(f.stem.replace('ranking_', '')) == 8
             and f.stem.replace('ranking_', '').isdigit()]

    if not files:
        return state_dir, 0, 0

    t0 = time.time()
    processed = 0
    skipped = 0

    for i, fp in enumerate(files):
        try:
            with open(fp, 'r', encoding='utf-8') as f:
                data = json.load(f)
            rankings = data.get('rankings', [])
            if not rankings:
                skipped += 1
                continue

            # T-1, T-2 찾기
            t1_map, t2_map = {}, {}
            for j, target in [(i-1, 't1'), (i-2, 't2')]:
                if j < 0:
                    continue
                pfp = files[j]
                try:
                    with open(pfp, 'r', encoding='utf-8') as f:
                        pdata = json.load(f)
                    pm = {r['ticker']: r.get('composite_rank', r.get('rank', PENALTY))
                          for r in pdata.get('rankings', [])}
                    if target == 't1':
                        t1_map = pm
                    else:
                        t2_map = pm
                except Exception:
                    pass

            # wr 계산
            for item in rankings:
                r0 = item.get('composite_rank', item.get('rank', PENALTY))
                r1 = t1_map.get(item['ticker'], PENALTY)
                r2 = t2_map.get(item['ticker'], PENALTY)
                item['weighted_rank'] = round(r0 * 0.5 + r1 * 0.3 + r2 * 0.2, 1)

            # rank 재정렬 (wr 기준)
            rankings.sort(key=lambda x: (x['weighted_rank'], -x.get('score', 0)))
            for new_rank, item in enumerate(rankings, 1):
                item['rank'] = new_rank

            data['rankings'] = rankings
            with open(fp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            processed += 1
        except Exception as e:
            print(f'  ERR {fp.name}: {str(e)[:60]}', flush=True)
            skipped += 1

    elapsed = time.time() - t0
    return state_dir, processed, elapsed


def main():
    print(f'=== wr batch 후처리 시작 ===')
    t0 = time.time()

    # 2워커 병렬 (state/, state/defense/)
    with ProcessPoolExecutor(max_workers=2) as ex:
        futures = {ex.submit(postprocess_dir, d): d for d in STATE_DIRS}
        for fut in as_completed(futures):
            d, n, elapsed = fut.result()
            print(f'  {d}: {n}개 처리 ({elapsed:.1f}초)', flush=True)

    print(f'\n=== 총 소요: {time.time()-t0:.1f}초 ===')


if __name__ == '__main__':
    main()
