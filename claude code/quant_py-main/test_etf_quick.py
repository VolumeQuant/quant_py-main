"""ETF 매칭 빠른 테스트 — gemini_analysis.run_etf_matching 직접 호출"""
import json, sys

date = sys.argv[1] if len(sys.argv) > 1 else '20260306'
with open(f'state/ranking_{date}.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
top10 = data['rankings'][:10]

names = [f'{r.get("composite_rank", r.get("rank", i+1))}.{r["name"]}' for i, r in enumerate(top10)]
print(f'날짜: {date}')
print(' | '.join(names))

from gemini_analysis import run_etf_matching
result = run_etf_matching(top10, base_date=date)
if result:
    print('\n=== ETF 메시지 ===')
    print(result)
else:
    print('\nETF 매칭 실패')
