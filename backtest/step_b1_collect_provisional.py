"""Phase B Step B-1: 잠정실적 전수 수집 (2018~2026)
EDA에서 수집한 목록 캐시 재사용 + 유니버스 합집합 기준 문서 파싱

Output: data_cache/provisional_earnings.parquet
  컬럼: ticker, base_date, rcept_dt, 매출액, 영업이익, 당기순이익, label(분기)
"""
import sys, os, json, time, zipfile, io, glob
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import pandas as pd
from pathlib import Path
from collections import defaultdict

API_KEY = '8e4325768fba382be2bb0d49d7224bd4621124a1'
PROJECT = Path(__file__).parent.parent
CACHE_DIR = PROJECT / 'data_cache'

# ── Step 1: 유니버스 합집합 (BT 전체 기간) ──
print('=== 유니버스 합집합 추출 ===')
all_tickers = set()
ticker_names = {}

# state/ + bt_extended/ + state/defense/ + bt_extended_defense/
for pattern in ['state/ranking_*.json', 'backtest/bt_extended/ranking_*.json']:
    for fp in sorted(glob.glob(str(PROJECT / pattern))):
        try:
            with open(fp, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for r in data.get('rankings', []):
                tk = r.get('ticker', '')
                if tk:
                    all_tickers.add(tk)
                    if tk not in ticker_names:
                        nm = r.get('name', '')
                        if nm:
                            ticker_names[tk] = nm
        except Exception:
            pass

print(f'  전체 유니버스 합집합: {len(all_tickers)}종목')

# ── Step 2: 잠정실적 목록 수집 (33분기) ──
# API로 전부 수집 (EDA 때 했지만 캐시 안 저장했으므로 재수집)
print('\n=== 잠정실적 목록 수집 (33분기) ===')
url = 'https://opendart.fss.or.kr/api/list.json'

periods = []
for year in range(2018, 2027):
    periods.append((f'{year%100}.1Q', f'{year}0401', f'{year}0615', f'{year}-03-31'))
    periods.append((f'{year%100}.2Q', f'{year}0701', f'{year}0915', f'{year}-06-30'))
    periods.append((f'{year%100}.3Q', f'{year}1001', f'{year}1215', f'{year}-09-30'))
    if year < 2026:
        periods.append((f'{year%100}.4Q', f'{year+1}0101', f'{year+1}0315', f'{year}-12-31'))

periods = [(l, b, e, bd) for l, b, e, bd in periods if b >= '20180701' and b <= '20260417']

all_prov_list = []
for label, bgn, end, base_dt in periods:
    items = []
    page = 1
    while True:
        params = {
            'crtfc_key': API_KEY, 'bgn_de': bgn, 'end_de': end,
            'pblntf_ty': 'I', 'page_count': 100, 'page_no': page,
        }
        try:
            r = requests.get(url, params=params, timeout=30)
            data = r.json()
            if data.get('status') != '000':
                break
            items.extend(data.get('list', []))
            if page >= int(data.get('total_page', 1)):
                break
            page += 1
            time.sleep(0.15)
        except Exception as e:
            print(f'  {label}: API error {str(e)[:40]}')
            break

    prov = [x for x in items
            if '잠정' in x.get('report_nm', '')
            and '연결' in x.get('report_nm', '')
            and x.get('corp_cls') in ('Y', 'K')
            and '기재정정' not in x.get('report_nm', '')
            and '자회사' not in x.get('report_nm', '')]

    # 유니버스 합집합과 교차
    matched = [x for x in prov if x.get('stock_code') in all_tickers]

    for x in matched:
        all_prov_list.append({
            'label': label,
            'ticker': x['stock_code'],
            'name': x['corp_name'],
            'rcept_no': x['rcept_no'],
            'rcept_dt': x['rcept_dt'],
            'base_date': base_dt,
        })

    print(f'  {label}: {len(prov)}건 → 유니버스 겹침 {len(matched)}건', flush=True)
    time.sleep(0.15)

# 중복 제거 (같은 ticker+base_date → 최신 rcept_no만)
dedup = {}
for item in all_prov_list:
    key = (item['ticker'], item['base_date'])
    if key not in dedup or item['rcept_dt'] > dedup[key]['rcept_dt']:
        dedup[key] = item
prov_list = list(dedup.values())
print(f'\n중복 제거 후: {len(prov_list)}건 (원본 {len(all_prov_list)}건)')

# 목록 캐시 저장
list_cache = PROJECT / 'data_cache' / 'provisional_list_cache.json'
with open(list_cache, 'w', encoding='utf-8') as f:
    json.dump(prov_list, f, ensure_ascii=False, indent=1)
print(f'목록 캐시 저장: {list_cache}')

# ── Step 3: 표본 10건 파싱 테스트 ──
print(f'\n=== 표본 10건 파싱 테스트 ===')
test_results = []
for item in prov_list[:10]:
    try:
        time.sleep(0.15)
        doc_url = f"https://opendart.fss.or.kr/api/document.xml?crtfc_key={API_KEY}&rcept_no={item['rcept_no']}"
        doc_r = requests.get(doc_url, timeout=30)

        if len(doc_r.content) < 100:
            print(f'  {item["name"]}: 문서 없음')
            continue

        z = zipfile.ZipFile(io.BytesIO(doc_r.content))
        content = z.read(z.namelist()[0]).decode('utf-8', errors='replace')
        tables = pd.read_html(io.StringIO(content))

        if not tables:
            print(f'  {item["name"]}: 테이블 없음')
            continue

        t = tables[0]
        rev = op = ni = None

        for idx in range(len(t)):
            row = t.iloc[idx]
            cells = [str(c).strip() if pd.notna(c) else '' for c in row]

            for ci, cell in enumerate(cells):
                if '매출' in cell and '총' not in cell and rev is None:
                    for cj in range(ci + 1, len(cells)):
                        try:
                            v = float(cells[cj].replace(',', '').replace(' ', ''))
                            if abs(v) > 0:
                                rev = v
                                break
                        except ValueError:
                            pass
                    if rev is not None:
                        break

                if '영업이익' in cell and op is None:
                    for cj in range(ci + 1, len(cells)):
                        try:
                            v = float(cells[cj].replace(',', '').replace(' ', ''))
                            op = v
                            break
                        except ValueError:
                            pass
                    if op is not None:
                        break

                if '당기순이익' in cell and '지배' not in cell and ni is None:
                    for cj in range(ci + 1, len(cells)):
                        try:
                            v = float(cells[cj].replace(',', '').replace(' ', ''))
                            ni = v
                            break
                        except ValueError:
                            pass
                    if ni is not None:
                        break

        print(f'  {item["name"]}({item["ticker"]}): 매출={rev} 영업이익={op} 순이익={ni}')
        test_results.append({'ok': rev is not None or op is not None})

    except Exception as e:
        print(f'  {item["name"]}: ERROR {str(e)[:50]}')
        test_results.append({'ok': False})

success_rate = sum(1 for r in test_results if r['ok']) / len(test_results) * 100 if test_results else 0
print(f'  표본 성공률: {success_rate:.0f}% ({sum(1 for r in test_results if r["ok"])}/{len(test_results)})')

if success_rate < 70:
    print('  경고: 파싱 성공률 70% 미만 — 파서 개선 필요')
    # 계속 진행하되 경고

# ── Step 4: 전수 파싱 ──
print(f'\n=== 전수 파싱 ({len(prov_list)}건) ===')
all_results = []
failed = 0
checkpoint_interval = 200

for i, item in enumerate(prov_list):
    try:
        time.sleep(0.15)
        doc_url = f"https://opendart.fss.or.kr/api/document.xml?crtfc_key={API_KEY}&rcept_no={item['rcept_no']}"
        doc_r = requests.get(doc_url, timeout=30)

        if len(doc_r.content) < 100:
            failed += 1
            continue

        z = zipfile.ZipFile(io.BytesIO(doc_r.content))
        content = z.read(z.namelist()[0]).decode('utf-8', errors='replace')
        tables = pd.read_html(io.StringIO(content))

        if not tables:
            failed += 1
            continue

        t = tables[0]
        rev = op = ni = None

        for idx in range(len(t)):
            row = t.iloc[idx]
            cells = [str(c).strip() if pd.notna(c) else '' for c in row]

            for ci, cell in enumerate(cells):
                if '매출' in cell and '총' not in cell and rev is None:
                    for cj in range(ci + 1, len(cells)):
                        try:
                            v = float(cells[cj].replace(',', '').replace(' ', ''))
                            if abs(v) > 0:
                                rev = v
                                break
                        except ValueError:
                            pass
                    if rev is not None:
                        break

                if '영업이익' in cell and op is None:
                    for cj in range(ci + 1, len(cells)):
                        try:
                            v = float(cells[cj].replace(',', '').replace(' ', ''))
                            op = v
                            break
                        except ValueError:
                            pass
                    if op is not None:
                        break

                if '당기순이익' in cell and '지배' not in cell and ni is None:
                    for cj in range(ci + 1, len(cells)):
                        try:
                            v = float(cells[cj].replace(',', '').replace(' ', ''))
                            ni = v
                            break
                        except ValueError:
                            pass
                    if ni is not None:
                        break

        if rev is not None or op is not None:
            all_results.append({
                'ticker': item['ticker'],
                'name': item['name'],
                'label': item['label'],
                'base_date': item['base_date'],
                'rcept_dt': item['rcept_dt'],
                'revenue': rev,
                'operating_income': op,
                'net_income': ni,
            })

    except Exception:
        failed += 1

    if (i + 1) % checkpoint_interval == 0:
        print(f'  [{i+1}/{len(prov_list)}] 수집: {len(all_results)}건, 실패: {failed}건', flush=True)
        # 체크포인트 저장
        pd.DataFrame(all_results).to_parquet(
            CACHE_DIR / 'provisional_earnings_checkpoint.parquet', index=False)

# 최종 저장
print(f'\n=== 수집 완료 ===')
print(f'  성공: {len(all_results)}건')
print(f'  실패: {failed}건')
print(f'  성공률: {len(all_results)/(len(all_results)+failed)*100:.1f}%')

df = pd.DataFrame(all_results)
output_path = CACHE_DIR / 'provisional_earnings.parquet'
df.to_parquet(output_path, index=False)
print(f'  저장: {output_path}')

# 통계
print(f'\n=== 커버리지 통계 ===')
print(f'  총 종목: {df["ticker"].nunique()}')
print(f'  분기별:')
for label, group in df.groupby('label'):
    print(f'    {label}: {len(group)}건 ({group["ticker"].nunique()}종목)')
