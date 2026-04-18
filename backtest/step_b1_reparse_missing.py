"""Phase B-1 보충: 미수집 698건 재파싱 (파서 수정 — 멀티테이블 지원)
기존 7,755건에 합쳐서 저장.
"""
import sys, os, json, time, zipfile, io
sys.stdout.reconfigure(encoding='utf-8')

import requests
import pandas as pd
from pathlib import Path

API_KEY = '8e4325768fba382be2bb0d49d7224bd4621124a1'
CACHE_DIR = Path('data_cache')


def parse_document(rcept_no):
    """DART 문서 파싱 — 멀티테이블 지원 (수정됨)"""
    doc_url = f"https://opendart.fss.or.kr/api/document.xml?crtfc_key={API_KEY}&rcept_no={rcept_no}"
    r = requests.get(doc_url, timeout=30)
    if len(r.content) < 100:
        return None, None, None

    z = zipfile.ZipFile(io.BytesIO(r.content))
    raw = z.read(z.namelist()[0])

    content = None
    for enc in ['utf-8', 'euc-kr', 'cp949']:
        try:
            content = raw.decode(enc)
            if '매출' in content or '영업' in content:
                break
        except (UnicodeDecodeError, UnicodeError):
            continue
    if content is None:
        content = raw.decode('utf-8', errors='replace')

    tables = pd.read_html(io.StringIO(content))
    if not tables:
        return None, None, None

    rev = op = ni = None

    for t in tables:
        if rev is not None and op is not None:
            break
        for idx in range(len(t)):
            row = t.iloc[idx]
            cells = [str(c).strip() if pd.notna(c) else '' for c in row]

            for ci, cell in enumerate(cells):
                if '매출' in cell and '총' not in cell and '원가' not in cell and rev is None:
                    if any('당해' in c or '당기' in c for c in cells):
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
                    if any('당해' in c or '당기' in c for c in cells):
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
                    if any('당해' in c or '당기' in c for c in cells):
                        for cj in range(ci + 1, len(cells)):
                            try:
                                v = float(cells[cj].replace(',', '').replace(' ', ''))
                                ni = v
                                break
                            except ValueError:
                                pass
                    if ni is not None:
                        break

    return rev, op, ni


# 미수집 목록 로드
with open('data_cache/provisional_missing_list.json', 'r', encoding='utf-8') as f:
    missing = json.load(f)
print(f'미수집 대상: {len(missing)}건')

# 표본 5건 먼저
print('\n=== 표본 5건 ===')
ok = 0
for item in missing[:5]:
    time.sleep(0.15)
    rev, op, ni = parse_document(item['rcept_no'])
    status = f'매출={rev} 영업이익={op}'
    if rev is not None or op is not None:
        ok += 1
    print(f'  {item["name"]}({item["ticker"]}) {item["label"]}: {status}', flush=True)
print(f'  표본 성공: {ok}/5')

# 전수 파싱
print(f'\n=== 전수 재파싱 ({len(missing)}건) ===')
new_results = []
failed = 0
no_data = 0

for i, item in enumerate(missing):
    time.sleep(0.15)
    try:
        rev, op, ni = parse_document(item['rcept_no'])
        if rev is not None or op is not None:
            new_results.append({
                'ticker': item['ticker'],
                'name': item.get('name', ''),
                'label': item['label'],
                'base_date': item['base_date'],
                'rcept_dt': item['rcept_dt'],
                'revenue': rev,
                'operating_income': op,
                'net_income': ni,
            })
        else:
            no_data += 1
    except Exception:
        failed += 1

    if (i + 1) % 100 == 0:
        print(f'  [{i+1}/{len(missing)}] 성공: {len(new_results)} 없음: {no_data} 실패: {failed}', flush=True)

print(f'\n=== 재파싱 완료 ===')
print(f'  신규 성공: {len(new_results)}건')
print(f'  데이터없음: {no_data}건')
print(f'  실패: {failed}건')

# 기존 데이터와 합치기
existing = pd.read_parquet(CACHE_DIR / 'provisional_earnings.parquet')
new_df = pd.DataFrame(new_results)
combined = pd.concat([existing, new_df], ignore_index=True)
combined.to_parquet(CACHE_DIR / 'provisional_earnings.parquet', index=False)
print(f'\n합산 저장: {len(existing)} + {len(new_df)} = {len(combined)}건')

# 분기별 최종 확인
from collections import Counter
with open('data_cache/provisional_list_cache.json','r',encoding='utf-8') as f:
    full_list = json.load(f)
total_by_q = Counter(x['label'] for x in full_list)
success_by_q = Counter(combined['label'])
print(f'\n최종 수집률:')
for label in ['25.3Q', '25.4Q', '26.1Q']:
    t = total_by_q.get(label, 0)
    s = success_by_q.get(label, 0)
    pct = s / t * 100 if t > 0 else 0
    print(f'  {label}: {s}/{t} ({pct:.1f}%)')
