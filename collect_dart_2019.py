"""DART 2019년 재무제표 수집 — bt_2021~2022 Growth TTM용

2022년 초 TTM YoY 계산에 2019 Q3~Q4 데이터 필요.
전체 2019년을 수집하여 완전한 TTM 계산 보장.

Usage:
    python collect_dart_2019.py
"""
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd

PROJECT_ROOT = Path(__file__).parent
CACHE_DIR = PROJECT_ROOT / 'data_cache'


def main():
    from dart_collector import DartCollector

    files = sorted(CACHE_DIR.glob('fs_dart_*.parquet'))
    tickers = [f.stem.replace('fs_dart_', '') for f in files]
    print(f'대상: {len(tickers)}종목')

    dc = DartCollector()
    success = 0
    failed = 0
    skipped = 0

    for i, ticker in enumerate(tickers):
        try:
            cache_path = CACHE_DIR / f'fs_dart_{ticker}.parquet'
            existing = pd.read_parquet(cache_path) if cache_path.exists() else pd.DataFrame()

            # 이미 2019 있으면 스킵
            if not existing.empty:
                col = existing.columns[1]
                years = set(str(p)[:4] for p in existing[col].dropna().unique())
                if '2019' in years:
                    skipped += 1
                    continue

            new_df = dc.fetch_single(ticker, 2019, 2019)

            if new_df is not None and not new_df.empty:
                if not existing.empty:
                    combined = pd.concat([existing, new_df]).drop_duplicates()
                    combined = combined.sort_values(combined.columns[1])
                else:
                    combined = new_df
                combined.to_parquet(cache_path, index=False)
                success += 1
            else:
                skipped += 1

            if (i + 1) % 100 == 0:
                print(f'  [{i+1}/{len(tickers)}] 성공={success} 스킵={skipped} 실패={failed} | API {dc._call_count}건')

        except RuntimeError as e:
            if '한도' in str(e):
                print(f'\nAPI 한도 도달: {e}')
                break
            failed += 1
        except Exception as e:
            failed += 1

    print(f'\n=== DART 2019 수집 완료 ===')
    print(f'성공: {success}, 스킵: {skipped}, 실패: {failed}, API: {dc._call_count}건')


if __name__ == '__main__':
    main()
