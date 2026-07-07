# -*- coding: utf-8 -*-
"""8월 반기 시즌 사전점검 — document API 폴백이 H1에서 dFQQ(3개월단독) vs dFQA(반기누적) 중 뭘 집는지 표본검증.
Q1은 단독=누적이라 기존 검증으로 안 보임. 2025 반기보고서 3종목으로 실제 XBRL 순서 확인."""
import sys, io, re, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dart_collector import DartCollector, ACCOUNT_ID_MAP

dc = DartCollector()
PAT = re.compile(r'<TE ACODE="([^"]+)" ACONTEXT="([^"]+)"[^>]*ADECIMAL="(-?\d+)"[^>]*>([^<]*)</TE>')

for ticker in ['005930', '000660', '036190']:
    print(f"\n=== {ticker} 2025 H1 ===")
    # 폴백이 실제로 반환하는 값
    accounts, rcept = dc._fetch_quarter_via_document(ticker, 2025, '11012')
    print(f"  폴백 반환 (rcept {rcept}): 매출={accounts.get('매출액')}, 영업이익={accounts.get('영업이익')} (억)")
    # finstate_all 정상 경로 값과 비교
    try:
        import time; time.sleep(1)
        df = dc._api_call(ticker, 2025, reprt_code='11012', fs_div='CFS')
        main = dc._extract_accounts(df) if df is not None and len(df) else {}
        print(f"  finstate_all 정상경로: 매출={main.get('매출액')}, 영업이익={main.get('영업이익')} (억)")
    except Exception as e:
        print("  finstate_all 비교 실패:", e)
    # XBRL 원문에서 매출 계정의 컨텍스트 등장 순서
    try:
        import time; time.sleep(1)
        flist = dc.dart.list(ticker, start='2025-01-01', end='2026-04-30', kind='A', final=True)
        cand = flist[flist['report_nm'].str.contains('반기보고서', na=False)].sort_values('rcept_no', ascending=False)
        doc = dc.dart.document(cand.iloc[0]['rcept_no'])
        rev_codes = [k for k, v in ACCOUNT_ID_MAP.items() if v == '매출액']
        seq = []
        for m in PAT.finditer(doc):
            if m.group(1) in rev_codes and 'ConsolidatedMember' in m.group(2):
                ctx = m.group(2); base = re.match(r'(CFY\d{4}[de](?:FQQ|FQA|FQ|SFQ|TFQ|SFA|TFA|FY|AFA))', ctx)
                seq.append((base.group(1) if base else ctx[:20], dc._parse_doc_value(m.group(4), m.group(3))))
        print("  매출 TE 등장순서(연결):", [(c, f"{v/1e8:,.0f}억" if v else v) for c, v in seq[:6]])
    except Exception as e:
        print("  원문 순서 확인 실패:", e)
