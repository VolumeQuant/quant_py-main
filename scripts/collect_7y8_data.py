"""Phase 2: 2018-07 BT용 데이터 수집 (DART + pykrx 병렬)

- DART: 2016-Q1~2017-Q4 (fs_dart_*.parquet 보강)
- pykrx OHLCV: 2017-06~2019-05 (all_ohlcv_* 캐시 확장)
- pykrx market_cap: 2017 일별
- pykrx fundamental: 2018-01~2019-12
- KOSPI index: 2017-01~2020-05 (kospi_yf.parquet 확장)

실행: python scripts/collect_7y8_data.py
완료 시 개인봇 알림.
"""
import os, sys, time, json, traceback
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np

PROJECT = Path(__file__).parent.parent
CACHE_DIR = PROJECT / 'data_cache'
LOG_DIR = PROJECT / 'logs'
LOG_DIR.mkdir(exist_ok=True)


def log(msg, stream='main'):
    ts = datetime.now().strftime('%H:%M:%S')
    line = f'[{ts}][{stream}] {msg}'
    print(line, flush=True)
    with open(LOG_DIR / f'collect_7y8_{stream}.log', 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def send_private_tg(msg):
    try:
        import requests
        from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
        url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
        MAX = 4000
        for i in range(0, len(msg), MAX):
            chunk = msg[i:i+MAX]
            requests.post(url, data={'chat_id': TELEGRAM_PRIVATE_ID, 'text': chunk}, timeout=30)
            time.sleep(0.3)
    except Exception as e:
        log(f'텔레그램 실패: {e}', 'main')


# ============================================================
# Stream A: DART 2016-Q1~2017-Q4 수집
# ============================================================
def collect_dart():
    log('=== DART 2016-Q1~2017-Q4 수집 시작 ===', 'dart')
    t0 = time.time()
    try:
        from dart_collector import DartCollector, CACHE_DIR as DART_CACHE

        collector = DartCollector()

        # 유니버스: 현재 fs_dart 존재하는 종목들 + 새로 필요한 종목
        existing_tickers = set()
        for fp in CACHE_DIR.glob('fs_dart_*.parquet'):
            existing_tickers.add(fp.stem.replace('fs_dart_', ''))
        log(f'기존 fs_dart 종목: {len(existing_tickers)}', 'dart')

        # 현재 유니버스에 있는 종목 중심 (대형주)
        # 2016-2017에 상장되어 있던 종목만 의미 있음
        # 시총 1000억+ 기준 약 1500개
        tickers = sorted(existing_tickers)

        # 표본 테스트: 1개 종목 2016년 수집으로 방식 검증
        log(f'표본 테스트: {tickers[0]} 2016년 수집', 'dart')
        sample_ok = False
        try:
            # fetch_single 활용
            collector.fetch_single(tickers[0], 2016, 2017)
            sample_ok = True
            log('표본 성공', 'dart')
        except Exception as e:
            log(f'표본 실패: {e}', 'dart')

        if not sample_ok:
            log('DART 표본 실패 → 중단', 'dart')
            return False, 0

        # 전체 수집 (이미 있는 fs_dart에 2016-2017 증분)
        log(f'전체 {len(tickers)}종목 수집 시작', 'dart')
        success_cnt = 0
        fail_cnt = 0
        for i, tk in enumerate(tickers):
            try:
                collector.fetch_single(tk, 2016, 2017)
                success_cnt += 1
            except Exception:
                fail_cnt += 1
            if (i + 1) % 100 == 0:
                log(f'{i+1}/{len(tickers)} 성공={success_cnt} 실패={fail_cnt}', 'dart')

        elapsed = (time.time() - t0) / 60
        log(f'DART 완료: 성공 {success_cnt}, 실패 {fail_cnt}, {elapsed:.1f}분', 'dart')
        return True, success_cnt
    except Exception as e:
        log(f'DART 오류: {e}', 'dart')
        log(traceback.format_exc(), 'dart')
        return False, 0


# ============================================================
# Stream B: pykrx 2017~2019 수집 (순차 1초 sleep)
# ============================================================
def collect_pykrx():
    log('=== pykrx 2017-06~2019-05 수집 시작 ===', 'pykrx')
    t0 = time.time()
    try:
        import krx_auth
        krx_auth.login()
        from pykrx import stock

        # Step 1: KOSPI index 2017-01-02~2020-05-31
        log('KOSPI index 확장 수집...', 'pykrx')
        kospi_fp = CACHE_DIR / 'kospi_yf.parquet'
        if kospi_fp.exists():
            existing = pd.read_parquet(kospi_fp)
            log(f'기존 KOSPI: {existing.index[0]} ~ {existing.index[-1]}', 'pykrx')
            start_needed = '20170101'
            end_needed = existing.index[0].strftime('%Y%m%d')
        else:
            start_needed = '20170101'
            end_needed = '20260414'
            existing = pd.DataFrame()

        try:
            kospi_df = stock.get_index_ohlcv(start_needed, end_needed, '1001')
            if not kospi_df.empty:
                new_kospi = kospi_df['종가']
                new_kospi.name = 'KOSPI'
                if not existing.empty:
                    combined = pd.concat([new_kospi.to_frame(), existing]).sort_index()
                    combined = combined[~combined.index.duplicated(keep='first')]
                else:
                    combined = new_kospi.to_frame()
                combined.to_parquet(kospi_fp)
                log(f'KOSPI 확장: {len(kospi_df)}일 추가, 총 {len(combined)}일', 'pykrx')
        except Exception as e:
            log(f'KOSPI 실패: {e}', 'pykrx')
        time.sleep(1)

        # Step 2: OHLCV 2017-06-01~2019-05-31 벌크 수집
        log('OHLCV 확장 수집...', 'pykrx')
        # 기존 OHLCV 확인
        ohlcv_files = sorted(CACHE_DIR.glob('all_ohlcv_*.parquet'))
        if not ohlcv_files:
            log('OHLCV 캐시 없음, 생성', 'pykrx')
            existing_ohlcv = pd.DataFrame()
            existing_start = pd.Timestamp('2030-01-01')
        else:
            existing_ohlcv = pd.read_parquet(ohlcv_files[-1])
            existing_start = existing_ohlcv.index[0]
            log(f'기존 OHLCV: {existing_ohlcv.index[0]} ~ {existing_ohlcv.index[-1]}, {existing_ohlcv.shape[1]}종목', 'pykrx')

        needed_start = pd.Timestamp('2017-06-01')
        needed_end = min(existing_start - pd.Timedelta(days=1), pd.Timestamp('2019-05-31'))

        if needed_start <= needed_end:
            log(f'수집 범위: {needed_start.date()} ~ {needed_end.date()}', 'pykrx')
            new_rows = []
            cur = needed_start
            cnt = 0
            while cur <= needed_end:
                ds = cur.strftime('%Y%m%d')
                try:
                    day_ohlcv = stock.get_market_ohlcv_by_ticker(ds, market='ALL')
                    if not day_ohlcv.empty and '종가' in day_ohlcv.columns:
                        row = day_ohlcv['종가']
                        row.name = cur
                        new_rows.append(row)
                        cnt += 1
                except Exception:
                    pass
                cur += pd.Timedelta(days=1)
                time.sleep(1)  # 1초 sleep 엄수
                if cnt > 0 and cnt % 100 == 0:
                    log(f'  {cnt}일 수집, 현재 {cur.date()}', 'pykrx')

            if new_rows:
                new_df = pd.DataFrame(new_rows)
                combined = pd.concat([new_df, existing_ohlcv]).sort_index()
                combined = combined[~combined.index.duplicated(keep='first')]
                new_file = CACHE_DIR / f'all_ohlcv_{combined.index[0].strftime("%Y%m%d")}_{combined.index[-1].strftime("%Y%m%d")}.parquet'
                combined.to_parquet(new_file)
                log(f'OHLCV 확장: {cnt}일 추가, 총 {len(combined)}일, 저장: {new_file.name}', 'pykrx')
                # 이전 파일 유지 (안전)
        else:
            log('OHLCV 확장 불필요', 'pykrx')

        # Step 3: fundamental 2018-01~2019-12 증분
        log('fundamental 확장 수집...', 'pykrx')
        existing_fund = set()
        for fp in CACHE_DIR.glob('fundamental_batch_ALL_*.parquet'):
            d = fp.stem.split('_')[-1]
            if len(d) == 8 and d.isdigit():
                existing_fund.add(d)

        start_f = pd.Timestamp('2018-01-02')
        end_f = pd.Timestamp('2019-12-31')
        need_f = []
        cur = start_f
        while cur <= end_f:
            ds = cur.strftime('%Y%m%d')
            if ds not in existing_fund:
                need_f.append(ds)
            cur += pd.Timedelta(days=1)

        log(f'fundamental 수집 대상: {len(need_f)}일', 'pykrx')
        collected_f = 0
        for ds in need_f:
            try:
                f_df = stock.get_market_fundamental(ds, market='ALL')
                if not f_df.empty:
                    f_df.to_parquet(CACHE_DIR / f'fundamental_batch_ALL_{ds}.parquet')
                    collected_f += 1
            except Exception:
                pass
            time.sleep(1)
            if collected_f > 0 and collected_f % 100 == 0:
                log(f'  fundamental {collected_f}일 수집', 'pykrx')
        log(f'fundamental 완료: {collected_f}일 추가', 'pykrx')

        # Step 4: market_cap 일별 2017~2019 증분
        log('market_cap 확장 수집...', 'pykrx')
        existing_mc = set()
        for fp in CACHE_DIR.glob('market_cap_ALL_*.parquet'):
            d = fp.stem.split('_')[-1]
            if len(d) == 8 and d.isdigit():
                existing_mc.add(d)

        start_m = pd.Timestamp('2017-06-01')
        end_m = pd.Timestamp('2019-12-31')
        need_m = []
        cur = start_m
        while cur <= end_m:
            ds = cur.strftime('%Y%m%d')
            if ds not in existing_mc:
                need_m.append(ds)
            cur += pd.Timedelta(days=1)

        log(f'market_cap 수집 대상: {len(need_m)}일', 'pykrx')
        collected_m = 0
        for ds in need_m:
            try:
                m_df = stock.get_market_cap(ds, market='ALL')
                if not m_df.empty:
                    m_df.to_parquet(CACHE_DIR / f'market_cap_ALL_{ds}.parquet')
                    collected_m += 1
            except Exception:
                pass
            time.sleep(1)
            if collected_m > 0 and collected_m % 100 == 0:
                log(f'  market_cap {collected_m}일 수집', 'pykrx')
        log(f'market_cap 완료: {collected_m}일 추가', 'pykrx')

        elapsed = (time.time() - t0) / 60
        log(f'pykrx 완료: {elapsed:.1f}분', 'pykrx')
        return True
    except Exception as e:
        log(f'pykrx 오류: {e}', 'pykrx')
        log(traceback.format_exc(), 'pykrx')
        return False


# ============================================================
# 메인
# ============================================================
def main():
    log('=== Phase 2 수집 시작 ===', 'main')
    t0 = time.time()
    send_private_tg('[Phase 2] 2018-07 BT 데이터 수집 시작 (예상 60분)')

    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_dart = ex.submit(collect_dart)
        fut_pykrx = ex.submit(collect_pykrx)
        dart_result = fut_dart.result()
        pykrx_result = fut_pykrx.result()

    elapsed = (time.time() - t0) / 60
    status = f'Phase 2 완료 ({elapsed:.1f}분)\n'
    status += f'DART: {"OK" if dart_result[0] else "실패"} ({dart_result[1]}종목 수집)\n'
    status += f'pykrx: {"OK" if pykrx_result else "실패"}'
    log(status, 'main')
    send_private_tg(status)
    return dart_result[0] and pykrx_result


if __name__ == '__main__':
    ok = main()
    sys.exit(0 if ok else 1)
