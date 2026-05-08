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
from datetime import datetime, timedelta
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
    # 우선주 제거: 끝자리 0만 보통주 (CLAUDE.md 정책)
    df = df[df.index.str[-1] == '0']
    # 6자리 숫자만 (KRX 특수 코드 제거: 0009K0, 0011T0 등)
    df = df[df.index.str.match(r'^\d{6}$')]
    # 외국기업 제거 (900xxx, 950xxx — DART 의무 없음)
    df = df[~df.index.str.startswith(('900', '950'))]
    # 종목명 기반 키워드 필터 (FG와 동일: REIT/금융/지주 등 DART 정기보고 없는 업종)
    name_path = CACHE_DIR / 'ticker_names_cache.json'
    if name_path.exists():
        import json
        with open(name_path, encoding='utf-8') as f:
            names = json.load(f)
        exclude_kw = ['금융', '은행', '증권', '보험', '캐피탈', '카드', '저축',
                      '지주', '홀딩스', 'SPAC', '스팩', '리츠', 'REIT',
                      '생명', '화재', '손해보험', 'IB투자', '벤처투자',
                      '자산운용', '신탁', '인프라', '맥쿼리', '리얼티']
        df['종목명'] = df.index.map(lambda t: names.get(t, ''))
        mask = df['종목명'].apply(lambda n: any(k in n for k in exclude_kw) if n else False)
        df = df[~mask].drop(columns=['종목명'])
    if full:
        return df.index.tolist()
    df['시가총액_억'] = df['시가총액'] / 1e8
    return df[df['시가총액_억'] >= 1000].index.tolist()


def get_recently_disclosed(dc, days_back=3, universe_set=None):
    """최근 N일간 분기/반기/사업보고서 공시한 상장종목 (list API 1회 호출).

    당일 발표된 실적을 즉시 캐치하기 위함. days_back은 주말/공휴일 안전마진.
    실패 시 None 반환 → 호출자가 폴백 로직 사용.
    """
    end = datetime.now().date()
    start = end - timedelta(days=days_back)
    try:
        df = dc.dart.list(
            start=start.strftime('%Y%m%d'),
            end=end.strftime('%Y%m%d'),
            kind='A', final=True,
        )
        dc._call_count += 1
    except Exception as e:
        print(f'list API 실패: {e}')
        return None
    if df is None or len(df) == 0:
        return []
    pat = '사업보고서|분기보고서|반기보고서'
    df = df[df['report_nm'].str.contains(pat, na=False)]
    df = df[df['stock_code'].notna() & (df['stock_code'] != '')]
    tickers = df['stock_code'].unique().tolist()
    if universe_set is not None:
        tickers = [t for t in tickers if t in universe_set]
    return tickers


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

    # 항상 시총 1000억+ (--full 명시 시만 전종목)
    # 2026-05-08: 금요일 자동 full_mode 제거
    # 사유: list API + no_cache 로직이 이미 신규 공시/상장 catchup 효과 보장.
    # 1Q 시즌 + 금요일 full = 30분 timeout 발생 → 제거.
    full_mode = '--full' in sys.argv
    tickers = get_production_tickers(full=full_mode)
    if full_mode:
        print('전종목 모드 (--full)')
    if not tickers:
        print('유니버스 비어있음')
        return
    print(f'유니버스: {len(tickers)}종목')

    dc = DartCollector()
    universe_set = set(tickers)

    # ▼ 신규 (2026-05-06): 공시 목록 API로 최근 정기공시 종목만 우선 갱신
    # 1Q/H1/Q3/Y 시즌 폭주 방지 — 매일 그날 공시한 종목만 처리해서 timeout 회피
    recently_disclosed = get_recently_disclosed(dc, days_back=3, universe_set=universe_set)

    if recently_disclosed is not None:
        # 신규 공시 + 캐시 없는 종목(신규 상장 등) 합집합
        no_cache = [t for t in tickers
                    if not (CACHE_DIR / f'fs_dart_{t}.parquet').exists()]
        to_refresh = list(set(recently_disclosed) | set(no_cache))
        print(f'최근 3일 정기공시: {len(recently_disclosed)}종목 · '
              f'캐시 없음: {len(no_cache)}종목 · 합집합: {len(to_refresh)}종목')
    else:
        # list API 실패 → 기존 needs_refresh 폴백 (시즌 폭주 가능성 있음)
        print('list API 실패 — 기존 needs_refresh 로직 폴백')
        to_refresh = [t for t in tickers if needs_refresh(t, target_date)]
        print(f'갱신 필요: {len(to_refresh)}종목 (기존 {len(tickers) - len(to_refresh)}종목 스킵)')

    if not to_refresh:
        print('갱신 대상 없음 — 완료')
        return
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
