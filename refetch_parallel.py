"""bad_cache_tickers.txt 종목을 트리플 키 + 3 ThreadPool 병렬 재수집

각 worker가 별도 키 + 별도 OpenDartReader 인스턴스로 동시 호출
4년치 (2023-2026)만 수집 → 시스템 필요 데이터만
"""
import sys, os, time
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, 'C:/dev')
sys.stdout.reconfigure(encoding='utf-8')

with open('C:/dev/bad_cache_tickers.txt', 'r') as f:
    tickers = [line.strip() for line in f if line.strip()]

print(f'재수집 대상: {len(tickers)}종목 (2016-2026 11년치, BT 7.8년 커버)')

# 기존 캐시 삭제
deleted = 0
for tk in tickers:
    fp = f'C:/dev/data_cache/fs_dart_{tk}.parquet'
    if os.path.exists(fp):
        os.remove(fp)
        deleted += 1
print(f'기존 캐시 삭제: {deleted}건')

from dart_collector import DartCollector
from config import DART_API_KEYS

NUM_WORKERS = len([k for k in DART_API_KEYS if k])
print(f'병렬 워커: {NUM_WORKERS}개')

# 워커별 별도 collector (각자 자기 키 사용)
collectors = [DartCollector(api_key=DART_API_KEYS[i]) for i in range(NUM_WORKERS)]

# 종목 라운드로빈 분배: i번째 종목 → worker (i % NUM_WORKERS)
buckets = [[] for _ in range(NUM_WORKERS)]
for i, tk in enumerate(tickers):
    buckets[i % NUM_WORKERS].append(tk)

print(f'분배: ' + ', '.join(f'W{i}={len(buckets[i])}' for i in range(NUM_WORKERS)))

def worker_run(worker_idx, ticker_list):
    dc = collectors[worker_idx]
    success = 0
    failed = []
    for j, tk in enumerate(ticker_list):
        try:
            df = dc.fetch_single(tk, 2016, 2026)
            if df is not None and not df.empty:
                dc.save_cache(tk, df)
                success += 1
            else:
                failed.append(tk)
        except RuntimeError as e:
            print(f'\nW{worker_idx} 중단: {e}', flush=True)
            return success, failed, ticker_list[j:]
        except Exception:
            failed.append(tk)
        if (j + 1) % 30 == 0:
            print(f'  W{worker_idx} [{j+1}/{len(ticker_list)}] 성공 {success} 실패 {len(failed)}', flush=True)
    return success, failed, []

t0 = time.time()
total_success = 0
total_failed = []
remaining = []

with ThreadPoolExecutor(max_workers=NUM_WORKERS) as ex:
    futures = {ex.submit(worker_run, i, buckets[i]): i for i in range(NUM_WORKERS)}
    for fut in as_completed(futures):
        w = futures[fut]
        s, f, rem = fut.result()
        total_success += s
        total_failed.extend(f)
        remaining.extend(rem)
        print(f'\nW{w} 완료: 성공 {s} 실패 {len(f)} 미처리 {len(rem)}', flush=True)

elapsed = time.time() - t0
print(f'\n=== 전체 완료: 성공 {total_success}/{len(tickers)} 실패 {len(total_failed)} 미처리 {len(remaining)} ===')
print(f'소요: {elapsed/60:.1f}분')
if total_failed:
    print(f'실패 종목 (앞 20): {total_failed[:20]}')
