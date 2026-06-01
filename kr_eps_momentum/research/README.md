# KR EPS Research — 시행착오 검증 도구

US/KR 시행착오 EDA(6/1 자율주행) 결과 도출한 **공통 검증 패턴**을 KR EPS 시스템에 적용한 도구.

## 도구

### `leave_one_out.py` — Dominant winner 제외 robustness 검증
**US v83.2 교훈** 코드화: 71일 단일 표본에서 C2 boost edge가 전부 MU 한 종목 → MU 제외 시 동전던지기 → "변경 평가 시 반드시 dominant winner 제외 robustness 확인" 원칙 강제.

```bash
python kr_eps_momentum/research/leave_one_out.py --change MIN_NTM_500
```

### `multistart_bt.py` — 6시작일 표준화
**US v80.6 교훈** 코드화: 33시작일 평균이 짧은 기간 시작일로 흐려져 잘못된 결론 → 6시작일 (50거래일+ 보장) multistart로 +18%p 알파 일관 확인.

```bash
python kr_eps_momentum/research/multistart_bt.py --change MIN_NTM_500 --n_starts 6
```

### `data_monitor.py` — 데이터 누락 감지
**KR EPS 5/14 PoC 17일 멈춤 사고** 재발 방지: Task Scheduler 등록 누락 → 17일 데이터 0건 → 사용자 우연 발견. GHA cron + 이 monitor + 개인봇 알림으로 자동 감지.

```bash
python kr_eps_momentum/research/data_monitor.py --days 5 --alert
```

GHA cron에 별도 추가 가능 (매주 1회 검사).

## 사용 시점

| 도구 | 시점 |
|---|---|
| `data_monitor.py` | 매주 (또는 GHA cron) |
| `leave_one_out.py` | 변경 채택 전 |
| `multistart_bt.py` | 변경 채택 전 (60+ 누적일 필요) |

## 60일 누적 도달 후 (8월 초 예정)

KR EPS 시스템 변경 검증 시:
1. `multistart_bt.py` 6시작일 BT
2. `leave_one_out.py` dominant winner 제외 robust 확인
3. 인접 안정성 CV < 0.10 plateau 확인
4. WF 4구간 약세장 사고 패턴 X 확인
5. 모두 통과 → 채택. 하나라도 fail → reject

## 공통 검증 원칙 (US/KR EDA 결과)

- **변경 폭 작게** (롤백 용이)
- **DB backup 필수** (`bak_pre_<change>`)
- **단독 변경** (효과 분리)
- **Cal noise ±0.10** 인지
- **OOS > IS** (cherry-pick 방지)
- **롤백 트리거** 명시 (5거래일 KOSPI 알파 -3%p 또는 MDD -10%)
