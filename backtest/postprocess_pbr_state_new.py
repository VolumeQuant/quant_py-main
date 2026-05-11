"""state_new/ + state_new/defense/ pbr/per/roe batch 후처리.
각 ranking 날짜에 해당하는 fundamental_batch_ALL_{date}.parquet에서 PER/PBR/ROE 추출.
"""
import sys, json, time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd

PROJECT = Path(__file__).parent.parent
import os as _os
_target = _os.environ.get('STATE_TARGET', 'state')
STATE_DIRS = [
    PROJECT / _target,
    PROJECT / _target / 'defense',
]
DATA_DIR = PROJECT / 'data_cache'

# fundamental_batch_ALL_*.parquet 인덱스 (날짜 → 경로)
_FUND_INDEX = None


def get_fund_index():
    global _FUND_INDEX
    if _FUND_INDEX is None:
        _FUND_INDEX = {}
        for fp in sorted(DATA_DIR.glob('fundamental_batch_ALL_*.parquet')):
            d = fp.stem.replace('fundamental_batch_ALL_', '')
            if len(d) == 8 and d.isdigit():
                _FUND_INDEX[d] = fp
    return _FUND_INDEX


def find_nearest_fund(date_str, max_gap=10):
    idx = get_fund_index()
    if date_str in idx:
        return idx[date_str]
    keys = sorted(idx.keys())
    target = int(date_str)
    best = None; best_gap = max_gap + 1
    for k in keys:
        try:
            gap = abs(int(k) - target)
            if gap < best_gap:
                best_gap = gap; best = idx[k]
        except: pass
    return best if best_gap <= max_gap else None


def postprocess_dir(state_dir_str):
    state_dir = Path(state_dir_str)
    files = sorted(state_dir.glob('ranking_*.json'))
    files = [f for f in files if len(f.stem.replace('ranking_', '')) == 8
             and f.stem.replace('ranking_', '').isdigit()]
    if not files:
        return state_dir_str, 0, 0.0

    t0 = time.time()
    processed = skipped = 0
    fund_cache = {}

    for fp in files:
        try:
            d = fp.stem.replace('ranking_', '')
            with open(fp, 'r', encoding='utf-8') as f:
                data = json.load(f)
            rankings = data.get('rankings', [])
            if not rankings:
                skipped += 1; continue

            fund_fp = find_nearest_fund(d, max_gap=10)
            if fund_fp is None:
                skipped += 1; continue
            if str(fund_fp) not in fund_cache:
                try:
                    fund_cache[str(fund_fp)] = pd.read_parquet(fund_fp)
                except:
                    skipped += 1; continue
            fund_df = fund_cache[str(fund_fp)]

            for item in rankings:
                ticker = item['ticker']
                if ticker in fund_df.index:
                    row = fund_df.loc[ticker]
                    for col, key in [('PER', 'per'), ('PBR', 'pbr')]:
                        v = row.get(col)
                        if v is not None and pd.notna(v) and v > 0:
                            item[key] = round(float(v), 2)
                    eps, bps = row.get('EPS'), row.get('BPS')
                    if (eps is not None and bps is not None and pd.notna(eps)
                            and pd.notna(bps) and bps > 0 and eps != 0):
                        item['roe'] = round(float(eps / bps * 100), 2)

            data['rankings'] = rankings
            with open(fp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            processed += 1
        except Exception as e:
            print(f'  ERR {fp.name}: {str(e)[:60]}', flush=True)
            skipped += 1

    elapsed = time.time() - t0
    return state_dir_str, processed, elapsed


def main():
    print(f'=== state_new pbr/per/roe batch 후처리 시작 ===')
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=2) as ex:
        futures = {ex.submit(postprocess_dir, str(d)): d for d in STATE_DIRS}
        for fut in as_completed(futures):
            d, n, elapsed = fut.result()
            print(f'  {d}: {n}개 처리 ({elapsed:.1f}초)', flush=True)
    print(f'\n=== 총 소요: {time.time()-t0:.1f}초 ===')


if __name__ == '__main__':
    main()
