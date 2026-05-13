"""식별 알고리즘 v2 — 캐시 매출 row 모든 분기 vs DART SG&A 비교

판정: 캐시 매출 == DART SG&A (오차 2% 이내) → 잘못 분기
종목 단위로는: 잘못 분기 1개 이상 → 재수집 대상

표본 8종목 (잘못 4 + 정상 4) 100% 정확도 확인 후 전체 적용.
"""
import sys, os, time
sys.path.insert(0, 'C:/dev')
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from dart_collector import DartCollector
from config import DART_API_KEYS

REPRT_MAP = {3: '11013', 6: '11012', 9: '11014', 12: '11011'}

collectors = [DartCollector(api_key=DART_API_KEYS[i]) for i in range(3)]

def get_dart_sga_year(dc, ticker, year):
    """해당 종목 + 년도의 4분기 SG&A 모두 가져오기 → {Timestamp: sga_amt(원)}"""
    out = {}
    for month, code in REPRT_MAP.items():
        for fs_div in ['CFS', 'OFS']:
            try:
                rep = dc.dart.finstate_all(ticker, year, reprt_code=code, fs_div=fs_div)
                if rep is None or rep.empty: continue
                sga = rep[rep['account_id']=='dart_TotalSellingGeneralAdministrativeExpenses']
                if sga.empty: continue
                amt = pd.to_numeric(sga['thstrm_amount'].astype(str).str.replace(',',''), errors='coerce').iloc[0]
                date = pd.Timestamp(f'{year}-{month:02d}-01') + pd.offsets.MonthEnd(0)
                out[date] = amt
                break
            except Exception:
                pass
    return out

def diagnose_ticker(args):
    """종목 1개 진단 → (ticker, [잘못 분기 리스트], [정상 분기 리스트], err)
    USE_BACKUP=1 환경변수 시 백업본으로 검증 (표본 정확도 검증용)"""
    worker_idx, tk = args
    if os.environ.get('USE_BACKUP') == '1':
        # 백업 표본 8종목만 fs_dart_{tk}.parquet 별도 폴더 (직접 파일)
        # 다른 종목은 all_fs_dart 폴더
        bp = f'C:/dev/data_cache_backup_20260512/fs_dart_{tk}.parquet'
        if os.path.exists(bp):
            fp = bp
        else:
            fp = f'C:/dev/data_cache_backup_20260512/all_fs_dart/fs_dart_{tk}.parquet'
    else:
        fp = f'C:/dev/data_cache/fs_dart_{tk}.parquet'
    try:
        b = pd.read_parquet(fp)
        cache_rev = b[(b['공시구분']=='q') & (b['계정']=='매출액') & b['값'].notna()].sort_values('기준일')
        if cache_rev.empty:
            return (tk, [], [], 'no_q_rev')

        dc = collectors[worker_idx]

        # 캐시 매출이 있는 모든 분기를 검사 (year 단위로 묶어서 호출)
        cache_qtrs = {pd.Timestamp(d): float(v) * 1e8 for d, v in zip(cache_rev['기준일'], cache_rev['값'])}  # 원 단위로
        years = sorted(set(d.year for d in cache_qtrs.keys()))

        bad_qtrs = []
        ok_qtrs = []
        for yr in years:
            sga_year = get_dart_sga_year(dc, tk, yr)
            for d, cache_v in cache_qtrs.items():
                if d.year != yr: continue
                if d not in sga_year:
                    continue  # SG&A 없음 → 판정 보류
                sga_v = sga_year[d]
                # 일치 (오차 0.5% 이내) — 우연 일치 false positive 방지
                if abs(cache_v - sga_v) < max(1e6, abs(sga_v)*0.005):
                    bad_qtrs.append(d.strftime('%Y-%m'))
                else:
                    ok_qtrs.append(d.strftime('%Y-%m'))
        return (tk, bad_qtrs, ok_qtrs, None)
    except Exception as e:
        return (tk, [], [], f'ERR:{type(e).__name__}:{e}')

# 표본 8종목 검증
samples = [('042500', 'BAD'), ('024840', 'BAD'), ('046940', 'BAD'), ('072950', 'BAD'),
           ('000660', 'OK'), ('088130', 'OK'), ('196170', 'OK'), ('207940', 'OK')]

print('=== 표본 8종목 검증 (식별 알고리즘 v2) ===')
t0 = time.time()
with ThreadPoolExecutor(max_workers=3) as ex:
    args_list = [(i % 3, tk) for i, (tk, _) in enumerate(samples)]
    futs = {ex.submit(diagnose_ticker, a): a[1] for a in args_list}
    results = {}
    for fut in as_completed(futs):
        r = fut.result()
        results[r[0]] = r

print(f'\n소요: {time.time()-t0:.1f}s')
correct = 0
for tk, expected in samples:
    r = results.get(tk)
    if r is None:
        print(f'  {tk} ({expected}): 결과 없음')
        continue
    bad_q, ok_q, err = r[1], r[2], r[3]
    # 잘못 분기 2개 이상이어야 BAD (1개는 우연 일치 가능)
    actual = 'BAD' if len(bad_q) >= 2 else 'OK'
    match = '✓' if actual == expected else '✗'
    print(f'  {tk} ({expected}): {actual} {match}  bad분기={len(bad_q)} ok분기={len(ok_q)} err={err}')
    if bad_q:
        print(f'    잘못 분기: {bad_q[:5]}{"..." if len(bad_q)>5 else ""}')
    if actual == expected:
        correct += 1

print(f'\n정확도: {correct}/{len(samples)} ({100*correct/len(samples):.0f}%)')
