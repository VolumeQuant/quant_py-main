"""Phase B Step B-0: 잠정 vs 확정 괴리 EDA (Go/No-Go)
표본: 24.2Q + 25.1Q, 유니버스 겹침 종목 각 25개 = 최대 50건
"""
import sys, os, json, time, zipfile, io
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import pandas as pd
from pathlib import Path

API_KEY = '8e4325768fba382be2bb0d49d7224bd4621124a1'
CACHE_DIR = Path('data_cache')

# 유니버스 로드
with open('state/ranking_20260417.json', 'r', encoding='utf-8') as f:
    uni = set(r['ticker'] for r in json.load(f)['rankings'])
print(f'유니버스: {len(uni)}종목')

# 잠정실적 목록 수집 (2개 분기)
url = 'https://opendart.fss.or.kr/api/list.json'
samples = []

for label, bgn, end, base_dt in [
    ('24.2Q', '20240715', '20240831', '2024-06-30'),
    ('25.1Q', '20250415', '20250531', '2025-03-31'),
]:
    all_items = []
    page = 1
    while True:
        params = {
            'crtfc_key': API_KEY, 'bgn_de': bgn, 'end_de': end,
            'pblntf_ty': 'I', 'page_count': 100, 'page_no': page,
        }
        r = requests.get(url, params=params, timeout=30)
        data = r.json()
        if data.get('status') != '000':
            break
        all_items.extend(data.get('list', []))
        if page >= int(data.get('total_page', 1)):
            break
        page += 1
        time.sleep(0.15)

    prov = [x for x in all_items
            if '잠정' in x.get('report_nm', '')
            and '연결' in x.get('report_nm', '')
            and x.get('corp_cls') in ('Y', 'K')
            and '기재정정' not in x.get('report_nm', '')
            and '자회사' not in x.get('report_nm', '')]

    matched = [x for x in prov if x.get('stock_code') in uni]
    print(f'{label}: 잠정 {len(prov)}건, 유니버스 겹침 {len(matched)}건')

    for x in matched[:25]:
        samples.append({
            'label': label,
            'ticker': x['stock_code'],
            'name': x['corp_name'],
            'rcept_no': x['rcept_no'],
            'rcept_dt': x['rcept_dt'],
            'base_date': base_dt,
        })

print(f'총 표본: {len(samples)}건\n')

# 각 표본 파싱 + 비교
results = []
for i, s in enumerate(samples):
    ticker = s['ticker']
    try:
        time.sleep(0.15)
        doc_url = f"https://opendart.fss.or.kr/api/document.xml?crtfc_key={API_KEY}&rcept_no={s['rcept_no']}"
        doc_r = requests.get(doc_url, timeout=30)

        if len(doc_r.content) < 100:
            print(f'  [{i+1}/{len(samples)}] {s["name"]}({ticker}): 문서 없음')
            continue

        z = zipfile.ZipFile(io.BytesIO(doc_r.content))
        content = z.read(z.namelist()[0]).decode('utf-8', errors='replace')
        tables = pd.read_html(io.StringIO(content))

        if not tables:
            print(f'  [{i+1}/{len(samples)}] {s["name"]}({ticker}): 테이블 없음')
            continue

        t = tables[0]
        prov_rev = prov_op = None

        # 행 순회하며 매출액/영업이익 추출
        for idx in range(len(t)):
            row = t.iloc[idx]
            cells = [str(c).strip() if pd.notna(c) else '' for c in row]

            for ci, cell in enumerate(cells):
                if '매출' in cell and '총' not in cell and prov_rev is None:
                    # 다음 셀 중 첫 번째 숫자
                    for cj in range(ci + 1, len(cells)):
                        try:
                            v = float(cells[cj].replace(',', '').replace(' ', ''))
                            if abs(v) > 0:
                                prov_rev = v
                                break
                        except ValueError:
                            pass
                    if prov_rev is not None:
                        break

                if '영업이익' in cell and prov_op is None:
                    for cj in range(ci + 1, len(cells)):
                        try:
                            v = float(cells[cj].replace(',', '').replace(' ', ''))
                            prov_op = v
                            break
                        except ValueError:
                            pass
                    if prov_op is not None:
                        break

        # 확정치 (fs_dart 캐시)
        dart_path = CACHE_DIR / f'fs_dart_{ticker}.parquet'
        conf_rev = conf_op = None
        base_ts = pd.Timestamp(s['base_date'])

        if dart_path.exists():
            dart_df = pd.read_parquet(dart_path)
            q_data = dart_df[(dart_df['기준일'] == base_ts) & (dart_df['공시구분'] == 'q')]
            for _, row in q_data.iterrows():
                if row['계정'] == '매출액' and pd.notna(row['값']):
                    conf_rev = row['값']
                elif row['계정'] == '영업이익' and pd.notna(row['값']):
                    conf_op = row['값']

        # 괴리 계산 (단위 맞춤)
        # DART는 종목마다 억원 or 백만원, 잠정 HTML은 대부분 백만원
        # ratio ≈ 100 → prov=백만원, conf=억원 → prov /= 100
        # ratio ≈ 1 → 동일 단위
        # ratio ≈ 0.01 → prov=억원, conf=백만원 → conf /= 100
        def align_units(prov_val, conf_val):
            if prov_val is None or conf_val is None or prov_val == 0:
                return prov_val, conf_val
            ratio = abs(prov_val / conf_val) if conf_val != 0 else 0
            if 50 < ratio < 200:  # prov가 ~100배 큼 → prov를 100으로 나눔
                return prov_val / 100, conf_val
            elif 500 < ratio < 2000:  # prov가 ~1000배 큼
                return prov_val / 1000, conf_val
            elif 0.005 < ratio < 0.02:  # conf가 ~100배 큼
                return prov_val, conf_val / 100
            return prov_val, conf_val

        prov_rev, conf_rev = align_units(prov_rev, conf_rev)
        prov_op, conf_op = align_units(prov_op, conf_op)

        rev_gap = op_gap = None
        if prov_rev and conf_rev and conf_rev != 0:
            rev_gap = abs(prov_rev - conf_rev) / abs(conf_rev) * 100
        if prov_op is not None and conf_op is not None and conf_op != 0:
            op_gap = abs(prov_op - conf_op) / abs(conf_op) * 100

        results.append({
            'label': s['label'], 'ticker': ticker, 'name': s['name'],
            'prov_rev': prov_rev, 'conf_rev': conf_rev, 'rev_gap': rev_gap,
            'prov_op': prov_op, 'conf_op': conf_op, 'op_gap': op_gap,
        })

        parts = []
        if rev_gap is not None:
            parts.append(f'매출 {rev_gap:.1f}%')
        else:
            parts.append('매출 N/A')
        if op_gap is not None:
            parts.append(f'영업이익 {op_gap:.1f}%')
        print(f'  [{i+1}/{len(samples)}] {s["name"]}({ticker}): {" | ".join(parts)}', flush=True)

    except Exception as e:
        print(f'  [{i+1}/{len(samples)}] {s["name"]}({ticker}): ERROR {str(e)[:80]}', flush=True)

# 통계
print(f'\n{"="*50}')
print(f'괴리율 통계 ({len(results)}건)')
print(f'{"="*50}')

rev_gaps = sorted([r['rev_gap'] for r in results if r['rev_gap'] is not None])
op_gaps = sorted([r['op_gap'] for r in results if r['op_gap'] is not None])

if rev_gaps:
    n = len(rev_gaps)
    print(f'\n매출 괴리율 ({n}건):')
    print(f'  중위수:  {rev_gaps[n//2]:.2f}%')
    print(f'  평균:    {sum(rev_gaps)/n:.2f}%')
    print(f'  최소:    {rev_gaps[0]:.2f}%')
    print(f'  최대:    {rev_gaps[-1]:.2f}%')
    p95 = rev_gaps[min(int(n * 0.95), n - 1)]
    print(f'  95분위:  {p95:.2f}%')
    lt5 = sum(1 for g in rev_gaps if g < 5)
    lt10 = sum(1 for g in rev_gaps if g < 10)
    print(f'  <5%:     {lt5}/{n} ({lt5/n*100:.0f}%)')
    print(f'  <10%:    {lt10}/{n} ({lt10/n*100:.0f}%)')
    eq0 = sum(1 for g in rev_gaps if g < 0.01)
    print(f'  =0%(동일): {eq0}/{n} ({eq0/n*100:.0f}%)')

if op_gaps:
    n = len(op_gaps)
    print(f'\n영업이익 괴리율 ({n}건):')
    print(f'  중위수:  {op_gaps[n//2]:.2f}%')
    print(f'  평균:    {sum(op_gaps)/n:.2f}%')
    print(f'  최소:    {op_gaps[0]:.2f}%')
    print(f'  최대:    {op_gaps[-1]:.2f}%')

# 방향성
higher = sum(1 for r in results if r['prov_rev'] and r['conf_rev'] and r['prov_rev'] > r['conf_rev'])
lower = sum(1 for r in results if r['prov_rev'] and r['conf_rev'] and r['prov_rev'] < r['conf_rev'])
equal = sum(1 for r in results if r['prov_rev'] and r['conf_rev'] and abs(r['prov_rev'] - r['conf_rev']) < 1)
print(f'\n방향성: 잠정>확정 {higher}건, 잠정<확정 {lower}건, 동일 {equal}건')

# Go/No-Go
print(f'\n{"="*50}')
if rev_gaps:
    med = rev_gaps[len(rev_gaps)//2]
    p95 = rev_gaps[min(int(len(rev_gaps)*0.95), len(rev_gaps)-1)]
    if med < 5 and p95 < 10:
        print(f'판단: GO (중위수 {med:.1f}% < 5%, 95분위 {p95:.1f}% < 10%)')
    elif med < 10 and p95 < 20:
        print(f'판단: 조건부 GO (중위수 {med:.1f}%, 95분위 {p95:.1f}%)')
    else:
        print(f'판단: NO-GO (중위수 {med:.1f}%, 95분위 {p95:.1f}%)')
else:
    print('판단: 데이터 부족')

# 저장
with open('backtest/step_b0_gap_eda.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
print(f'\n결과 저장: backtest/step_b0_gap_eda.json')
