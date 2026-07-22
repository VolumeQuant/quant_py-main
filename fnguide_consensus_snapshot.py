# -*- coding: utf-8 -*-
"""FnGuide 일별 컨센서스 스냅샷 수집기 (2026-06-13).

매일 FnGuide 컨센서스(forward_eps/per/추정기관수/목표주가)를 스냅샷 →
data_cache/fnguide_consensus_history.parquet 에 누적.
시계열이 쌓이면 NTM revision momentum(오늘 vs N일전 forward_eps) 계산 가능
→ KR EPS 시스템 데이터 소스(yfinance 대비 커버리지 2배) + 융합 팩터용.

유니버스: 시총 >= THRESHOLD억 (기본 2000, 애널 커버 영역).
사용:
  python fnguide_consensus_snapshot.py --sample 20   # 표본 검증
  python fnguide_consensus_snapshot.py                # 전체 (백그라운드 권장)
⚠️ FnGuide 현재값만 → history는 매일 쌓아야 생김(즉시 BT 불가, forward 축적).
"""
import sys, io, os, glob, argparse, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fnguide_crawler import get_consensus_batch

PROJ = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(PROJ, 'data_cache', 'fnguide_consensus_history.parquet')
THRESHOLD_KRW = 2000 * 1e8  # 시총 2000억


def universe():
    f = sorted(glob.glob(os.path.join(PROJ, 'data_cache', 'market_cap_ALL_*.parquet')))[-1]
    df = pd.read_parquet(f)
    tickers = [str(t).zfill(6) for t in df.index[df['시가총액'] >= THRESHOLD_KRW]]
    # 우선주(끝자리≠0)/특수코드 제외 (production 필터 일관)
    tickers = [t for t in tickers if t[-1] == '0' and not (t.startswith('9') and len(t) == 6 and t[1] in '05')]
    return tickers


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sample', type=int, default=0)
    ap.add_argument('--date', default=None)
    args = ap.parse_args()

    # 날짜: 인자 우선, 없으면 오늘(평일). ⚠️구현이 market_cap 파일 날짜였는데 그 파일 생산자가
    # 무스케줄이라 7/8에 멈춤 → 매일 크롤이 같은 날짜(7/8)를 덮어써 이력이 4일치에 고정되던
    # 진범(2026-07-22 발견). 크롤은 '지금' 값이므로 도장은 오늘이 맞다. 주말은 스킵(거래일 정렬).
    from datetime import datetime
    if args.date:
        snap_date = args.date
    else:
        now = datetime.now()
        if now.weekday() >= 5:
            print('[스킵] 주말 — 스냅샷 생략'); return
        snap_date = now.strftime('%Y%m%d')

    tickers = universe()
    if args.sample:
        tickers = tickers[:args.sample]
    print(f'[수집] {snap_date} 기준 {len(tickers)}종목 (시총>=2000억)')

    df = get_consensus_batch(tickers, delay=0.5)
    df = df[df.get('has_consensus', False) == True].copy() if 'has_consensus' in df.columns else df
    if 'ticker' not in df.columns or len(df) == 0:
        print('[경고] 컨센서스 수집 0건 — 중단'); return
    df['date'] = snap_date
    keep = ['date', 'ticker', 'forward_eps', 'forward_per', 'analyst_count', 'target_price']
    df = df[[c for c in keep if c in df.columns]]
    cov = len(df)
    print(f'[커버리지] {cov}/{len(tickers)} = {100*cov/len(tickers):.0f}% 컨센서스 있음')

    if args.sample:
        print('\n[표본 결과 (저장 안 함)]')
        print(df.head(10).to_string(index=False))
        print(f'\n애널수 분포: 중앙값 {df["analyst_count"].median():.0f}, 2명이하 {(df["analyst_count"]<=2).sum()}개')
        return

    # 누적 저장 (date+ticker 중복 제거 → 재실행 시 당일분 갱신)
    if os.path.exists(OUT):
        try:
            old = pd.read_parquet(OUT)
        except Exception:  # 엔진 불일치(pyarrow↔fastparquet) 재발 방지 — fs_dart/HY-OAS와 동일 패턴
            old = pd.read_parquet(OUT, engine='fastparquet')
        old = old[old['date'] != snap_date]
        df = pd.concat([old, df], ignore_index=True)
    df.to_parquet(OUT, index=False)
    nday = df['date'].nunique()
    print(f'[저장] {OUT} — 총 {len(df)}행, {nday}일치 누적')


if __name__ == '__main__':
    main()
