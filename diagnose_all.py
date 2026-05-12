"""전체 1954종목 진단 → bad_tickers_v2.txt 저장

알고리즘:
- 캐시 매출 row의 2024, 2025년 분기만 검사
- DART API에서 같은 분기 SG&A 가져와 비교 (오차 0.5% 이내 → 잘못 분기)
- 종목당 잘못 분기 ≥ 2개 → BAD

호출 한도: 1954 × 2년 × 4분기 = 약 15,632 (트리플 키 59,700 안전)
"""
import sys, os, glob, time, json
sys.path.insert(0, 'C:/dev')
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from dart_collector import DartCollector
from config import DART_API_KEYS

REPRT_MAP = {3: '11013', 6: '11012', 9: '11014', 12: '11011'}
DIAG_YEARS = [2024, 2025]  # 매핑 버그 영향 분기

collectors = [DartCollector(api_key=DART_API_KEYS[i]) for i in range(3)]

def get_dart_sga_year(dc, ticker, year):
    out = {}
    for month, code in REPRT_MAP.items():
        for fs_div in ['CFS', 'OFS']:
            try:
                rep = dc.dart.finstate_all(ticker, year, reprt_code=code, fs_div=fs_div)
                if rep is None or rep.empty: continue
                sga = rep[rep['account_id']=='dart_TotalSellingGeneralAdministrativeExpenses']
                if sga.empty: continue
                amt = pd.to_numeric(sga['thstrm_amount'].astype(str).str.replace(',',''), errors='coerce').iloc[0]
                if pd.isna(amt): continue
                date = pd.Timestamp(f'{year}-{month:02d}-01') + pd.offsets.MonthEnd(0)
                out[date] = amt
                break
            except Exception:
                pass
    return out

def diagnose_ticker(args):
    worker_idx, tk = args
    fp = f'C:/dev/data_cache/fs_dart_{tk}.parquet'
    try:
        b = pd.read_parquet(fp)
        cache_rev = b[(b['공시구분']=='q') & (b['계정']=='매출액') & b['값'].notna()].sort_values('기준일')
        cache_qtrs = {pd.Timestamp(d): float(v) * 1e8 for d, v in zip(cache_rev['기준일'], cache_rev['값'])}
        # 2024, 2025만 검사
        cache_qtrs = {d: v for d, v in cache_qtrs.items() if d.year in DIAG_YEARS}
        if not cache_qtrs:
            return (tk, [], [], 'no_recent_q_rev')

        dc = collectors[worker_idx]
        years = sorted(set(d.year for d in cache_qtrs.keys()))
        bad_qtrs = []
        ok_qtrs = []
        for yr in years:
            sga_year = get_dart_sga_year(dc, tk, yr)
            for d, cache_v in cache_qtrs.items():
                if d.year != yr: continue
                if d not in sga_year: continue
                sga_v = sga_year[d]
                if abs(cache_v - sga_v) < max(1e6, abs(sga_v)*0.005):
                    bad_qtrs.append(d.strftime('%Y-%m'))
                else:
                    ok_qtrs.append(d.strftime('%Y-%m'))
        return (tk, bad_qtrs, ok_qtrs, None)
    except Exception as e:
        return (tk, [], [], f'ERR:{type(e).__name__}')

all_files = sorted(glob.glob('C:/dev/data_cache/fs_dart_*.parquet'))
all_tickers = [os.path.basename(f).replace('fs_dart_','').replace('.parquet','') for f in all_files]
print(f'대상: {len(all_tickers)}종목')

t0 = time.time()
results = {}
with ThreadPoolExecutor(max_workers=3) as ex:
    args_list = [(i % 3, tk) for i, tk in enumerate(all_tickers)]
    futs = {ex.submit(diagnose_ticker, a): a[1] for a in args_list}
    n = 0
    for fut in as_completed(futs):
        r = fut.result()
        results[r[0]] = r
        n += 1
        if n % 200 == 0:
            elapsed = time.time() - t0
            print(f'  {n}/{len(all_tickers)} ({elapsed:.0f}s, ETA {elapsed*(len(all_tickers)-n)/n:.0f}s)')

# 집계
bad = []
ok = []
no_data = []
err = []
for tk, r in results.items():
    bad_q, ok_q, e = r[1], r[2], r[3]
    if e and e != 'no_recent_q_rev':
        err.append(tk)
    elif e == 'no_recent_q_rev':
        no_data.append(tk)
    elif len(bad_q) >= 2:
        bad.append((tk, bad_q))
    else:
        ok.append(tk)

print(f'\n=== 결과 ({time.time()-t0:.0f}s) ===')
print(f'  BAD (잘못 분기 ≥2): {len(bad)}')
print(f'  OK              : {len(ok)}')
print(f'  no_recent_q_rev : {len(no_data)}')
print(f'  err             : {len(err)}')

# 저장
with open('C:/dev/bad_tickers_v2.txt', 'w', encoding='utf-8') as f:
    for tk, q in bad:
        f.write(tk + '\n')

# 상세 결과 (JSON)
detail = {tk: {'bad_qtrs': r[1], 'ok_qtrs': r[2], 'err': r[3]} for tk, r in results.items()}
with open('C:/dev/diagnose_all_detail.json', 'w', encoding='utf-8') as f:
    json.dump(detail, f, ensure_ascii=False, indent=1)

print(f'\n저장: bad_tickers_v2.txt ({len(bad)}종목)')
print(f'저장: diagnose_all_detail.json')
print(f'\nBAD 종목 잘못 분기수 분포:')
from collections import Counter
c = Counter(len(q) for _, q in bad)
for k in sorted(c.keys()):
    print(f'  {k}분기 잘못: {c[k]}종목')
