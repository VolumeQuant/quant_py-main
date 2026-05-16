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

    # ── 추가 점검 (2026-05-12 사고 후): SG&A 매핑 흔적 자동 감지 ──
    # 1. DART vs FN 매출 5배+ 차이 종목 카운트 (캐시 자체 검사, DART 호출 0)
    big_diff = 0
    big_diff_tickers = []
    for fp in CACHE_DIR.glob('fs_dart_*.parquet'):
        if 'backup' in fp.name: continue
        tk = fp.stem.replace('fs_dart_', '')
        fn_fp = CACHE_DIR / f'fs_fnguide_{tk}.parquet'
        if not fn_fp.exists(): continue
        try:
            d = pd.read_parquet(fp); f = pd.read_parquet(fn_fp)
            d_q = d[(d['공시구분']=='q') & (d['계정']=='매출액') & d['값'].notna() & (d['값']!=0)]
            f_q = f[(f['공시구분']=='q') & (f['계정']=='매출액') & f['값'].notna() & (f['값']!=0)]
            if d_q.empty or f_q.empty: continue
            m = d_q.merge(f_q, on='기준일', suffixes=('_d', '_f'))
            m = m[(m['값_d'] != 0) & (m['값_f'] != 0)]
            if m.empty: continue
            r = m['값_f'] / m['값_d']
            if ((r > 5) | (r < 0.2)).any():
                big_diff += 1
                if len(big_diff_tickers) < 10:
                    big_diff_tickers.append(tk)
        except Exception:
            pass

    print(f'\n[health] DART vs FN 매출 5배+ 차이 종목: {big_diff}')
    if big_diff_tickers:
        print(f'           표본: {big_diff_tickers}')

    THRESHOLD_BIG_DIFF = 10  # 2026-05-13 baseline 측정 후 조정 (5 → 10)
    # baseline (215 재수집 후 측정): 7~10 (지주사 + 작은 회사 매출 OFS false positive)
    # 5는 너무 엄격 → 매일 false alarm. 10이 정상 baseline.
    if big_diff > THRESHOLD_BIG_DIFF:
        print(f'[health] ⚠️ 매출 5배+ 차이 {big_diff} > {THRESHOLD_BIG_DIFF} — SG&A 매핑 또는 캐시 무결성 위반 의심')
        abnormal = True

    # ── 추가 점검 (2026-05-12 LG엔솔/LG화학 사례 후): 영업이익 부호 다름 검사 ──
    # DART와 FN의 y 영업이익 부호가 2년+ 다른 종목 = 매핑 사고 강한 신호
    opi_sign_diff = 0
    opi_sign_tickers = []
    for fp in CACHE_DIR.glob('fs_dart_*.parquet'):
        if 'backup' in fp.name: continue
        tk = fp.stem.replace('fs_dart_', '')
        fn_fp = CACHE_DIR / f'fs_fnguide_{tk}.parquet'
        if not fn_fp.exists(): continue
        try:
            d = pd.read_parquet(fp); f = pd.read_parquet(fn_fp)
            d_y = d[(d['공시구분']=='y') & (d['계정']=='영업이익') & d['값'].notna() & (d['값']!=0)].set_index('기준일')['값']
            f_y = f[(f['공시구분']=='y') & (f['계정']=='영업이익') & f['값'].notna() & (f['값']!=0)].set_index('기준일')['값']
            common = d_y.index.intersection(f_y.index)
            if len(common) == 0: continue
            sign_diff = sum(1 for ts in common if (float(d_y[ts]) > 0) != (float(f_y[ts]) > 0))
            if sign_diff >= 2:
                opi_sign_diff += 1
                if len(opi_sign_tickers) < 10:
                    opi_sign_tickers.append(tk)
        except Exception:
            pass

    print(f'[health] DART vs FN 영업이익 부호 다름 (2년+) 종목: {opi_sign_diff}')
    if opi_sign_tickers:
        print(f'           표본: {opi_sign_tickers}')

    THRESHOLD_OPI_SIGN = 5  # 2026-05-13 baseline 측정 후 조정 (3 → 5)
    # baseline: LG엔솔/LG화학/알파칩스 3건 = DART vs FN 영업이익 정의 차이 (재수집 무의미)
    # 6+ 새 종목 등장 시 진짜 매핑 사고 의심
    if opi_sign_diff > THRESHOLD_OPI_SIGN:
        print(f'[health] ⚠️ 영업이익 부호 다름 {opi_sign_diff} > {THRESHOLD_OPI_SIGN} — 영업이익 매핑 사고 의심')
        abnormal = True

    # ── Phase B 추가 (2026-05-16): 직전 분기 누락률 자동 감지 ──
    # 분기 마감 후 5거래일(약 1주) 이후에도 누락률 30%+ → finstate_all sync 문제
    # 5/15 (1Q마감) → 5/22 이후 / 8/15 (2Q마감) → 8/22 이후 등
    import datetime as _dt
    today = _dt.date.today()
    # 가장 가까운 분기말 (3/31, 6/30, 9/30, 12/31)
    q_ends = [_dt.date(today.year, m, d) for m, d in [(3,31), (6,30), (9,30), (12,31)]]
    q_ends = [q for q in q_ends if q <= today]
    if q_ends:
        last_q = max(q_ends)
        days_since = (today - last_q).days
        if 7 <= days_since <= 60:  # 분기마감 1주~2달
            q1_missing = 0
            total_checked = 0
            for fp in CACHE_DIR.glob('fs_dart_*.parquet'):
                if 'backup' in fp.name: continue
                try:
                    df = pd.read_parquet(fp, columns=['계정', '기준일', '공시구분'])
                    q1 = df[(df['기준일'] == pd.Timestamp(last_q)) & (df['공시구분'] == 'q')]
                    total_checked += 1
                    if not any(q1['계정'] == '매출액'):
                        q1_missing += 1
                except Exception:
                    pass
            miss_rate = q1_missing / max(total_checked, 1) * 100
            print(f'\n[health] {last_q} 분기 매출 누락률 (마감 {days_since}일 후): '
                  f'{q1_missing}/{total_checked} ({miss_rate:.1f}%)')
            THRESHOLD_MISS_PCT = 25  # 5/15 baseline 28.1%, 7일 후 25%까지 허용
            if days_since > 7 and miss_rate > THRESHOLD_MISS_PCT:
                print(f'[health] ⚠️ 누락률 {miss_rate:.1f}% > {THRESHOLD_MISS_PCT}% — document API 폴백 또는 재수집 권고')
                abnormal = True

    if abnormal:
        print(f'\n[health] ⚠️ 비정상 변동: rows={fix_total}/{THRESHOLD_ROW}, tickers={fix_tickers}/{THRESHOLD_TICKER}, big_diff={big_diff}/{THRESHOLD_BIG_DIFF}')
        return 1
    else:
        print(f'\n[health] ✅ 정상 범위')
        return 0


if __name__ == '__main__':
    sys.exit(main())
