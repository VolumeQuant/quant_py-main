"""
데이터 캐시 갱신 모듈 — 프로덕션 파이프라인용

FG(fast_generate_rankings_v2)가 읽는 캐시 파일들을 최신 상태로 갱신:
  1. 시가총액 (market_cap_ALL_{date}.parquet)
  2. pykrx PER/PBR/EPS/BPS (fundamental_batch_ALL_{date}.parquet)
  3. OHLCV 증분 (all_ohlcv_*.parquet — 당일 갭 + 신규 종목)
  4. KRX 섹터 (krx_sector_{date}.parquet)

run_daily.py에서 FG 호출 전에 실행.
"""

import sys
import os
import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')
SCRIPT_DIR = Path(__file__).parent.resolve()
CACHE_DIR = SCRIPT_DIR / 'data_cache'

# pykrx 임포트 + 인증
import krx_auth
krx_auth.login()
from pykrx import stock as pykrx_stock


def get_latest_trading_date() -> str:
    """최근 거래일 찾기 — 삼성전자 개별 조회 우선, 캐시 폴백"""
    today = datetime.now(KST)
    # 1차: 삼성전자 OHLCV
    try:
        end = today.strftime('%Y%m%d')
        start = (today - timedelta(days=10)).strftime('%Y%m%d')
        df = pykrx_stock.get_market_ohlcv(start, end, '005930')
        if not df.empty:
            latest = df.index[-1].strftime('%Y%m%d')
            print(f"[거래일] 개별종목 조회: {latest}")
            return latest
    except Exception as e:
        print(f"[거래일] 개별종목 조회 실패: {e}")
    # 2차: market_cap 캐시
    mc_dates = []
    for f in CACHE_DIR.glob('market_cap_ALL_*.parquet'):
        d = f.stem.split('_')[-1]
        if len(d) == 8 and d.isdigit():
            mc_dates.append(d)
    if mc_dates:
        today_str = today.strftime('%Y%m%d')
        valid = [d for d in mc_dates if d <= today_str]
        if valid:
            latest = max(valid)
            print(f"[거래일] 캐시에서 탐색: {latest}")
            return latest
    raise RuntimeError("최근 거래일을 찾을 수 없습니다.")


def refresh_market_cap(base_date: str) -> pd.DataFrame:
    """시가총액 배치 수집 → 캐시 저장"""
    from data_collector import DataCollector
    collector = DataCollector()
    df = collector.get_market_cap(base_date, market='ALL')
    print(f"[데이터] 시가총액: {len(df)}개 종목")
    return df


def refresh_fundamentals(base_date: str) -> pd.DataFrame:
    """pykrx PER/PBR/EPS/BPS 배치 수집 → 캐시 저장"""
    from data_collector import DataCollector
    collector = DataCollector()
    df = collector.get_market_fundamental_batch(base_date, market='ALL')
    print(f"[데이터] 펀더멘털: {len(df)}개 종목")
    return df


def refresh_sector(base_date: str) -> pd.DataFrame:
    """KRX 섹터 분류 수집 → 캐시 저장"""
    from data_collector import DataCollector
    collector = DataCollector()
    df = collector.get_krx_sector(base_date)
    print(f"[데이터] 섹터: {len(df)}개 종목")
    return df


def _select_best_ohlcv(base_date: str):
    """가장 적합한 OHLCV 캐시 파일 선택 (_full 우선, BASE_DATE 포함, 가장 긴 span)"""
    ohlcv_files = list(CACHE_DIR.glob("all_ohlcv_*.parquet"))
    full_files = [f for f in ohlcv_files if '_full' in f.stem]
    if full_files:
        ohlcv_files = full_files
    if not ohlcv_files:
        return None

    best_file = None
    best_span = 0
    for f in ohlcv_files:
        parts = f.stem.split('_')
        if len(parts) >= 4:
            f_start, f_end = parts[2], parts[3]
            if f_start <= base_date <= f_end:
                span = int(f_end) - int(f_start)
                if span > best_span:
                    best_span = span
                    best_file = f
    return best_file or sorted(ohlcv_files)[-1]


def _refresh_adjusted_ohlcv(raw_df: pd.DataFrame) -> None:
    """수정주가(all_ohlcv_adj) + ca_events.json 유지 — 2026-06-17 수정주가 전환.
    momentum/MA는 수정주가, CA페널티는 raw 갭(ca_events) 기반.
    ① ca_events.json 갱신(raw 갭, fetch 불필요) ② 수정주가: 새 거래일/신규종목 raw로 채우고
    (비CA 종목은 raw=수정주가), 최근 5거래일내 CA발생 종목만 KRX 수정주가 재fetch.
    실패해도 raw로 폴백 — 파이프라인 절대 안 깨짐(try/except)."""
    import json
    try:
        raw_df = raw_df.replace(0, np.nan)
        # ① ca_events.json (raw >33%/+45% 갭 = 당일 관측가능 PIT)
        ca = {}
        for tk in raw_df.columns:
            r = raw_df[tk].pct_change(fill_method=None)
            ds = [d.strftime('%Y%m%d') for d in r.index[(r < -0.33) | (r > 0.45)]]
            if ds:
                ca[tk] = ds
        with open(CACHE_DIR / 'ca_events.json', 'w', encoding='utf-8') as f:
            json.dump({'ca_by_ticker': ca, 'method': 'raw_gap_-0.33_+0.45'}, f, ensure_ascii=True)
        print(f"[수정주가] ca_events.json 갱신: {len(ca)}종목")
        # ② all_ohlcv_adj
        adj_files = sorted(CACHE_DIR.glob('all_ohlcv_adj_*.parquet'))
        if not adj_files:
            print("[수정주가] all_ohlcv_adj 없음 — 최초 build_variants 필요. 스킵(FG가 raw 폴백).")
            return
        adj = pd.read_parquet(adj_files[-1]).replace(0, np.nan)
        # 새 거래일/신규종목을 raw로 병합(수정주가 있는 칸은 보존, 나머지=raw)
        adj2 = adj.reindex(index=raw_df.index, columns=raw_df.columns)
        adj2 = adj2.where(adj2.notna(), raw_df)
        # 최근 5거래일내 CA(갭) 발생 종목만 전체 수정주가 재fetch (보통 0~3종목)
        recent = raw_df.index[-5:]
        ca_recent = [tk for tk in raw_df.columns
                     if ((raw_df[tk].pct_change(fill_method=None).loc[recent] < -0.33) |
                         (raw_df[tk].pct_change(fill_method=None).loc[recent] > 0.45)).any()]
        if ca_recent:
            fromd, tod = raw_df.index[0].strftime('%Y%m%d'), raw_df.index[-1].strftime('%Y%m%d')
            n_ok = 0
            for tk in ca_recent:
                try:
                    d = pykrx_stock.get_market_ohlcv_by_date(fromd, tod, tk, adjusted=True)
                    if d is not None and len(d) and '종가' in d.columns:
                        s = d['종가'].replace(0, np.nan); s.index = pd.to_datetime(s.index)
                        adj2[tk] = s.reindex(adj2.index)
                        n_ok += 1
                except Exception:
                    pass
                time.sleep(1.0)
            print(f"[수정주가] 최근 CA {len(ca_recent)}종목 중 {n_ok} 재조정 fetch")
        a_s, a_e = adj2.index[0].strftime('%Y%m%d'), adj2.index[-1].strftime('%Y%m%d')
        newp = CACHE_DIR / f'all_ohlcv_adj_{a_s}_{a_e}.parquet'
        adj2.to_parquet(newp)
        for old in adj_files:
            if old != newp:
                old.unlink()
        print(f"[수정주가] all_ohlcv_adj 갱신: {newp.name} ({adj2.shape[1]}종목 {adj2.shape[0]}일)")
    except Exception as e:
        print(f"[수정주가] 갱신 실패 — raw 폴백(파이프라인 정상): {type(e).__name__}: {e}")


def refresh_ohlcv_incremental(base_date: str, market_cap_df: pd.DataFrame = None) -> None:
    """OHLCV 캐시 증분 갱신 — 당일 갭 채우기 + 신규 종목 추가

    1) 캐시의 마지막 날짜 ~ base_date 사이 갭을 벌크 API로 채움
    2) 시총 1000억+ 중 OHLCV에 없는 종목의 과거 데이터 수집
    3) 다른 OHLCV 캐시 파일도 동기화
    """
    best_file = _select_best_ohlcv(base_date)
    if not best_file:
        print("[OHLCV] 캐시 파일 없음 - 스킵")
        return

    ohlcv_df = pd.read_parquet(best_file)
    base_ts = pd.Timestamp(datetime.strptime(base_date, '%Y%m%d'))
    print(f"[OHLCV] 캐시: {best_file.name} ({len(ohlcv_df.columns)}종목, {len(ohlcv_df)}일)")

    updated = False

    # --- Part 1: 당일 갭 채우기 ---
    if not ohlcv_df.empty and base_ts not in ohlcv_df.index:
        last_cached = ohlcv_df.index[-1]
        gap_days = (base_ts - last_cached).days
        if 0 < gap_days <= 30:
            print(f"[OHLCV] 증분: {last_cached.strftime('%Y%m%d')} → {base_date} ({gap_days}일)")
            new_rows = []
            for offset in range(1, gap_days + 1):
                date_dt = last_cached + timedelta(days=offset)
                date_str = date_dt.strftime('%Y%m%d')
                try:
                    day_ohlcv = pykrx_stock.get_market_ohlcv_by_ticker(date_str, market='ALL')
                    if not day_ohlcv.empty and '종가' in day_ohlcv.columns:
                        row = day_ohlcv['종가']
                        row.name = pd.Timestamp(date_dt)
                        new_rows.append(row)
                except Exception:
                    print(f"  {date_str}: 벌크 실패 (휴장일 가능)")
                time.sleep(0.5)

            if new_rows:
                new_df = pd.DataFrame(new_rows)
                ohlcv_df = pd.concat([ohlcv_df, new_df])
                ohlcv_df = ohlcv_df[~ohlcv_df.index.duplicated(keep='last')].sort_index()
                print(f"  +{len(new_rows)}거래일 → 총 {len(ohlcv_df)}일")
                updated = True
            else:
                print("  새 거래일 없음 (휴장일)")
        elif gap_days > 30:
            print(f"[OHLCV] 갭 {gap_days}일 - 수동 재수집 필요")
    elif base_ts in ohlcv_df.index:
        print(f"[OHLCV] 캐시 히트: {base_date} 이미 존재")

    # --- Part 2: 신규 종목 추가 (시총 1000억+ 중 OHLCV에 없는 것) ---
    if market_cap_df is not None and not market_cap_df.empty and '시가총액' in market_cap_df.columns:
        large_cap = set(market_cap_df[market_cap_df['시가총액'] >= 100_000_000_000].index.astype(str))
        existing = set(ohlcv_df.columns)
        missing = large_cap - existing
        if missing:
            print(f"[OHLCV] 신규 종목: {len(missing)}개 수집")
            ohlcv_end = ohlcv_df.index[-1].strftime('%Y%m%d')
            ohlcv_start = (ohlcv_df.index[-1] - timedelta(days=370)).strftime('%Y%m%d')
            collected = 0
            for ticker in sorted(missing):
                try:
                    tk_df = pykrx_stock.get_market_ohlcv_by_date(ohlcv_start, ohlcv_end, ticker)
                    if not tk_df.empty and '종가' in tk_df.columns:
                        ohlcv_df[ticker] = tk_df['종가'].reindex(ohlcv_df.index)
                        collected += 1
                    time.sleep(1)
                except Exception:
                    time.sleep(1)
            if collected > 0:
                print(f"  +{collected}종목 추가")
                updated = True
        else:
            print("[OHLCV] 누락 종목 없음")

    # --- Part 3: 캐시 저장 + 다른 OHLCV 파일 동기화 ---
    if updated:
        new_start = ohlcv_df.index[0].strftime('%Y%m%d')
        new_end = ohlcv_df.index[-1].strftime('%Y%m%d')
        new_cache = CACHE_DIR / f'all_ohlcv_{new_start}_{new_end}.parquet'
        ohlcv_df.to_parquet(new_cache)
        new_span = int(new_end) - int(new_start)
        # 짧은 범위 캐시 정리, 긴 파일 보존
        # ★ all_ohlcv_adj/vdown/vup 등 날짜가 아닌 태그 파일은 건드리지 않음(int 크래시·오염 방지, 2026-06-17)
        for old_f in CACHE_DIR.glob('all_ohlcv_*.parquet'):
            if old_f == new_cache:
                continue
            parts = old_f.stem.split('_')
            if len(parts) >= 4 and parts[2].isdigit() and parts[3].isdigit():
                old_span = int(parts[3]) - int(parts[2])
                if old_span <= new_span:
                    old_f.unlink()
                    print(f"  이전 캐시 삭제: {old_f.name}")
        # 다른 OHLCV 파일에도 신규 데이터 동기화
        for other_f in CACHE_DIR.glob('all_ohlcv_*.parquet'):
            if other_f == new_cache:
                continue
            _op = other_f.stem.split('_')
            if not (len(_op) >= 4 and _op[2].isdigit() and _op[3].isdigit()):
                continue  # 수정주가(all_ohlcv_adj 등) 동기화 제외 — 전용 루틴이 관리
            try:
                other_df = pd.read_parquet(other_f)
                other_end = other_df.index[-1]
                if other_end < ohlcv_df.index[-1]:
                    append_rows = ohlcv_df[ohlcv_df.index > other_end]
                    if not append_rows.empty:
                        upd = pd.concat([other_df, append_rows])
                        upd = upd[~upd.index.duplicated(keep='last')].sort_index()
                        o_s = upd.index[0].strftime('%Y%m%d')
                        o_e = upd.index[-1].strftime('%Y%m%d')
                        upd_path = CACHE_DIR / f'all_ohlcv_{o_s}_{o_e}.parquet'
                        upd.to_parquet(upd_path)
                        if upd_path != other_f:
                            other_f.unlink()
                        print(f"  동기화: {other_f.name} → {upd_path.name}")
            except Exception:
                pass
        print(f"[OHLCV] 캐시 저장: {new_cache.name}")

    # 2026-06-17: 수정주가(all_ohlcv_adj) + ca_events.json 유지 (updated 무관, 항상 최신화)
    _refresh_adjusted_ohlcv(ohlcv_df)


def refresh_index(base_date: str) -> None:
    """KOSPI/KOSDAQ 인덱스 OHLCV 갱신 (국면 판단용 MA200)
    단일 'close' 컬럼으로 저장. 옛 멀티컬럼 ('종가'+'kospi') 발견 시 fillna 병합."""
    for name, ticker in [('kospi', '1001'), ('kosdaq', '2001')]:
        cache_file = CACHE_DIR / f'{name}_yf.parquet'
        try:
            existing_series = None
            if cache_file.exists():
                existing_df = pd.read_parquet(cache_file)
                # 멀티컬럼이면 fillna로 단일 series 병합
                merged = existing_df.iloc[:, 0].copy()
                for col in existing_df.columns[1:]:
                    merged = merged.fillna(existing_df[col])
                existing_series = merged.dropna()
                if len(existing_series) > 0:
                    last = existing_series.index[-1].strftime('%Y%m%d')
                    if last >= base_date:
                        print(f"[인덱스] {name}: 캐시 히트 ({last})")
                        continue
                    start = last
                else:
                    start = '20200101'
            else:
                start = '20200101'
            df = pykrx_stock.get_index_ohlcv(start, base_date, ticker)
            if not df.empty and len(df.columns) >= 4:
                close = df.iloc[:, 3].copy()  # 종가
                close.name = 'close'
                new_df = pd.DataFrame(close)
                if existing_series is not None:
                    existing_series.name = 'close'
                    combined = pd.concat([pd.DataFrame(existing_series), new_df])
                    combined = combined[~combined.index.duplicated(keep='last')].sort_index()
                    combined.to_parquet(cache_file)
                else:
                    new_df.to_parquet(cache_file)
                print(f"[인덱스] {name}: {len(df)}일 갱신 ({base_date})")
            time.sleep(1)
        except Exception as e:
            print(f"[인덱스] {name} 갱신 실패: {e}")


def refresh_all(base_date: str = None) -> str:
    """모든 데이터 캐시 갱신. base_date 반환."""
    if base_date is None:
        base_date = get_latest_trading_date()
    print(f"\n{'='*50}")
    print(f"데이터 캐시 갱신: {base_date}")
    print(f"{'='*50}")

    mc_df = refresh_market_cap(base_date)
    refresh_fundamentals(base_date)
    refresh_ohlcv_incremental(base_date, market_cap_df=mc_df)
    refresh_sector(base_date)
    refresh_index(base_date)

    print(f"[완료] 데이터 캐시 갱신: {base_date}\n")
    return base_date


if __name__ == '__main__':
    if len(sys.argv) > 1 and len(sys.argv[1]) == 8:
        refresh_all(sys.argv[1])
    else:
        refresh_all()
