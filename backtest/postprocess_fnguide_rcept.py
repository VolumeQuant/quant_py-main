"""FnGuide 재무제표 파일에 rcept_dt 필드 역추적 batch
PIT 보장을 위해 각 FnGuide 레코드에 실제 공시일을 DART에서 매핑.

매칭 규칙:
  (종목코드, 기준일, 공시구분) → DART의 동일 키 rcept_dt 이식
  DART에 없으면 기본 추정:
    y (연간): 기준일 + 90일 (법정 기한)
    q (분기): 기준일 + 45일

처리 후 fs_fnguide_{ticker}.parquet에 rcept_dt 컬럼 추가.
"""
import sys, glob, time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd

DATA = Path(__file__).resolve().parent.parent / 'data_cache'


def process_ticker(ticker):
    fp_fng = DATA / f'fs_fnguide_{ticker}.parquet'
    fp_dart = DATA / f'fs_dart_{ticker}.parquet'

    try:
        fng = pd.read_parquet(fp_fng)
    except Exception as e:
        return ticker, 0, f'fng_read_err: {e}'

    if fng.empty:
        return ticker, 0, 'empty'

    # 이미 rcept_dt 있으면 스킵
    if 'rcept_dt' in fng.columns:
        return ticker, len(fng), 'already_has_rcept'

    # DART rcept_dt 맵 로드
    rcept_map = {}
    if fp_dart.exists():
        try:
            dart = pd.read_parquet(fp_dart)
            if 'rcept_dt' in dart.columns:
                # (기준일, 공시구분) → rcept_dt (첫 매칭)
                for _, row in dart[['기준일', '공시구분', 'rcept_dt']].dropna(subset=['rcept_dt']).iterrows():
                    key = (row['기준일'], row['공시구분'])
                    if key not in rcept_map:
                        rcept_map[key] = row['rcept_dt']
        except Exception:
            pass

    # rcept_dt 컬럼 추가
    def derive(row):
        key = (row['기준일'], row['공시구분'])
        if key in rcept_map:
            return rcept_map[key]
        # DART에 없으면 기본 추정
        base = pd.Timestamp(row['기준일'])
        if row['공시구분'] == 'y':
            return base + pd.Timedelta(days=90)
        else:  # q
            return base + pd.Timedelta(days=45)

    fng['rcept_dt'] = fng.apply(derive, axis=1)

    # 저장
    fng.to_parquet(fp_fng)
    matched = sum(1 for _, row in fng.iterrows() if (row['기준일'], row['공시구분']) in rcept_map)
    return ticker, len(fng), f'matched={matched}/total={len(fng)}'


def main():
    files = sorted(glob.glob(str(DATA / 'fs_fnguide_*.parquet')))
    tickers = [Path(f).stem.replace('fs_fnguide_', '') for f in files]
    print(f'총 FnGuide 파일: {len(tickers)}')

    t0 = time.time()
    processed = 0
    matched_total = 0
    errors = 0
    with ProcessPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(process_ticker, tk): tk for tk in tickers}
        for fut in as_completed(futures):
            ticker, n, status = fut.result()
            processed += 1
            if 'err' in status.lower():
                errors += 1
                if errors < 5:
                    print(f'  ERR {ticker}: {status}')
            elif status.startswith('matched='):
                parts = status.split('=')
                m = int(parts[1].split('/')[0])
                matched_total += m
            if processed % 500 == 0:
                print(f'  [{processed}/{len(tickers)}] {time.time()-t0:.0f}s', flush=True)

    print(f'\n완료: {processed}종목, 에러 {errors}, 매칭된 레코드 총 {matched_total}, 소요 {time.time()-t0:.1f}초')


if __name__ == '__main__':
    main()
