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
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, 'C:/dev')
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd

DATA = Path('C:/dev/data_cache')
# DAYS: DART 갱신 후 fnguide 시도할 기간. FnGuide 사이트는 DART보다 며칠~수주 늦게 들어옴.
# 너무 짧으면 누락, 너무 길면 사이트 부담. 30일이면 분기보고서 들어올 때까지 매일 재시도 가능.
DAYS = int(os.environ.get('FNG_INCR_DAYS', '30'))  # 기본 30일
TICKER_TIMEOUT = int(os.environ.get('FNG_TICKER_TIMEOUT', '30'))  # 종목당 30초 timeout
WORKERS = int(os.environ.get('FNG_WORKERS', '2'))  # ThreadPool worker 수


def main(base_date=None):
    if base_date is None:
        base_date = pd.Timestamp.now().strftime('%Y%m%d')

    # 종목 선정: (1) 최근 DAYS일 내 DART 갱신 + (2) fnguide < dart mtime (또는 fnguide 없음)
    # → 이미 fnguide가 dart 이후 갱신된 종목은 스킵 (이미 받음). 사이트 부담 최소화.
    cutoff = time.time() - DAYS * 86400
    dart_files = sorted(glob.glob(str(DATA / 'fs_dart_*.parquet')))
    recent = []
    skipped_fresh = 0
    for fp in dart_files:
        dart_mt = os.path.getmtime(fp)
        if dart_mt < cutoff:
            continue  # DART 너무 오래됨
        tk = Path(fp).stem.replace('fs_dart_', '')
        fng_fp = DATA / f'fs_fnguide_{tk}.parquet'
        if not fng_fp.exists() or os.path.getmtime(fng_fp) < dart_mt:
            recent.append(tk)
        else:
            skipped_fresh += 1

    if not recent:
        print(f'최근 {DAYS}일 내 DART 증분이 있는 종목들의 fnguide 모두 최신 — 스킵')
        return

    print(f'FnGuide 증분 대상: {len(recent)}종목 '
          f'(최근 {DAYS}일 DART 갱신 + fnguide stale, 이미 최신 {skipped_fresh}개 스킵)')
    print(f'  workers={WORKERS}, ticker_timeout={TICKER_TIMEOUT}s')

    from fnguide_crawler import get_financial_statement

    t0 = time.time()
    ok, fail, timeout_n = 0, 0, 0

    def _fetch(tk):
        try:
            return tk, get_financial_statement(tk, use_cache=False), None
        except Exception as e:
            return tk, None, str(e)[:80]

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {executor.submit(_fetch, tk): tk for tk in recent}
        done = 0
        for future in as_completed(futures):
            done += 1
            tk = futures[future]
            try:
                _tk, res, err = future.result(timeout=TICKER_TIMEOUT)
                if err:
                    fail += 1
                    if fail <= 3:
                        print(f'  [{tk}] ERR {err}')
                elif res is not None and not res.empty:
                    ok += 1
                else:
                    fail += 1
            except TimeoutError:
                timeout_n += 1
                fail += 1
                if timeout_n <= 3:
                    print(f'  [{tk}] TIMEOUT {TICKER_TIMEOUT}s')
            except Exception as e:
                fail += 1

            if done % 20 == 0 or done == len(recent):
                print(f'  [{done}/{len(recent)}] ok={ok} fail={fail} timeout={timeout_n} '
                      f'elapsed={time.time()-t0:.0f}s', flush=True)

    print(f'\nFnGuide 증분 완료: 성공 {ok}, 실패 {fail} (timeout {timeout_n}), '
          f'소요 {time.time()-t0:.1f}초')

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
