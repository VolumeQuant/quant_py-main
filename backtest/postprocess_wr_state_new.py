"""state_new/ + state_new/defense/ wr batch 후처리 (옵션F production 재생성용).
원본 postprocess_wr_batch.py는 C:/dev/state 하드코딩 — state_new 작업용 별도.
"""
import sys, os, json, time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
sys.stdout.reconfigure(encoding='utf-8')

PROJECT = Path(__file__).parent.parent
# 환경변수 STATE_TARGET 지원: 'state'(production) or 'state_new'(작업용)
import os as _os
_target = _os.environ.get('STATE_TARGET', 'state')
STATE_DIRS = [
    PROJECT / _target,
    PROJECT / _target / 'defense',
]

PENALTY = 50


def postprocess_dir(state_dir):
    state_dir = Path(state_dir)
    files = sorted(state_dir.glob('ranking_*.json'))
    files = [f for f in files if len(f.stem.replace('ranking_', '')) == 8
             and f.stem.replace('ranking_', '').isdigit()]

    if not files:
        return state_dir, 0, 0.0

    t0 = time.time()
    processed = skipped = 0

    for i, fp in enumerate(files):
        try:
            with open(fp, 'r', encoding='utf-8') as f:
                data = json.load(f)
            rankings = data.get('rankings', [])
            if not rankings:
                skipped += 1
                continue

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

            for item in rankings:
                r0 = item.get('composite_rank', item.get('rank', PENALTY))
                r1 = t1_map.get(item['ticker'], PENALTY)
                r2 = t2_map.get(item['ticker'], PENALTY)
                item['weighted_rank'] = round(r0 * 0.5 + r1 * 0.3 + r2 * 0.2, 1)

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
    print(f'=== state_new wr batch 후처리 시작 ===')
    t0 = time.time()

    with ProcessPoolExecutor(max_workers=2) as ex:
        futures = {ex.submit(postprocess_dir, str(d)): d for d in STATE_DIRS}
        for fut in as_completed(futures):
            d, n, elapsed = fut.result()
            print(f'  {d}: {n}개 처리 ({elapsed:.1f}초)', flush=True)

    print(f'\n=== 총 소요: {time.time()-t0:.1f}초 ===')


if __name__ == '__main__':
    main()
