# TTM PER/ROE 밸류 팩터 — 끝장 검증 종합 (2026-06-15~16)

> **회사PC 인수인계용.** 집PC에서 밤샘으로 진행한 TTM 밸류 검증 전체. PULL 후 이 문서만 읽으면 무엇을 왜 했고 결론이 무엇인지 다 파악 가능. 재현 스크립트·데이터 위치 포함.

---

## 0. 한 줄 결론
**annual PER 유지가 맞다.** 고정 운영 config에서 annual이 TTM을 일관되게 살짝 이김(−0.2). "TTM이 더 좋다"고 잠깐 보였던 건 **max-selection 편향**(많은 config 최적화 시 우연히 높은 게 골라짐)이었고, 가격파일만 바꿔도(+0.61→+0.05) 무너졌다. **production 무변경.**

---

## 1. 질문
밸류 4팩터(PER/PBR/PCR/PSR) 중 **PER만 연간(pykrx, 작년 기준)**이고 PCR/PSR은 TTM(최근 4분기)이라 짝짝이. "PER도 TTM으로 바꾸면(ROE도) 더 좋지 않냐?" (사용자 제기). 직관: 최신 데이터가 더 정확하니 더 좋아야 함.

## 2. 데이터 (모두 커밋됨, 재생성 불필요)
| 폴더 | 내용 | 생성 env |
|---|---|---|
| `state/` | production annual (true PIT, gold standard) | — |
| `_sp2/` | 가중TTM (USE_SELF_PER/ROE, 최근가중, **overheat 미저장**) | USE_SELF_PER=1 USE_SELF_ROE=1 |
| `_sp3/` | 균등TTM (+TTM_FUND_EQUAL, overheat 저장) | +TTM_FUND_EQUAL=1 STORE_OVERHEAT_PEN=1 |
| `_sp0b/` | annual 재생성 (오늘 데이터, overheat 저장, 최근가중) | STORE_OVERHEAT_PEN=1 |
| `_sp2b/` | TTM 재생성 (_sp0b와 **같은 배치**, overheat 저장) | USE_SELF_PER=1 USE_SELF_ROE=1 STORE_OVERHEAT_PEN=1 |

★ **같은배치 비교는 `_sp0b`(annual) vs `_sp2b`(TTM)** — 둘 다 오늘 데이터·STORE_PEN·최근가중, USE_SELF_PER만 차이 → value isolation.

## 3. 검증 스크립트 (backtest/)
| 스크립트 | 역할 | 결과파일 |
|---|---|---|
| `_sp_ttm_final.py` | 균등TTM 멀티팩터×과열×E/X/S 최적화 | `_sp_ttm_final_result.txt` |
| `_sp_ortho_value.py` | fresh-orthogonal 밸류(평균회귀·G/M잔차·과열잔차) BT | `_sp_ortho_value_result.txt` |
| `_sp_clean_value.py` | _sp3 맥락에 annual value 주입(confound 발견) | — |
| `_sp_clean_final2.py` | _sp0b vs _sp2b 같은배치 비교(V0 불일치=빈티지) | — |
| `_sp_proper_opt.py` | ★밸류강제 V≥10 + 멀티팩터×슬롯 최적 (OPT_LO/HI env로 표본) | — |
| `_sp_wf_value.py` | WF 기간분할(약세장 포함) | — |
| `_sp_validate.py` | ★가격민감도+인접CV+LOWO (결론 확정) | — |
| `_sp_overheat_annual.py` | annual 과열캡 ON/OFF (+0.94 확인) | — |
> ⚠️ TurboSim은 **폴더당 1회 생성 + `_ensure_cache` 슬롯간 재사용**(슬롯은 캐시키 아님). 슬롯마다 재생성하면 8배 느림(초기 _sp_proper_opt 버그였음, 수정됨).

## 4. 여정 (틀린 설명 4개 + 편향 1개)
1. **회사PC 1차**: annual 3.59 > TTM 3.01 (같은배치, 풀그리드). 사용자 "납득 안 간다, 버그 아니냐".
2. **집PC 심층**: 균등TTM·과열on/off·E/X/S 다 해도 annual 승. but TTM best가 **V0**(밸류 안 씀) → 불공정 비교 지적받음.
3. **메커니즘 사냥(다 틀림)**:
   - "TTM이 G/M과 중복" → 측정상 TTM이 **더 직교**(annual corr -0.146 vs TTM -0.069). 틀림.
   - "annual이 더 예측적" → **IC 동일**(annual 0.030 ≈ TTM 0.028 @20d). 틀림.
   - "TTM outlier" → **분포 동일**. 틀림.
   - "value-과열캡 중복" → 같은배치 재검증서 노이즈에 묻힘.
4. **밸류 강제(V≥10)+최적화**: TTM이 +0.61 우위, WF 약세장서도 +0.98~1.09 → **흥분(형 직감 맞나?)**.
5. **견고성 검증(_sp_validate)**: ★**가격파일만 바꿔도 +0.61→+0.05 붕괴**. 고정 운영config에선 annual이 −0.2/−0.25 **일관 승**. → +0.61은 **max-selection 편향**이었음. 회사PC 결론 확정.

## 5. 최종 수치 (`_sp_validate.py`)
| | best config (최적화, 편향有) | 고정 운영config(공정) |
|---|---|---|
| 가격파일 A | TTM +0.61 | **annual +0.20** |
| 가격파일 B | TTM +0.05 | **annual +0.25** |
- 인접CV(TTM best) 0.234(이웃 0.90~2.08, 들쭉날쭉). LOWO Δ+0.05~0.20(노이즈).
- 과열캡은 annual에 +0.94(3.79 vs 2.84), TTM엔 거의 0(시총/TTM순이익 기반이라 TTM value와 중복).

## 6. ★핵심 교훈 (앞으로 모든 팩터실험에 적용)
1. **max-selection 편향**: 두 방법을 "각자 최적화한 best끼리" 비교하면 안 됨 — 많이 뒤지면 우연히 높은 게 골라져 부풀려짐. **고정 config 비교 + 다른 prices/기간 out-of-sample 검증** 필수.
2. **3종목 집중 = BT 노이즈 ±0.3~0.5**. 작은 차이는 노이즈. 데이터 빈티지·prices·재생성 비결정성이 증폭됨.
3. **IC가 노이즈 없는 유일한 팩터비교 척도**. (annual≈TTM 동등).
4. 표본먼저 + TurboSim 1회로드 재사용은 필수.

## 7. 결정
**production 무변경(annual PER 유지).** USE_SELF_PER/USE_SELF_ROE/TTM_FUND_EQUAL/STORE_OVERHEAT_PEN 플래그는 default off(재실험용 보존). 6/15 production은 PURE하게 채널 발송 완료(별개).

## 8. 재현 방법 (회사PC)
```
# 같은배치 공정비교 (핵심)
python backtest/_sp_validate.py          # 가격민감도+인접CV+LOWO → annual 우위 확인
python backtest/_sp_proper_opt.py        # 밸류강제 최적화 (max-selection 편향 재현)
OPT_LO=20240101 OPT_HI=20261231 python backtest/_sp_proper_opt.py  # 표본
python backtest/_sp_wf_value.py          # WF 기간분할
```
(회사PC 자체 같은배치 재생성을 원하면: STORE_OVERHEAT_PEN=1 [USE_SELF_PER=1 USE_SELF_ROE=1] fast_generate_rankings_v2.py LO HI --state-dir _spXX)
