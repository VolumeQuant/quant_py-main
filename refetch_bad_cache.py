"""bad_cache_tickers.txt 종목 재수집"""
import sys, os, time
sys.path.insert(0, 'C:/dev')
sys.stdout.reconfigure(encoding='utf-8')

with open('C:/dev/bad_cache_tickers.txt', 'r') as f:
    tickers = [line.strip() for line in f if line.strip()]

print(f'재수집 대상: {len(tickers)}종목')

# 기존 캐시 삭제
for tk in tickers:
    fp = f'C:/dev/data_cache/fs_dart_{tk}.parquet'
    if os.path.exists(fp):
        os.remove(fp)

print('기존 캐시 삭제 완료')

from dart_collector import DartCollector
dc = DartCollector()

t0 = time.time()
success = 0
failed = []

for i, tk in enumerate(tickers):
    try:
        df = dc.fetch_single(tk, 2017, 2026)
        if df is not None and not df.empty:
            dc.save_cache(tk, df)
            success += 1
        else:
            failed.append(tk)
    except RuntimeError as e:
        # API 한도 등
        print(f'\n중단: {e}')
        break
    except Exception as e:
        failed.append(tk)

    if (i + 1) % 50 == 0:
        elapsed = time.time() - t0
        rate = (i + 1) / elapsed
        remain = (len(tickers) - i - 1) / rate
        print(f'  [{i+1}/{len(tickers)}] 성공 {success} 실패 {len(failed)} | {elapsed:.0f}초 경과, {remain:.0f}초 남음', flush=True)

elapsed = time.time() - t0
print(f'\n완료: 성공 {success} / 실패 {len(failed)} / {elapsed/60:.1f}분')
if failed:
    print(f'실패 종목 (앞 20): {failed[:20]}')
