"""BT 내용 오염 검증 — v77처럼 뻥튀기 종목 지배 여부

체크:
1. Top 5 지배 종목 — 특정 종목이 과도하게 Top에 머무는지
2. 솔루스첨단소재(336370) / SK스퀘어(402340) 등 뻥튀기 종목 Top 등장 여부
3. 지주사 키워드 종목의 rev_z 분포 (이슈 2: 0.0으로 통일되는지)
4. 동일 score 중복 패턴 (이슈 9: NaN vs capped 구분 실패)
5. Top 5 모멘텀 — 비정상 급등락
6. 극단값 score (|score| > 3) 출현 빈도
7. Top 종목 rank 변동성 — 너무 안 바뀌면 정체 (오염), 너무 자주 바뀌면 noise
8. 신규 상장/IPO 종목 Top 등장 — (d) 필터 실패 징후
9. 섹터 집중도 — 1개 섹터가 Top 10 지배
"""
import sys, os, json, glob
from pathlib import Path
from collections import Counter, defaultdict
sys.stdout.reconfigure(encoding='utf-8')

import pandas as pd, numpy as np

paths = [Path('C:/dev/backtest/bt_extended'), Path('C:/dev/state')]
files = []
for p in paths:
    files.extend(sorted(p.glob('ranking_*.json')))
files = sorted(files)
print(f'검증 대상: {len(files)} 파일 (2018-07~2026-04)\n')

# =============== 1. Top 5 지배 종목 ===============
print('=== 1. Top 5 최다 등장 종목 ===')
top5_counter = Counter()
top1_counter = Counter()
ticker_names = {}
for fp in files:
    d = json.load(open(fp, 'r', encoding='utf-8'))
    r = d.get('rankings', [])[:5]
    for idx, item in enumerate(r):
        tk = item.get('ticker'); nm = item.get('name')
        ticker_names[tk] = nm
        top5_counter[tk] += 1
        if idx == 0:
            top1_counter[tk] += 1

print(f'Top 5 등장 최다:')
for tk, cnt in top5_counter.most_common(15):
    pct = cnt * 100 // len(files)
    print(f'  {tk} {ticker_names.get(tk,"?"):15s}: {cnt:4d}회 ({pct}%)')

print(f'\n1위 최다:')
for tk, cnt in top1_counter.most_common(10):
    pct = cnt * 100 // len(files)
    print(f'  {tk} {ticker_names.get(tk,"?"):15s}: {cnt:4d}회 ({pct}%)')

# =============== 2. 뻥튀기 종목 등장 ===============
print(f'\n=== 2. 과거 뻥튀기 종목 (v77 이슈) 확인 ===')
suspicious = {
    '336370': '솔루스첨단소재',
    '402340': 'SK스퀘어',
    '000020': '동화약품',  # 구 지주사
}
for fp in files:
    d = json.load(open(fp, 'r', encoding='utf-8'))
    r = d.get('rankings', [])[:20]
    for item in r:
        tk = item.get('ticker')
        if tk in suspicious:
            dt = fp.stem.replace('ranking_', '')
            print(f'  {dt}: rank={item["rank"]} {tk} {item["name"]} score={item["score"]:.3f}')

# =============== 3. 지주사 rev_z 분포 (이슈 2) ===============
print(f'\n=== 3. 지주사 rev_z 분포 (이슈 2 검증) ===')
# 최근 파일 한 개로 확인
fp = files[-1]
d = json.load(open(fp, 'r', encoding='utf-8'))
holding_recs = []
for r in d.get('rankings', []):
    nm = r.get('name', '')
    if '지주' in nm or 'Holdings' in nm.upper():
        holding_recs.append(r)
print(f'{fp.name}에 지주사 {len(holding_recs)}종목:')
rev_z_vals = Counter()
for r in holding_recs[:20]:
    rz = r.get('rev_z')
    rev_z_vals[rz] += 1
    print(f'  {r["ticker"]} {r["name"]:20s} rev_z={rz} oca_z={r.get("oca_z")} score={r["score"]:.3f}')
print(f'rev_z 값 분포: {dict(rev_z_vals.most_common(5))}')

# =============== 4. 동일 score 중복 패턴 ===============
print(f'\n=== 4. 동일 score 중복 (이슈 9) ===')
dup_counts = []
for fp in files[-100:]:  # 최근 100 파일 샘플
    d = json.load(open(fp, 'r', encoding='utf-8'))
    scores = [r['score'] for r in d.get('rankings', [])]
    score_cnt = Counter([round(s, 3) for s in scores])
    max_dup = max(score_cnt.values()) if score_cnt else 0
    dup_counts.append(max_dup)
print(f'최근 100일 파일 중 동일 score 최대 종목수: '
      f'mean={sum(dup_counts)/len(dup_counts):.1f} max={max(dup_counts)}')

# =============== 5. 극단값 score ===============
print(f'\n=== 5. 극단 score ≥ 3 종목 (신뢰 의심) ===')
extreme_count = 0
extreme_samples = []
for fp in files:
    d = json.load(open(fp, 'r', encoding='utf-8'))
    for r in d.get('rankings', [])[:10]:
        s = r.get('score', 0)
        if abs(s) > 3:
            extreme_count += 1
            if len(extreme_samples) < 5:
                extreme_samples.append((fp.stem.replace('ranking_',''), r['rank'], r['ticker'], r['name'], s))
print(f'|score|>3 종목 총 등장: {extreme_count}')
for e in extreme_samples:
    print(f'  {e[0]}: rank={e[1]} {e[2]} {e[3]} score={e[4]:.3f}')

# =============== 6. Top 1 rank 변동성 ===============
print(f'\n=== 6. 최근 60일 Top 1 변동성 ===')
for fp in files[-60::10]:
    d = json.load(open(fp, 'r', encoding='utf-8'))
    r0 = d.get('rankings', [])[0] if d.get('rankings') else None
    if r0:
        dt = fp.stem.replace('ranking_','')
        print(f'  {dt}: {r0["ticker"]} {r0["name"]:15s} score={r0["score"]:.3f}')

# =============== 7. 섹터 집중도 ===============
print(f'\n=== 7. 섹터 집중도 (최근 30일 Top 10) ===')
sector_in_top10 = Counter()
for fp in files[-30:]:
    d = json.load(open(fp, 'r', encoding='utf-8'))
    for r in d.get('rankings', [])[:10]:
        sector_in_top10[r.get('sector', 'UNK')] += 1
total = sum(sector_in_top10.values())
for s, c in sector_in_top10.most_common():
    print(f'  {s:15s}: {c} ({c*100//total}%)')

# =============== 8. Top 5 내 단일 점수 지배 (특정 score 값이 다수 Top 차지) ===============
print(f'\n=== 8. 동일 score로 Top 5를 차지한 날 ===')
sus_days = 0
for fp in files:
    d = json.load(open(fp, 'r', encoding='utf-8'))
    top5_scores = [round(r['score'], 2) for r in d.get('rankings', [])[:5]]
    if len(top5_scores) >= 3:
        dup = Counter(top5_scores).most_common(1)
        if dup and dup[0][1] >= 3:
            sus_days += 1
print(f'Top 5 중 3+종목이 같은 score: {sus_days}/{len(files)}일 ({sus_days*100//len(files)}%)')

# =============== 9. 가격 극단 확인 (동전주, 이상값) ===============
print(f'\n=== 9. Top 10 내 가격 극단 (동전주 / 변칙) ===')
low_price_count = 0
for fp in files:
    d = json.load(open(fp, 'r', encoding='utf-8'))
    for r in d.get('rankings', [])[:10]:
        p = r.get('price', 0)
        if p is not None and 0 < p < 1000:  # 1천원 미만 동전주
            low_price_count += 1
print(f'Top 10 내 가격 < 1000원: {low_price_count}건')
