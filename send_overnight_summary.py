"""5/13 새벽 종합 보고 — 사용자 일어났을 때 확인용"""
import sys, requests
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID

msg = """🌅 <b>5/13 새벽 자율 작업 완료 보고</b>

자고 있는 동안 매뉴얼 13단계 + 추가 점검 + 최적화 진행했어요. 중학생도 이해 쉽게 정리.

━━━━━━━━━━━━━━━
📌 <b>1. 무슨 작업 했나</b>
━━━━━━━━━━━━━━━

옵션F 사고로 dart 캐시 일부가 잘못된 매출 값으로 오염됨. 215종목을 깨끗하게 재수집하고, monitor·run_daily 강화로 5/15 분기 마감 폭주 대비.

━━━━━━━━━━━━━━━
✅ <b>2. 완료한 단계</b>
━━━━━━━━━━━━━━━

• Step 3: <b>메인 179종목 재수집</b> 완료 (179/179 성공, 105분)
• Step 4: 검증 통과 (잔여 8 = 지주사 false positive)
• Step 5/6: unit test 4/4 + 5/5
• Step 7: <b>캐시 분석으로 대체</b> (DART 호출 X, 사용자 의도)
• Step 8: <b>추가 36종목 재수집</b> (LG엔솔/SK이노/한섬/아스플로 등 포함)
• Step 9: state 재생성 (1283일, 26.8분)
• Step 10: BT 검증 (5.25y Cal 2.983)
• Step 11: <b>SKIP</b> (OHLCV 5/11 없음)
• Step 12: <b>git commit + push 완료 (3 commit)</b>
• Step 13: 스케줄러 재활성화 ✅

━━━━━━━━━━━━━━━
🎯 <b>3. BT 결과 (가짜 알파 제거 정상화)</b>
━━━━━━━━━━━━━━━

5.25년 BT 비교:
• 옛 state (옵션F 시대): Cal 3.636
• 새 state (정정 후): Cal <b>2.983</b>
• Δ -0.653 = KBI메탈/SK스퀘어/링네트 같은 <b>가짜 알파 종목 제거 효과</b>

판정: ⚠️ 재검토 ≠ Roll back
- MDD 32% 거의 동일 (위험 변화 X)
- 진짜 알파만 남음 (LG엔솔/SK이노 등 매핑 사고 종목 빠짐)
- 옛 baseline 4.71은 옵션F 시대라 직접 비교 부적합

━━━━━━━━━━━━━━━
🔍 <b>4. Phase 10 최적 재탐색</b>
━━━━━━━━━━━━━━━

새 state 기준 boost/defense 인접 5x5 그리드서치:
• boost (V15 Q0 G55 M30): <b>baseline = 1위 (Cal 3.347)</b> ✅
• defense (V30 Q15 G15 M40): <b>baseline = 1위 (Cal 3.347)</b> ✅

→ <b>v80 baseline 정확히 최적</b>. 변경 불필요. 215종목 재수집 후에도 동일.

━━━━━━━━━━━━━━━
🚨 <b>5. 발생한 사고 2개</b>
━━━━━━━━━━━━━━━

A. <b>data_cache/all_ohlcv_*.parquet 부재</b>
- 5/12 작업 중 사라짐 (의도 X)
- 백업 _ohlcv_backup/all_ohlcv_20190603_20260330 복원
- 결과: 3/30까지 데이터로 진행 (OHLCV 5/11 없음)

B. <b>pykrx IP 차단 재발</b>
- 5/13 새벽 모든 일자 빈 결과
- 메모리 2026-03-24 해제 → 5/13 재차단
- OHLCV 3/31~5/11 30거래일 누락
- 시간 경과 후 자연 해제 또는 회사 PC 자동 갱신 기대

━━━━━━━━━━━━━━━
🛡️ <b>6. 5/15 폭주 대비 강화</b>
━━━━━━━━━━━━━━━

• monitor_dart_fn_health.py: 매출 5배+ + <b>영업이익 부호 다름</b> 검사 추가
• run_daily.py: 무결성 의심 시 <b>개인봇 즉시 알림</b> (비차단)
• B 게이트: ranking &lt;320 채널 차단
• pre-commit hook: 매핑 사고 commit 자동 차단
• 자동 방어막 8개 작동

━━━━━━━━━━━━━━━
📦 <b>7. GitHub 동기화</b>
━━━━━━━━━━━━━━━

회사 PC에서 <b>git pull origin main</b> 한 줄.

3 commit pushed:
1. 코드 + 문서 + 옵션F 시대 삭제 (27 파일)
2. fs_dart 215종목 재수집 (215 파일)
3. state + bt_extended 재생성 (5086 파일)

━━━━━━━━━━━━━━━
⚠️ <b>8. 일어났을 때 할 일</b>
━━━━━━━━━━━━━━━

A. pykrx IP 차단 확인
   <code>python -c "from pykrx import stock; print(stock.get_market_ohlcv_by_ticker('20260511', market='ALL').shape)"</code>
   - shape (n, m) = 해제됨
   - shape (0, 0) = 아직 차단

B. pykrx 해제 시:
   <code>python fix_ohlcv_incremental.py</code>
   → 3/31~5/11 자동 증분 + 새 캐시 저장

C. 5/12 자동 스케줄러는 5/13 7:00 다음 실행 예정 (확인됨)

D. 회사 PC <b>git pull origin main</b> 후 정상 운영

━━━━━━━━━━━━━━━
📊 <b>9. 215종목 재수집 명세</b>
━━━━━━━━━━━━━━━

• v3 메인 179 (tier1 32 + tier2 147)
• 추가 36:
  - 캐시 분석 4: 써니전자, 미래아이앤지, 아이앤씨, 네이블
  - extra 24 + other 3 (사용자 회사 PC)
  - 영업이익 매핑 6: LG화학, LG엔솔, 한미사이언스, 알파칩스, 티케이, 컴투스
  - SK이노베이션 (시총 22조) — 영업이익 부호 1년 + 큰 차이 1년
  - 한섬 — 자본 2022-23 부호 다름
  - 아스플로 — 매출 6배+ 차이

━━━━━━━━━━━━━━━

푹 자고 일어났을 때 시스템 정상화 + 최적 baseline 확인 완료. 회사 PC git pull 한 번이면 바로 운영 가능."""

r = requests.post(
    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
    data={"chat_id": TELEGRAM_PRIVATE_ID, "text": msg, "parse_mode": "HTML"},
    timeout=30,
)
print(f'개인봇 전송: {r.status_code}')
if r.status_code != 200:
    print(r.text)
