"""FnGuide 증분 갱신 — 최근 N일 내 DART 공시된 종목만 재크롤

DART 증분(매일 refresh_dart_cache.py)으로 새로 공시된 종목은
FnGuide에도 새 분기 데이터가 있을 가능성 높음.

로직:
  1. DART 파일 mtime이 최근 N일 이내인 종목 탐지
  2. 해당 종목만 FnGuide get_financial_statement(use_cache=False) 호출
  3. 크롤링 후 rcept_dt는 postprocess_fnguide_rcept.py 별도 실행 or 본 스크립트 끝에 호출

실행:
    python refresh_fnguide_incremental.py [base_date]
"""
import sys, os, glob, time
from pathlib import Path
sys.path.insert(0, 'C:/dev')
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd

DATA = Path('C:/dev/data_cache')
DAYS = int(os.environ.get('FNG_INCR_DAYS', '3'))  # 기본 3일


def main(base_date=None):
    if base_date is None:
        base_date = pd.Timestamp.now().strftime('%Y%m%d')

    # 최근 DAYS일 내 DART 갱신 종목 탐지
    cutoff = time.time() - DAYS * 86400
    dart_files = sorted(glob.glob(str(DATA / 'fs_dart_*.parquet')))
    recent = []
    for fp in dart_files:
        if os.path.getmtime(fp) >= cutoff:
            tk = Path(fp).stem.replace('fs_dart_', '')
            recent.append(tk)

    if not recent:
        print(f'최근 {DAYS}일 내 DART 증분 없음 — FnGuide 스킵')
        return

    print(f'FnGuide 증분 대상: {len(recent)}종목 (최근 {DAYS}일 DART 갱신)')

    from fnguide_crawler import get_financial_statement

    t0 = time.time()
    ok, fail = 0, 0
    for i, tk in enumerate(recent, 1):
        try:
            # use_cache=False로 강제 재크롤
            res = get_financial_statement(tk, use_cache=False)
            if res is not None and not res.empty:
                ok += 1
            else:
                fail += 1
        except Exception as e:
            fail += 1
            if fail <= 3:
                print(f'  [{tk}] ERR {str(e)[:60]}')
        if i % 20 == 0 or i == len(recent):
            print(f'  [{i}/{len(recent)}] ok={ok} fail={fail} elapsed={time.time()-t0:.0f}s', flush=True)

    print(f'\nFnGuide 증분 완료: 성공 {ok}, 실패 {fail}, 소요 {time.time()-t0:.1f}초')

    # rcept_dt 보강 (DART에서 역추적)
    print('\nrcept_dt 역추적 (postprocess_fnguide_rcept.py 호출)...')
    import subprocess
    subprocess.run(
        [sys.executable, 'C:/dev/backtest/postprocess_fnguide_rcept.py'],
        check=False,
    )


if __name__ == '__main__':
    base = sys.argv[1] if len(sys.argv) > 1 and len(sys.argv[1]) == 8 else None
    main(base)
