"""DART vs FnGuide 데이터 정합성 모니터링 (옵션 F 보조).

매일 run_daily 종료 후 또는 주 1회 실행. baseline 비교 후 비정상 변동 시 개인봇 알림.

baseline (2026-05-12 EDA, fs_dart 1927종목 기준):
  - 매출 mismatch (y+q): 약 388 row
  - 영업이익 mismatch: 약 34종목
  - 자산 mismatch: 약 4종목
  - 총 정정 row: ~2283 (1100종목)

임계값:
  - 총 정정 row > 4000: 비정상 (≈ baseline 2배)
  - 총 정정 종목 > 1500: 비정상

종료 코드:
  0 = 정상 또는 정정 0
  1 = baseline 2배 초과 (개인봇 알림 권장)
"""
import sys, glob, os, json
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent / 'backtest'))

import pandas as pd
from fast_generate_rankings_v2 import fix_dart_account_mismatch

CACHE_DIR = Path(__file__).parent / 'data_cache'
BASELINE_TICKERS = 1100
BASELINE_ROWS = 2283
THRESHOLD_ROW = 4000
THRESHOLD_TICKER = 1500


def main():
    print('[health] DART vs FN 정합성 점검 중...')
    fix_total = 0
    fix_tickers = 0
    per_acct = {}
    sample_examples = []

    for fp in CACHE_DIR.glob('fs_dart_*.parquet'):
        if 'backup' in fp.name:
            continue
        tk = fp.stem.replace('fs_dart_', '')
        fn_fp = CACHE_DIR / f'fs_fnguide_{tk}.parquet'
        if not fn_fp.exists():
            continue
        try:
            d = pd.read_parquet(fp)
            f = pd.read_parquet(fn_fp)
        except Exception:
            continue
        _, removed = fix_dart_account_mismatch(d, f)
        if removed:
            fix_total += len(removed)
            fix_tickers += 1
            for kind, acct, ts in removed:
                key = f'{kind}_{acct}'
                per_acct[key] = per_acct.get(key, 0) + 1
            if len(sample_examples) < 5:
                sample_examples.append((tk, removed[0]))

    print(f'[health] 정정 종목: {fix_tickers} (baseline {BASELINE_TICKERS})')
    print(f'[health] 정정 row: {fix_total} (baseline {BASELINE_ROWS})')
    print(f'[health] 항목별:')
    for k in sorted(per_acct, key=lambda x: -per_acct[x]):
        print(f'           {k}: {per_acct[k]}')

    if sample_examples:
        print(f'[health] 표본 5개:')
        for tk, (kind, acct, ts) in sample_examples:
            print(f'           {tk} {kind} {acct} {ts.date() if hasattr(ts, "date") else ts}')

    abnormal = fix_total > THRESHOLD_ROW or fix_tickers > THRESHOLD_TICKER
    if abnormal:
        print(f'\n[health] ⚠️ 비정상 변동: rows={fix_total}/{THRESHOLD_ROW}, tickers={fix_tickers}/{THRESHOLD_TICKER}')
        return 1
    else:
        print(f'\n[health] ✅ 정상 범위')
        return 0


if __name__ == '__main__':
    sys.exit(main())
