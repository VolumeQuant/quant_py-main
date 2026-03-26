"""DART 2020년 재무제표 보충 수집

fs_dart 캐시 중 2020년 데이터가 없는 종목만 타겟 수집.
collect_dart_all.py의 전체 phase 순회 대신, 2020년만 직접 수집.

Usage:
    python collect_dart_2020.py
"""
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd

PROJECT_ROOT = Path(__file__).parent
CACHE_DIR = PROJECT_ROOT / 'data_cache'


def find_tickers_missing_2020():
    """fs_dart 캐시에서 2020년 데이터 없는 종목 목록 반환"""
    missing = []
    files = sorted(CACHE_DIR.glob('fs_dart_*.parquet'))
    for f in files:
        try:
            df = pd.read_parquet(f)
            col = df.columns[1]  # 기준일자 컬럼
            years = set(str(p)[:4] for p in df[col].dropna().unique())
            if '2020' not in years:
                ticker = f.stem.replace('fs_dart_', '')
                missing.append(ticker)
        except Exception:
            pass
    return missing


def main():
    from dart_collector import DartCollector

    missing = find_tickers_missing_2020()
    print(f'2020년 데이터 없는 종목: {len(missing)}개')

    if not missing:
        print('수집할 종목 없음 — 완료')
        return

    dc = DartCollector()
    success = 0
    failed = 0
    skipped = 0

    for i, ticker in enumerate(missing):
        try:
            # 기존 캐시 로드
            cache_path = CACHE_DIR / f'fs_dart_{ticker}.parquet'
            existing = pd.read_parquet(cache_path) if cache_path.exists() else pd.DataFrame()

            # 2020년만 수집
            new_df = dc.fetch_single(ticker, 2020, 2020)

            if new_df is not None and not new_df.empty:
                # 기존 데이터와 병합
                if not existing.empty:
                    combined = pd.concat([existing, new_df]).drop_duplicates()
                    combined = combined.sort_values(combined.columns[1])  # 기준일자 정렬
                else:
                    combined = new_df
                combined.to_parquet(cache_path, index=False)
                success += 1
            else:
                skipped += 1

            if (i + 1) % 50 == 0:
                print(f'  진행: {i+1}/{len(missing)} (성공 {success}, 스킵 {skipped}, 실패 {failed})')
                print(f'  API 호출 누적: {dc._call_count}/{dc._total_limit}')

        except RuntimeError as e:
            if '한도' in str(e):
                print(f'\nAPI 일일 한도 도달: {e}')
                print(f'내일 재실행하면 이어서 수집됩니다.')
                break
            failed += 1
        except Exception as e:
            failed += 1
            if (i + 1) % 100 == 0:
                print(f'  에러 ({ticker}): {e}')

    print(f'\n=== DART 2020 수집 완료 ===')
    print(f'성공: {success}, 스킵(데이터없음): {skipped}, 실패: {failed}')
    print(f'API 호출: {dc._call_count}건')


if __name__ == '__main__':
    main()
