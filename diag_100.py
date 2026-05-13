"""랜덤 100종목 24Q1 캐시 매출액 vs DART SG&A 비교 → 잘못 비율 추정"""
import sys, os, glob, random, time
sys.path.insert(0, 'C:/dev')
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from dart_collector import DartCollector
from config import DART_API_KEYS

# 24Q1 매출 row 있는 종목만 대상
all_files = sorted(glob.glob('C:/dev/data_cache/fs_dart_*.parquet'))
all_tickers = [os.path.basename(f).replace('fs_dart_','').replace('.parquet','') for f in all_files]
print(f'전체 fs_dart: {len(all_tickers)}개')

# 랜덤 시드 고정
random.seed(20260512)
sample = random.sample(all_tickers, 100)

# 트리플 키 + 3 ThreadPool
collectors = [DartCollector(api_key=DART_API_KEYS[i]) for i in range(3)]

def check_one(args):
    worker_idx, tk = args
    fp = f'C:/dev/data_cache/fs_dart_{tk}.parquet'
    try:
        b = pd.read_parquet(fp)
        rev24 = b[(b['공시구분']=='q') & (b['계정']=='매출액') & (b['기준일']==pd.Timestamp('2024-03-31')) & b['값'].notna()]
        if rev24.empty:
            return (tk, 'no_24q1', None, None)
        cache_rev = float(rev24['값'].iloc[0])

        dc = collectors[worker_idx]
        rep = dc.dart.finstate_all(tk, 2024, reprt_code='11013', fs_div='CFS')
        if rep is None or rep.empty:
            rep = dc.dart.finstate_all(tk, 2024, reprt_code='11013', fs_div='OFS')
        if rep is None or rep.empty:
            return (tk, 'no_dart_data', cache_rev, None)

        sga = rep[rep['account_id']=='dart_TotalSellingGeneralAdministrativeExpenses']
        rev_dart = rep[rep['account_id']=='ifrs-full_Revenue']

        sga_eok = None
        if not sga.empty:
            sga_amt = pd.to_numeric(sga['thstrm_amount'].astype(str).str.replace(',',''), errors='coerce').iloc[0]
            sga_eok = sga_amt / 1e8

        rev_eok = None
        if not rev_dart.empty:
            rev_amt = pd.to_numeric(rev_dart['thstrm_amount'].astype(str).str.replace(',',''), errors='coerce').iloc[0]
            rev_eok = rev_amt / 1e8

        # 분류
        if sga_eok is not None and abs(cache_rev - sga_eok) < max(0.5, abs(sga_eok)*0.02):
            return (tk, 'BAD_sga_match', cache_rev, sga_eok, rev_eok)
        if rev_eok is not None and abs(cache_rev - rev_eok) < max(0.5, abs(rev_eok)*0.02):
            return (tk, 'OK_rev_match', cache_rev, sga_eok, rev_eok)
        return (tk, 'UNKNOWN', cache_rev, sga_eok, rev_eok)
    except Exception as e:
        return (tk, f'ERR:{type(e).__name__}', None, None)

t0 = time.time()
results = []
with ThreadPoolExecutor(max_workers=3) as ex:
    args_list = [(i % 3, tk) for i, tk in enumerate(sample)]
    futs = {ex.submit(check_one, a): a for a in args_list}
    for fut in as_completed(futs):
        results.append(fut.result())
        n = len(results)
        if n % 20 == 0:
            print(f'  진행 {n}/100 (elapsed {time.time()-t0:.1f}s)')

# 집계
cnt = {}
for r in results:
    cnt[r[1]] = cnt.get(r[1], 0) + 1
print(f'\n=== 결과 (100종목, {time.time()-t0:.1f}s) ===')
for k in sorted(cnt.keys()):
    print(f'  {k}: {cnt[k]}')

bad = [r for r in results if r[1] == 'BAD_sga_match']
print(f'\n잘못 종목 (앞 10):')
for r in bad[:10]:
    print(f'  {r[0]}: 캐시매출={r[2]:.1f}억  SG&A={r[3]:.1f}억  진짜매출={r[4] if r[4] else "-"}')

# 잘못 비율
bad_cnt = cnt.get('BAD_sga_match', 0)
ok_cnt = cnt.get('OK_rev_match', 0)
total_classified = bad_cnt + ok_cnt
if total_classified > 0:
    pct = bad_cnt / total_classified * 100
    est_total_bad = int(pct/100 * 1954)  # 전체 fs_dart 1954개
    print(f'\n분류된 {total_classified}개 중 잘못 {bad_cnt}개 = {pct:.1f}%')
    print(f'전체 1954종목 추정 잘못: ~{est_total_bad}개')
