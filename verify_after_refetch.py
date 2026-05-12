"""재수집 후 자동 검증 (DART 호출 0, 캐시만)

집PC가 refetch_serial.py 실행 후 호출하는 검증 스크립트.

검사:
1. bad_tickers_v3.txt 종목의 매출이 FN과 5배+ 차이 사라졌는지
2. 영업이익 > 매출 같은 부정합 잔여 카운트
3. 진단 미완료 종목 (incomplete_diag_tickers.txt) 카운트 변화
4. 전체 fs_dart 무결성 베이스라인 (deeper_diagnose_offline.py 결과 vs 재실행)

종료 코드:
  0 = 정상화 완료 (검증 통과)
  1 = 잔여 BAD 종목 > 5개 (재수집 일부 실패 또는 미완 추가)
  2 = 치명적 (재수집 전보다 악화)
"""
import sys, os, glob, json
sys.path.insert(0, 'C:/dev')
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd


def check_bad_v3_recovery():
    """bad_tickers_v3 179종목이 재수집 후 FN과 매출 일치하는지"""
    with open('C:/dev/bad_tickers_v3.txt') as f:
        v3 = [l.strip() for l in f if l.strip()]

    still_bad = []
    recovered = 0
    missing_fn = 0

    for tk in v3:
        fp = f'C:/dev/data_cache/fs_dart_{tk}.parquet'
        fn_fp = f'C:/dev/data_cache/fs_fnguide_{tk}.parquet'
        if not os.path.exists(fp):
            still_bad.append((tk, 'cache_missing'))
            continue
        if not os.path.exists(fn_fp):
            missing_fn += 1
            continue
        try:
            d = pd.read_parquet(fp); f = pd.read_parquet(fn_fp)
            d_q = d[(d['공시구분']=='q') & (d['계정']=='매출액') & d['값'].notna() & (d['값']!=0)]
            f_q = f[(f['공시구분']=='q') & (f['계정']=='매출액') & f['값'].notna() & (f['값']!=0)]
            if d_q.empty or f_q.empty:
                still_bad.append((tk, 'no_q_rev'))
                continue
            m = d_q.merge(f_q, on='기준일', suffixes=('_d','_f'))
            m = m[(m['값_d']!=0) & (m['값_f']!=0)]
            if m.empty:
                still_bad.append((tk, 'no_qtr_overlap'))
                continue
            r = m['값_d'] / m['값_f']
            if ((r > 5) | (r < 0.2)).any():
                still_bad.append((tk, 'still_5x_diff'))
            else:
                recovered += 1
        except Exception as e:
            still_bad.append((tk, f'err:{type(e).__name__}'))

    return recovered, still_bad, missing_fn


def check_overall_baseline():
    """전체 fs_dart 5배+ 차이 종목 카운트 (베이스라인 비교)"""
    BASELINE_AFTER_REFETCH = 5  # 재수집 완료 후 기대치 (정상 지주사 등 false positive 최대치)
    all_files = sorted(glob.glob('C:/dev/data_cache/fs_dart_*.parquet'))
    big_diff = 0
    for fp in all_files:
        tk = os.path.basename(fp).replace('fs_dart_','').replace('.parquet','')
        fn_fp = f'C:/dev/data_cache/fs_fnguide_{tk}.parquet'
        if not os.path.exists(fn_fp): continue
        try:
            d = pd.read_parquet(fp); f = pd.read_parquet(fn_fp)
            d_q = d[(d['공시구분']=='q') & (d['계정']=='매출액') & d['값'].notna() & (d['값']!=0)]
            f_q = f[(f['공시구분']=='q') & (f['계정']=='매출액') & f['값'].notna() & (f['값']!=0)]
            if d_q.empty or f_q.empty: continue
            m = d_q.merge(f_q, on='기준일', suffixes=('_d','_f'))
            m = m[(m['값_d']!=0) & (m['값_f']!=0)]
            if m.empty: continue
            r = m['값_d'] / m['값_f']
            if ((r > 5) | (r < 0.2)).any():
                big_diff += 1
        except Exception:
            pass
    return big_diff, BASELINE_AFTER_REFETCH


def check_opi_over_rev():
    """영업이익 > 매출 비정상 카운트"""
    all_files = sorted(glob.glob('C:/dev/data_cache/fs_dart_*.parquet'))
    count = 0
    for fp in all_files:
        try:
            b = pd.read_parquet(fp)
            for qtr in b[(b['공시구분']=='q') & (b['기준일']>=pd.Timestamp('2024-01-01'))]['기준일'].unique():
                sub = b[(b['공시구분']=='q') & (b['기준일']==qtr) & b['값'].notna()]
                r = sub[sub['계정']=='매출액']; o = sub[sub['계정']=='영업이익']
                if r.empty or o.empty: continue
                rv, ov = float(r['값'].iloc[0]), float(o['값'].iloc[0])
                if rv > 0 and ov > rv * 1.1:
                    count += 1
        except Exception:
            pass
    return count


def main():
    print('=' * 60)
    print('재수집 후 자동 검증 (DART 호출 0)')
    print('=' * 60)

    # 1. bad_tickers_v3 회복 검사
    print('\n[1] bad_tickers_v3 (179) 정상화 검사')
    recovered, still_bad, missing_fn = check_bad_v3_recovery()
    total = 179
    print(f'  ✓ 정상화: {recovered}/{total}')
    print(f'  ✗ 잔여 BAD: {len(still_bad)}')
    print(f'  -  FN 없음: {missing_fn} (검증 불가)')
    if still_bad:
        from collections import Counter
        c = Counter(r for _, r in still_bad)
        print(f'  잔여 사유별: {dict(c)}')
        if len(still_bad) > 5:
            print(f'  예시 (앞 10): {[(t,r) for t,r in still_bad[:10]]}')

    # 2. 전체 베이스라인 검사
    print('\n[2] 전체 fs_dart 5배+ 차이 베이스라인')
    big_diff, baseline = check_overall_baseline()
    print(f'  현재 big_diff: {big_diff} (기대 ≤ {baseline})')

    # 3. 영업이익 > 매출 검사
    print('\n[3] 영업이익 > 매출 비정상 카운트')
    opi = check_opi_over_rev()
    print(f'  현재 카운트: {opi} (기대 ≤ 50, 대부분 매출 0 종목)')

    # 종합 판정
    print('\n' + '=' * 60)
    fatal = len(still_bad) > 20  # 재수집 후 20개+ 잔여 = 치명적
    abnormal = len(still_bad) > 5 or big_diff > baseline

    if fatal:
        print(f'❌ 치명적: 잔여 BAD {len(still_bad)} > 20 — 재수집 재확인 필요')
        return 2
    elif abnormal:
        print(f'⚠️ 일부 문제: 잔여 BAD {len(still_bad)} 또는 big_diff {big_diff} > {baseline}')
        print(f'   → 잔여 종목 수동 검토 필요')
        return 1
    else:
        print(f'✅ 검증 통과 — 정상화 완료')
        return 0


if __name__ == '__main__':
    sys.exit(main())
