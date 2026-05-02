# 회사 PC 인수인계 — 보안 정리 (2026-05-02)

> 이 파일은 일회성 인수인계용. 회사 PC 셋업 완료 후 삭제해도 됨.

## TL;DR

- GitGuardian이 텔레그램 봇 토큰 GitHub 노출을 감지
- BotFather에서 토큰 **revoke + 새 토큰 발급** 완료
- 새 텔레그램 채널 생성 완료
- 코드에서 시크릿 하드코딩 모두 제거 → `config.py` import 패턴으로 통일
- **새 `config.py` 내용은 카톡으로 별도 전달** (이 MD에는 토큰 안 박힘)

---

## 회사 PC에서 할 일 (순서대로)

### 1. 현재 작업 상태 확인 — 충돌 예방

```bash
git status
```

만약 `M` (modified) 또는 `??` (untracked)이 보이면, 그게 무엇인지 먼저 파악할 것.

### 2. 변경분 받기

#### Case A — working tree 깨끗할 때
```bash
git pull --rebase origin main
```
끝.

#### Case B — modified/untracked가 있을 때
```bash
git stash push -u -m "before-handoff-pull"
git pull --rebase origin main
git stash pop
```

`git stash pop`에서 **conflict 발생 시** → 아래 [충돌 주의사항](#충돌-주의사항) 섹션 참조.

### 3. config.py 갱신 (가장 중요)

집 PC에서 카톡으로 보낸 `config.py` 내용을 회사 PC `config.py`에 그대로 붙여넣기:

```bash
# 기존 회사 PC config.py 백업
cp config.py config.py.bak.$(date +%Y%m%d)

# 카톡으로 받은 내용으로 덮어쓰기 (또는 클로드한테 시키기)
# 클로드한테: "카톡으로 받은 내용으로 config.py 만들어줘"
```

`config.py`는 `.gitignore` 등록되어 있으므로 **GitHub에 절대 안 올라감**. 안전.

### 4. 텔레그램 발송 테스트

```bash
python send_telegram_auto.py
```

새 채널 + 개인봇 DM 양쪽에 메시지가 정상 도착하는지 확인. 집 PC에서 4/30 기준으로 발송 성공 검증함.

### 5. 인수인계 끝났으면 이 파일 삭제

```bash
git rm OFFICE_PC_HANDOFF.md
git commit -m "chore: remove handoff doc after office PC sync"
git push
```

---

## 변경된 파일 (이번 commit, 17개)

### 봇 토큰 하드코딩 제거 (13개)
- `backtest/cooldown_grid.py`
- `backtest/dart_disclosure_eda.py`
- `backtest/foreign_investor_eda.py`
- `backtest/improvement_test.py`
- `backtest/realtime_signal_eda.py`
- `backtest/step11_dur90_retest.py`
- `backtest/step11_extreme_surprise.py`
- `backtest/step11_prov_methods.py`
- `backtest/step12_final_recheck.py`
- `backtest/stoploss_trailing_grid.py`
- `backtest/v80_master_search.py`
- `backtest/wf_stability_test.py`

패턴 변경:
```python
# 이전
BOT = '<옛 토큰>'
PID = '7580571403'

# 이후
from config import TELEGRAM_BOT_TOKEN as BOT, TELEGRAM_PRIVATE_ID as PID
```

(또는 `BOT_TOKEN/PRIVATE_ID` 변수명을 쓰는 5개 파일에서는 동일 패턴의 alias)

### DART API 키 하드코딩 제거 (4개)
- `backtest/step_b0_gap_eda.py`
- `backtest/step_b1_collect_provisional.py`
- `backtest/step_b1_parse_provisional.py`
- `backtest/step_b1_reparse_missing.py`

```python
# 이전
API_KEY = '<옛 DART 키>'

# 이후
from config import DART_API_KEY as API_KEY
```

### 신규 파일 (1개)
- `config.example.py` — 회사 PC 셋업용 placeholder 템플릿. `.gitignore`에 안 잡힘 (트래킹됨).

---

## 충돌 주의사항

### 회사 PC에 위 17개 파일 중 modified가 있을 때

`git stash pop` 시 conflict 가능. 처리 원칙:

1. **절대 옛 토큰이 박힌 버전을 채택하지 말 것**
   - 옛 봇 토큰은 BotFather에서 이미 revoke되어 작동 안 함
   - 옛 DART 키는 살아있지만 어차피 모든 코드는 `config.py`로 통일하기로 함
2. **충돌 시 정답**: `from config import ... ` 패턴이 들어간 새 버전(HEAD = origin) 채택
3. 회사 PC만의 추가 변경분(예: 함수 로직 수정)이 같은 파일에 있다면 → 새 버전(import 패턴) 위에 그 변경분만 다시 얹기

```bash
# conflict 해결 예시 (origin 버전 채택)
git checkout --theirs <파일경로>   # stash pop 컨텍스트에선 theirs = stash, ours = HEAD
# 정확히는 ours = pull로 받은 새 버전이므로 ours 채택
git checkout --ours <파일경로>
git add <파일경로>
```

> 참고: `git stash pop` conflict 시 `ours` = HEAD(=origin 새 버전), `theirs` = stash(=회사 PC 옛 변경분).
> 이번 케이스는 거의 항상 `--ours` (시크릿 제거된 새 버전) 채택이 정답.

### state/ 또는 data_cache/ 충돌

자동 생성 데이터라 origin 버전(=가장 최신 16시 push) 채택이 안전:
```bash
git checkout --ours state/web_data_<날짜>.json
git add state/web_data_<날짜>.json
```

---

## 옛 토큰 / 옛 키 처리 정책

- **옛 봇 토큰**: BotFather revoke 완료 → 무력화. git history에 박혀있어도 무용지물.
- **옛 DART API 키**: 노출됐지만 무료 API라 큰 위험 X. 그래도 새 코드는 `config.py` 통일.
- **git history 재작성(force push) X**: 부작용이 더 큼. 옵션 A로 결정 (revoke만으로 충분).

---

## 회사 PC 클로드코드한테 던질 한 마디 (참고)

> "오늘 보안 사고로 텔레그램 봇 토큰 새로 발급받았고 채널도 새로 만들었어.
> `OFFICE_PC_HANDOFF.md` 보고 단계대로 진행해줘. 카톡으로 새 `config.py` 내용 보낼 거니까 거기 그대로 적용하면 돼.
> conflict 나면 그 MD의 충돌 주의사항 섹션 참고해서 처리."
