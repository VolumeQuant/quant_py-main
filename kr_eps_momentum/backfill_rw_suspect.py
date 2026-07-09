# -*- coding: utf-8 -*-
"""rw_suspect 과거 백필 (2026-07-10, 1회성·재실행 무해).

재작성 탐지기(history_rewrite_check)가 7/10에야 배선돼 과거 오염이 무기록 상태
→ DB 전 날짜에 소급 실행해 rw_suspect=1 마킹. 값은 절대 불변(꼬리표만).
이후 검증/BT는 `WHERE rw_suspect IS NULL OR rw_suspect=0`으로 오염 표본 제외.
"""
import sys, io, sqlite3
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from wisefn_source import history_rewrite_check

DB = 'eps_momentum_data_kr.db'

con = sqlite3.connect(DB)
for col, typ in [('ntm_src', 'TEXT'), ('rw_suspect', 'INTEGER')]:
    try:
        con.execute(f'ALTER TABLE ntm_screening ADD COLUMN {col} {typ}')
    except sqlite3.OperationalError:
        pass  # 이미 존재
dates = [r[0] for r in con.execute('SELECT DISTINCT date FROM ntm_screening ORDER BY date')]
con.execute('UPDATE ntm_screening SET rw_suspect=NULL')  # 재실행 시 이전 백필 초기화
con.commit()

total, by_ticker = 0, {}
for d in dates:
    rw = history_rewrite_check(DB, d)  # 오프라인 모드(DB 조회) — 과거 날짜는 행이 이미 존재
    if not rw:
        continue
    con.executemany('UPDATE ntm_screening SET rw_suspect=1 WHERE date=? AND ticker=?',
                    [(d, t) for t, _, _, _ in rw])
    total += len(rw)
    for t, _, _, g in rw:
        by_ticker.setdefault(t, []).append((d, g))
con.commit()

print(f'백필 완료: {len(dates)}일 스캔, 플래그 {total}건 (종목 {len(by_ticker)}개)')
print('--- 종목별 의심일수 top10 (최대 괴리%) ---')
for t, lst in sorted(by_ticker.items(), key=lambda x: -len(x[1]))[:10]:
    print(f'  {t}: {len(lst)}일, max {max(g for _, g in lst):.0f}%')
chk = con.execute('SELECT COUNT(*) FROM ntm_screening WHERE rw_suspect=1').fetchone()[0]
print(f'DB 검증: rw_suspect=1 행 {chk}건 (기대 {total})')
con.close()
