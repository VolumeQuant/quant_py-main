# -*- coding: utf-8 -*-
"""반기보고서 XBRL의 실제 TE 컨텍스트 덤프 — DOC 폴백 무득점 원인 특정 (삼성 2025 반기 1건)."""
import sys, io, re, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dart_collector import DartCollector, ACCOUNT_ID_MAP

dc = DartCollector()
flist = dc.dart.list('005930', start='2025-01-01', end='2026-04-30', kind='A', final=True)
cand = flist[flist['report_nm'].str.contains('반기보고서', na=False)].sort_values('rcept_no', ascending=False)
print("보고서:", cand.iloc[0]['report_nm'], cand.iloc[0]['rcept_no'])
doc = dc.dart.document(cand.iloc[0]['rcept_no'])
print("doc len:", len(doc) if doc else 0)
PAT = re.compile(r'<TE ACODE="([^"]+)" ACONTEXT="([^"]+)"[^>]*ADECIMAL="(-?\d+)"[^>]*>([^<]*)</TE>')
hits = list(PAT.finditer(doc))
print("TE 태그 총:", len(hits))
# ACCOUNT_ID_MAP에 있는 코드만
known = [(m.group(1), m.group(2), dc._parse_doc_value(m.group(4), m.group(3))) for m in hits if m.group(1) in ACCOUNT_ID_MAP]
print("맵 계정 매칭:", len(known))
for code, ctx, v in known[:25]:
    print(f"  {ACCOUNT_ID_MAP[code]:<10} ctx={ctx:<44} val={v/1e8 if v else v:,.0f}억" if v else f"  {ACCOUNT_ID_MAP[code]:<10} ctx={ctx} val=None")
# 컨텍스트 패턴 분포
from collections import Counter
cnt = Counter(re.sub(r'\d{4}', 'YYYY', c) for _, c, _ in known)
print("\n컨텍스트 패턴 분포:", dict(cnt))
