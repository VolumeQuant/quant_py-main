"""DART 캐시 증분 갱신 — 공시 시즌 최신 재무제표 수집

공시 일정 (12월 결산 기준):
  3~4월: 전년 사업보고서 (Y) → Q4 도출
  5~6월: 1분기보고서 (Q1)
  8~9월: 반기보고서 (H1)
  11~12월: 3분기보고서 (Q3)

run_daily.py Step 0에서 호출. 비공시 시즌(1,2,7,10월)에는 즉시 종료.

Usage:
    python refresh_dart_cache.py          # 자동 감지
    python refresh_dart_cache.py --force  # 비공시 시즌에도 강제 실행
"""
import sys
import time
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
from dart_collector import DartCollector, CACHE_DIR

# 공시 시즌: 월 → (target_year_offset, quarter_end_date)
# year_offset: 0=당해, -1=전년
# 실제 공시 마감 기준: Y(3/31), Q1(5/15), H1(8/14), Q3(11/14)
# 마감 전후 한 달씩만 실행 (이전: API 낭비 방지)
FILING_SEASON = {
    3:  (-1, '12-31'),  # 전년 사업보고서 (마감 3/31)
    4:  (-1, '12-31'),  # 늦게 내는 기업
    5:  (0, '03-31'),   # Q1 (마감 5/15)
    6:  (0, '03-31'),   # 늦게 내는 기업
    8:  (0, '06-30'),   # H1 (마감 8/14)
    9:  (0, '06-30'),   # 늦게 내는 기업
    11: (0, '09-30'),   # Q3 (마감 11/14)
    12: (0, '09-30'),   # 늦게 내는 기업
}


def get_target_period():
    """현재 월 기준 수집 대상 기간 반환 (매일 실행, 시즌 무관)"""
    now = datetime.now()
    month = now.month
    year = now.year

    if month in FILING_SEASON:
        year_offset, mmdd = FILING_SEASON[month]
    else:
        # 비공시 시즌: 가장 최근 공시 분기를 타겟
        # 1,2월→전년12/31, 7월→당해6/30, 10월→당해9/30
        fallback = {1: (-1, '12-31'), 2: (-1, '12-31'),
                    7: (0, '06-30'), 10: (0, '09-30')}
        year_offset, mmdd = fallback.get(month, (-1, '12-31'))

    target_year = year + year_offset
    target_date = pd.Timestamp(f'{target_year}-{mmdd}')

    return target_year, target_date


def get_production_tickers(full=False):
    """프로덕션 유니버스 티커
    full=False: 시총 1000억+ (매일)
    full=True: 전종목 (주 1회)
    """
    mcap_files = sorted(CACHE_DIR.glob('market_cap_ALL_*.parquet'))
    if not mcap_files:
        print('market_cap 캐시 없음')
        return []

    df = pd.read_parquet(mcap_files[-1])
    if full:
        return df.index.tolist()
    df['시가총액_억'] = df['시가총액'] / 1e8
    return df[df['시가총액_억'] >= 1000].index.tolist()


def needs_refresh(ticker, target_date):
    """캐시 최신성 확인: 최근 분기 데이터가 6개월 이상 오래됐으면 갱신 필요"""
    path = CACHE_DIR / f'fs_dart_{ticker}.parquet'
    if not path.exists():
        return True
    try:
        df = pd.read_parquet(path)
        q = df[df['공시구분'] == 'q']
        if q.empty:
            return True
        latest = q['기준일'].max()
        # 최신 분기가 target_date보다 6개월 이상 오래됐으면 갱신
        if (target_date - latest).days > 180:
            return True
        # target_date 자체가 없어도 갱신
        return df[df['기준일'] == target_date].empty
    except Exception:
        return True


def main():
    force = '--force' in sys.argv

    target_year, target_date = get_target_period()

    if target_year is None and not force:
        print(f'비공시 시즌 ({datetime.now().month}월) — 갱신 불필요')
        return

    if target_year is None and force:
        # 강제 모드: 당해년도 최신 분기 추정
        now = datetime.now()
        target_year = now.year
        target_date = pd.Timestamp(f'{now.year}-03-31')
        print(f'강제 모드: {target_year}년 갱신')
    else:
        print(f'DART 증분 갱신: {target_date.strftime("%Y-%m")} 분기')

    # 금요일: 전종목, 그 외: 시총 1000억+
    is_friday = datetime.now().weekday() == 4
    full_mode = is_friday or '--full' in sys.argv
    tickers = get_production_tickers(full=full_mode)
    if full_mode:
        print(f'전종목 모드 ({"금요일" if is_friday else "--full"})')
    if not tickers:
        print('유니버스 비어있음')
        return
    print(f'유니버스: {len(tickers)}종목')

    to_refresh = [t for t in tickers if needs_refresh(t, target_date)]
    print(f'갱신 필요: {len(to_refresh)}종목 (기존 {len(tickers) - len(to_refresh)}종목 스킵)')

    if not to_refresh:
        print('모든 종목 최신 — 완료')
        return

    dc = DartCollector()
    success = 0
    failed = 0
    t0 = time.time()

    for i, ticker in enumerate(to_refresh):
        try:
            df = dc.fetch_single(ticker, target_year - 1, target_year)
            if not df.empty:
                dc.save_cache(ticker, df)
                success += 1
            else:
                failed += 1
        except RuntimeError as e:
            if '한도' in str(e):
                print(f'API 한도 도달 — {success}수집 {failed}실패, 남은 {len(to_refresh) - i}종목')
                break
            failed += 1
        except Exception:
            failed += 1

        if (i + 1) % 50 == 0:
            elapsed = time.time() - t0
            print(f'  [{i+1}/{len(to_refresh)}] {success}수집 {failed}실패 | '
                  f'API {dc._call_count}건 | {elapsed:.0f}초')

    elapsed = time.time() - t0
    summary = (f'DART 증분 갱신 완료: {success}수집 {failed}실패 | '
               f'API {dc._call_count}건 | {elapsed:.0f}초')
    print(summary)

    # 텔레그램 개인봇 알림
    try:
        import requests
        from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
        msg = (f'📦 DART 캐시 갱신\n'
               f'{target_date.strftime("%Y-%m")} 분기\n'
               f'성공 {success} · 실패 {failed} · API {dc._call_count}건\n'
               f'소요 {elapsed:.0f}초')
        requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
            data={'chat_id': TELEGRAM_PRIVATE_ID, 'text': msg},
            timeout=10
        )
    except Exception:
        pass


if __name__ == '__main__':
    main()
