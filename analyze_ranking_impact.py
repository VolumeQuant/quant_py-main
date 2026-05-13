"""5/11 ranking에 BAD 종목 영향 분석 (DART 호출 0)

질문:
- 5/11 ranking Top 50에 BAD 179종목 중 몇 개 진입?
- 그 종목들 cr 위치는?
- 재수집 후 가짜 알파 제거되면 ranking 어떻게 바뀔지 추정
"""
import sys, json
sys.path.insert(0, 'C:/dev')
sys.stdout.reconfigure(encoding='utf-8')

# BAD 리스트
with open('C:/dev/bad_tickers_v3.txt') as f:
    bad = set(l.strip() for l in f if l.strip())
print(f'BAD 종목: {len(bad)}')

# 5/11 ranking — 옵션F + 표본 4종목 재수집 후 (state_sample)
# 옵션F + 표본 재수집 전 (state)
for path, label in [
    ('C:/dev/state/ranking_20260511.json', 'state (옵션F만)'),
    ('C:/dev/state_sample/ranking_20260511.json', 'state_sample (옵션F + 표본 4 재수집)'),
]:
    try:
        r = json.load(open(path, encoding='utf-8'))
    except FileNotFoundError:
        print(f'\n--- {label} --- 파일 없음 (skip)')
        continue
    rankings = r.get('rankings', [])
    print(f'\n=== {label} ===')
    print(f'전체 종목: {len(rankings)}')

    # Top 50 중 BAD 종목
    bad_in_top50 = []
    for i, x in enumerate(rankings[:50]):
        tk = x.get('ticker')
        if tk in bad:
            bad_in_top50.append((i+1, tk, x.get('name','')))

    print(f'Top 50 중 BAD: {len(bad_in_top50)}')
    for cr, tk, nm in bad_in_top50:
        print(f'  cr {cr:>3}: {tk} {nm}')

    # 더 넓게 — Top 100 중 BAD
    bad_in_top100 = sum(1 for x in rankings[:100] if x.get('ticker') in bad)
    print(f'Top 100 중 BAD: {bad_in_top100}')

    # 진입 (Top 3) 종목 영향
    top3 = [(x.get('ticker'), x.get('name','')) for x in rankings[:3]]
    print(f'\nTop 3 진입 후보:')
    for tk, nm in top3:
        is_bad = '🚨 BAD' if tk in bad else ''
        print(f'  {tk} {nm} {is_bad}')

# defense ranking도 같은 분석
print(f'\n--- defense state ranking ---')
try:
    r_def = json.load(open('C:/dev/state/defense/ranking_20260511.json', encoding='utf-8'))
    rankings = r_def.get('rankings', [])
    bad_in_top50 = [(i+1, x.get('ticker'), x.get('name','')) for i, x in enumerate(rankings[:50]) if x.get('ticker') in bad]
    print(f'defense Top 50 중 BAD: {len(bad_in_top50)}')
    for cr, tk, nm in bad_in_top50[:15]:
        print(f'  cr {cr:>3}: {tk} {nm}')
except FileNotFoundError:
    print('defense ranking 없음')
