# -*- coding: utf-8 -*-
"""KRX MDC 시장경보/단기과열/관리종목 fetch 가능성 탐침.
krx_auth 인증세션으로 getJsonData.cmd 호출. 메커니즘 확인(MDCSTAT01501) + 경보 bld 후보."""
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, r'C:\dev')
import krx_auth
ok = krx_auth.login()
print('로그인:', ok)
S = krx_auth._session
URL = 'https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd'

def probe(name, bld, extra):
    try:
        d = {'bld': bld, 'locale': 'ko_KR', **extra}
        r = S.post(URL, data=d, timeout=20)
        txt = r.text[:120]
        try:
            j = r.json()
            # 데이터 블록 추정
            keys = list(j.keys())
            rows = None
            for k in keys:
                if isinstance(j[k], list) and j[k]:
                    rows = j[k]; rk = k; break
            n = len(rows) if rows else 0
            sample = rows[0] if rows else {}
            print(f'[{name}] HTTP{r.status_code} keys={keys[:5]} rows={n}' + (f' (블록 {rk}, 샘플키 {list(sample.keys())[:6]})' if rows else f' | {txt[:80]}'))
        except Exception:
            print(f'[{name}] HTTP{r.status_code} non-JSON: {txt[:80]}')
    except Exception as e:
        print(f'[{name}] ERR {type(e).__name__}: {str(e)[:80]}')

# 1) 메커니즘 확인 — 잘 알려진 전종목시세
probe('전종목시세(확인)', 'dbms/MDC/STAT/standard/MDCSTAT01501', {'mktId':'ALL','trdDd':'20260610','share':'1','money':'1'})
# 2) 경보/과열/관리 bld 후보들
for nm, bld, ex in [
    ('관리종목 후보1', 'dbms/MDC/STAT/standard/MDCSTAT03901', {'mktId':'ALL'}),
    ('투자주의 후보', 'dbms/MDC/STAT/standard/MDCSTAT13501', {'mktId':'ALL','trdDd':'20260610'}),
    ('시장경보 후보', 'dbms/MDC/STAT/standard/MDCSTAT13701', {'mktId':'ALL','trdDd':'20260610'}),
    ('단기과열 후보1', 'dbms/MDC/STAT/standard/MDCSTAT13201', {'mktId':'ALL','trdDd':'20260610'}),
    ('단기과열 후보2', 'dbms/MDC/STAT/standard/MDCSTAT11001', {'mktId':'ALL','trdDd':'20260610'}),
]:
    probe(nm, bld, ex)
