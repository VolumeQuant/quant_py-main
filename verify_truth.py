"""DART API 직접 호출 → 표본 4종목 (잘못 추정) 24Q1 매출 진실 확인"""
import sys, os
sys.path.insert(0, 'C:/dev')
sys.stdout.reconfigure(encoding='utf-8')
from dart_collector import DartCollector
from config import DART_API_KEYS

dc = DartCollector(api_key=DART_API_KEYS[0])
dart = dc.dart

samples = ['042500','024840','046940','072950']
for tk in samples:
    print(f'\n=== {tk} === DART API 직접 호출 (24년 1분기 보고서)')
    try:
        # CFS 우선
        rep = dart.finstate_all(tk, 2024, reprt_code='11013', fs_div='CFS')
        if rep is None or rep.empty:
            print('  CFS 없음 → OFS 시도')
            rep = dart.finstate_all(tk, 2024, reprt_code='11013', fs_div='OFS')

        if rep is None or rep.empty:
            print('  데이터 없음')
            continue

        # 매출 관련 row만
        rev_keywords = ['매출액','수익(매출액)','영업수익','매출총액']
        for kw in rev_keywords:
            m = rep[rep['account_nm'].str.contains(kw, na=False)]
            if not m.empty:
                for _, r in m.head(3).iterrows():
                    sj = r['sj_div']
                    nm = r['account_nm']
                    val = r.get('thstrm_amount', 'N/A')
                    print(f'  [{sj}] {nm}: {val}')
                break
        # ifrs id로도 확인
        if 'account_id' in rep.columns:
            ifrs_rev = rep[rep['account_id']=='ifrs-full_Revenue']
            if not ifrs_rev.empty:
                for _, r in ifrs_rev.head(2).iterrows():
                    nm = r['account_nm']
                    val = r.get('thstrm_amount', 'N/A')
                    print(f'  [ifrs-full_Revenue] {nm}: {val}')
    except Exception as e:
        print(f'  ERROR: {e}')
