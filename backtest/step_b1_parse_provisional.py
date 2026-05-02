"""Phase B Step B-1 (파싱 전용): 목록 캐시 재사용 + 인코딩 수정
목록: data_cache/provisional_list_cache.json (이미 수집 완료, 8453건)
출력: data_cache/provisional_earnings.parquet
"""
import sys, os, json, time, zipfile, io
sys.stdout.reconfigure(encoding='utf-8')

import requests
import pandas as pd
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DART_API_KEY as API_KEY
PROJECT = Path(__file__).parent.parent
CACHE_DIR = PROJECT / 'data_cache'

# ── 목록 캐시 로드 (API 호출 0건) ──
cache_path = CACHE_DIR / 'provisional_list_cache.json'
with open(cache_path, 'r', encoding='utf-8') as f:
    prov_list = json.load(f)
print(f'목록 캐시 로드: {len(prov_list)}건')


def parse_document(rcept_no):
    """DART 문서 다운로드 → 매출/영업이익/순이익 추출"""
    doc_url = f"https://opendart.fss.or.kr/api/document.xml?crtfc_key={API_KEY}&rcept_no={rcept_no}"
    r = requests.get(doc_url, timeout=30)

    if len(r.content) < 100:
        return None, None, None

    z = zipfile.ZipFile(io.BytesIO(r.content))
    raw = z.read(z.namelist()[0])

    # 인코딩 감지
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

    # 모든 테이블 순회 (일부 문서는 기간+데이터 테이블 분리)
    for t in tables:
        if rev is not None and op is not None:
            break
        for idx in range(len(t)):
            row = t.iloc[idx]
            cells = [str(c).strip() if pd.notna(c) else '' for c in row]

            for ci, cell in enumerate(cells):
                # 매출액 (매출총이익 제외)
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

                # 영업이익
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

                # 당기순이익
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


# ── 표본 10건 테스트 ──
print('\n=== 표본 10건 파싱 테스트 ===')
ok_count = 0
for item in prov_list[:10]:
    time.sleep(0.15)
    try:
        rev, op, ni = parse_document(item['rcept_no'])
        status = f'매출={rev} 영업이익={op}'
        if rev is not None or op is not None:
            ok_count += 1
        print(f'  {item["name"]}({item["ticker"]}): {status}', flush=True)
    except Exception as e:
        print(f'  {item["name"]}: ERROR {str(e)[:50]}', flush=True)

print(f'  표본 성공률: {ok_count}/10 ({ok_count*10}%)', flush=True)
if ok_count < 5:
    print('  경고: 성공률 50% 미만이지만 계속 진행 (일부 종목은 월별 공시라 당해실적 없을 수 있음)')

# ── 전수 파싱 ──
print(f'\n=== 전수 파싱 ({len(prov_list)}건) ===', flush=True)
all_results = []
failed = 0
no_data = 0

for i, item in enumerate(prov_list):
    time.sleep(0.15)
    try:
        rev, op, ni = parse_document(item['rcept_no'])

        if rev is not None or op is not None:
            all_results.append({
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

    if (i + 1) % 200 == 0:
        print(f'  [{i+1}/{len(prov_list)}] 성공: {len(all_results)}건, 데이터없음: {no_data}, 실패: {failed}', flush=True)
        # 체크포인트
        pd.DataFrame(all_results).to_parquet(
            CACHE_DIR / 'provisional_earnings_checkpoint.parquet', index=False)

# ── 최종 저장 ──
print(f'\n=== 수집 완료 ===')
print(f'  성공: {len(all_results)}건')
print(f'  데이터없음: {no_data}건 (문서는 있으나 당해실적 값 없음)')
print(f'  실패: {failed}건 (다운로드/파싱 오류)')
total = len(all_results) + no_data + failed
print(f'  성공률: {len(all_results)/total*100:.1f}%' if total > 0 else '  N/A')

df = pd.DataFrame(all_results)
output_path = CACHE_DIR / 'provisional_earnings.parquet'
df.to_parquet(output_path, index=False)
print(f'  저장: {output_path}')

# 커버리지 통계
if not df.empty:
    print(f'\n=== 커버리지 통계 ===')
    print(f'  총 종목: {df["ticker"].nunique()}')
    print(f'  분기별:')
    for label, group in sorted(df.groupby('label'), key=lambda x: x[0]):
        print(f'    {label}: {len(group)}건 ({group["ticker"].nunique()}종목)')
