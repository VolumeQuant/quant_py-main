"""전체 1954종목 진단 → bad_tickers_v2.txt 저장

알고리즘:
- 캐시 매출 row의 2024, 2025년 분기만 검사
- DART API에서 같은 분기 SG&A 가져와 비교 (오차 0.5% 이내 → 잘못 분기)
- 종목당 잘못 분기 ≥ 2개 → BAD

호출 한도: 1954 × 2년 × 4분기 = 약 15,632 (트리플 키 59,700 안전)
"""
import sys, os, glob, time, json
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)
sys.stdout.reconfigure(encoding='utf-8')
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from dart_collector import DartCollector
from config import DART_API_KEYS

REPRT_MAP = {3: '11013', 6: '11012', 9: '11014', 12: '11011'}
DIAG_YEARS = [2024, 2025]  # 매핑 버그 영향 분기

collectors = [DartCollector(api_key=DART_API_KEYS[0])]  # 단일 키, 사용자 원칙 "DART 병렬 절대 X"

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
    _worker_idx, tk = args  # 단일 worker라 사용 안 함
    fp = f'{PROJECT_DIR}/data_cache/fs_dart_{tk}.parquet'
    try:
        b = pd.read_parquet(fp)
        cache_rev = b[(b['공시구분']=='q') & (b['계정']=='매출액') & b['값'].notna()].sort_values('기준일')
        cache_qtrs = {pd.Timestamp(d): float(v) * 1e8 for d, v in zip(cache_rev['기준일'], cache_rev['값'])}
        # 2024, 2025만 검사
        cache_qtrs = {d: v for d, v in cache_qtrs.items() if d.year in DIAG_YEARS}
        if not cache_qtrs:
            return (tk, [], [], 'no_recent_q_rev')

        dc = collectors[0]  # 단일 worker
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

# DIAG_INPUT 환경변수로 입력 파일 지정 가능 (집PC 회복 후 incomplete 재진단용)
input_file = os.environ.get('DIAG_INPUT')
if input_file and os.path.exists(input_file):
    with open(input_file, 'r') as f:
        all_tickers = [l.strip() for l in f if l.strip()]
    print(f'입력 파일: {input_file}')
else:
    all_files = sorted(glob.glob(f'{PROJECT_DIR}/data_cache/fs_dart_*.parquet'))
    all_tickers = [os.path.basename(f).replace('fs_dart_','').replace('.parquet','') for f in all_files]
    print(f'입력: 전종목 (data_cache/fs_dart_*.parquet)')
print(f'대상: {len(all_tickers)}종목')

# 결과 파일 — DIAG_INPUT 사용 시 파일명에 suffix 추가
if input_file:
    base = os.path.basename(input_file).replace('.txt','')
    OUTPUT_DETAIL = f'{PROJECT_DIR}/diagnose_{base}_detail.json'
    OUTPUT_BAD = f'{PROJECT_DIR}/bad_tickers_{base}.txt'
else:
    OUTPUT_DETAIL = os.path.join(PROJECT_DIR, 'diagnose_all_detail.json')
    OUTPUT_BAD = os.path.join(PROJECT_DIR, 'bad_tickers_v2.txt')

t0 = time.time()
results = {}
# 단일 worker 순차 진행 (사용자 원칙 "DART 병렬 절대 X" — 회사 PC IP 차단 사례 반영)
for n, tk in enumerate(all_tickers, 1):
    r = diagnose_ticker((0, tk))
    results[r[0]] = r
    if n % 100 == 0:
        elapsed = time.time() - t0
        print(f'  {n}/{len(all_tickers)} ({elapsed:.0f}s, ETA {elapsed*(len(all_tickers)-n)/n:.0f}s)', flush=True)
    time.sleep(0.3)  # 종목간 sleep

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
with open(OUTPUT_BAD, 'w', encoding='utf-8') as f:
    for tk, q in bad:
        f.write(tk + '\n')

# 상세 결과 (JSON)
detail = {tk: {'bad_qtrs': r[1], 'ok_qtrs': r[2], 'err': r[3]} for tk, r in results.items()}
with open(OUTPUT_DETAIL, 'w', encoding='utf-8') as f:
    json.dump(detail, f, ensure_ascii=False, indent=1)

print(f'\n저장: {OUTPUT_BAD} ({len(bad)}종목)')
print(f'저장: {OUTPUT_DETAIL}')
print(f'\nBAD 종목 잘못 분기수 분포:')
from collections import Counter
c = Counter(len(q) for _, q in bad)
for k in sorted(c.keys()):
    print(f'  {k}분기 잘못: {c[k]}종목')
