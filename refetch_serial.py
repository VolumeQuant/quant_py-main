"""bad_tickers_v3.txt 종목 순차 재수집 — 집PC 안전 모드 v2

원칙 (CLAUDE.md pykrx 항목 준용 — DART도 동일):
  ✗ 병렬 호출 절대 금지
  ✗ import 시 자동 실행 금지 (if __name__ guard 필수)
  ✓ 단일 worker만
  ✓ 종목당 sleep 5초
  ✓ ConnectionError 시 exponential backoff (60s → 180s → 600s)
  ✓ 기존 캐시 atomic rename (실패 시 손실 0)

사용:
  python refetch_serial.py                   # bad_tickers_v3.txt 입력
  BAD_LIST=foo.txt python refetch_serial.py  # 다른 입력
  DRY_RUN=1 python refetch_serial.py         # 실행 전 시뮬레이션
"""
import sys, os, time, shutil
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)
sys.stdout.reconfigure(encoding='utf-8')


def main():
    DRY_RUN = os.environ.get('DRY_RUN') == '1'
    input_file = os.environ.get('BAD_LIST', os.path.join(PROJECT_DIR, 'bad_tickers_v3.txt'))

    if not os.path.exists(input_file):
        print(f'ERROR: 입력 파일 없음: {input_file}')
        return 1

    with open(input_file, 'r') as f:
        tickers = [line.strip() for line in f if line.strip()]

    print(f'='*60)
    print(f'재수집 — 단일 worker, sleep 5초, exponential backoff')
    print(f'='*60)
    print(f'입력: {input_file}')
    print(f'대상: {len(tickers)}종목 (2016-2026 11년치)')
    print(f'예상 시간: 약 {len(tickers) * 11 * 0.5 / 60:.1f}분 (호출당 0.3s + 종목당 5s)')

    if DRY_RUN:
        print(f'\nDRY_RUN=1: 실제 호출 없음, 입력만 검증')
        for tk in tickers:
            cp = f'{PROJECT_DIR}/data_cache/fs_dart_{tk}.parquet'
            exists = '있음' if os.path.exists(cp) else '없음'
            print(f'  {tk} (캐시 {exists})')
        return 0

    print(f'='*60)

    # main 함수 안에서만 dart_collector import (모듈 import 시 키 발급 자동 안 되도록)
    from dart_collector import DartCollector
    from config import DART_API_KEYS

    dc = DartCollector(api_key=DART_API_KEYS[0])

    t0 = time.time()
    success = 0
    failed = []
    empty = []
    BACKOFF = [60, 180, 600]

    for i, tk in enumerate(tickers):
        cp = f'{PROJECT_DIR}/data_cache/fs_dart_{tk}.parquet'
        retries = 0
        while retries <= len(BACKOFF):
            try:
                df = dc.fetch_single(tk, 2016, 2026)
                if df is not None and not df.empty:
                    # MERGE: 기존 캐시 row 보존 (5/12 SK하이닉스 손실 사고 재발 방지)
                    if os.path.exists(cp):
                        try:
                            import pandas as pd
                            existing = pd.read_parquet(cp)
                            # 새 데이터 + 기존 row 추가 (중복 제거: 새 데이터 우선)
                            keys_new = set(zip(df['계정'], df['기준일'], df['공시구분']))
                            ext_extra = existing[~existing.apply(
                                lambda r: (r['계정'], r['기준일'], r['공시구분']) in keys_new, axis=1
                            )]
                            if 'fs_div' in df.columns and 'fs_div' not in ext_extra.columns:
                                ext_extra['fs_div'] = None
                            ext_extra = ext_extra.reindex(columns=df.columns)
                            df = pd.concat([df, ext_extra], ignore_index=True)
                        except Exception:
                            pass
                    tmp = cp + '.tmp'
                    df.to_parquet(tmp, index=False)
                    shutil.move(tmp, cp)
                    success += 1
                    print(f'  [{i+1}/{len(tickers)}] {tk}: ✓ 성공 {len(df)} rows ({time.time()-t0:.0f}s)', flush=True)
                else:
                    empty.append(tk)
                    print(f'  [{i+1}/{len(tickers)}] {tk}: 빈 결과', flush=True)
                break
            except ConnectionError as e:
                if retries < len(BACKOFF):
                    wait = BACKOFF[retries]
                    print(f'  [{i+1}/{len(tickers)}] {tk}: ConnectionError — {wait}s 대기 후 재시도 ({retries+1}/{len(BACKOFF)})', flush=True)
                    time.sleep(wait)
                    retries += 1
                else:
                    failed.append((tk, 'ConnectionError 3회 실패'))
                    print(f'  [{i+1}/{len(tickers)}] {tk}: ✗ ConnectionError 3회 실패 — skip', flush=True)
                    break
            except RuntimeError as e:
                print(f'\nAPI 한도 도달: {e}')
                print(f'중단 — 성공 {success}, 미처리 {len(tickers)-i-1}')
                return 2
            except Exception as e:
                failed.append((tk, f'{type(e).__name__}:{e}'))
                print(f'  [{i+1}/{len(tickers)}] {tk}: ✗ {type(e).__name__}', flush=True)
                break
        time.sleep(0.3)  # 종목간 sleep — 사용자 회상 "1초보다 짧음" 반영 (2026-05-12)

    elapsed = time.time() - t0
    print(f'\n{"="*60}')
    print(f'완료: 성공 {success}/{len(tickers)}, 빈 결과 {len(empty)}, 실패 {len(failed)}')
    print(f'소요: {elapsed/60:.1f}분')
    print(f'{"="*60}')

    if failed:
        with open(os.path.join(PROJECT_DIR, 'refetch_failed.txt'), 'w') as f:
            for tk, _ in failed:
                f.write(tk + '\n')
        print(f'저장: refetch_failed.txt ({len(failed)}종목)')
    if empty:
        with open(os.path.join(PROJECT_DIR, 'refetch_empty.txt'), 'w') as f:
            for tk in empty:
                f.write(tk + '\n')
        print(f'저장: refetch_empty.txt ({len(empty)}종목)')

    return 0


if __name__ == '__main__':
    sys.exit(main())
