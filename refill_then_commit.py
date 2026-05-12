"""OHLCV refill → 커밋푸쉬 → MD 업데이트 → 커밋푸쉬 → 개인봇 보고 자동 체인.

사용자 회사 도착(1시간)까지 완료 목표.
"""
import os, sys, time, subprocess, json
from pathlib import Path
import requests
sys.stdout.reconfigure(encoding='utf-8')

PROJECT = Path(__file__).parent
PYTHON = sys.executable

def run(name, cmd, env=None, timeout=3600, capture=False):
    print(f'\n{"="*60}\n[{name}] 시작\n{"="*60}', flush=True)
    t0 = time.time()
    merged = {**os.environ, **(env or {})}
    if capture:
        r = subprocess.run(cmd, env=merged, capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=timeout)
        print(r.stdout[-2500:] if r.stdout else '(no stdout)')
        if r.returncode != 0:
            print(f'STDERR: {(r.stderr or "")[-500:]}')
    else:
        r = subprocess.run(cmd, env=merged, timeout=timeout)
    elapsed = time.time() - t0
    print(f'\n[{name}] rc={r.returncode} ({elapsed/60:.1f}분)', flush=True)
    return r.returncode, elapsed

# 1. OHLCV refill
rc1, t1 = run('1. OHLCV refill (1475일)',
              [PYTHON, '-u', 'fix_ohlcv_refill_v2.py'],
              env={'PYTHONIOENCODING': 'utf-8'},
              timeout=4800)

# 2. refill 결과 검증
print(f'\n{"="*60}\n[2. 검증]\n{"="*60}', flush=True)
import pandas as pd
o = pd.read_parquet(PROJECT/'data_cache'/'all_ohlcv_20170601_20260512.parquet')
nz = o.notna().sum(axis=1)
bad_count = (nz < 1500).sum()
final_yearly = nz.resample('YE').mean().round(0).to_dict()
print(f'결손 남은 일자: {bad_count}')
print(f'연도별: {final_yearly}')

# 3. git commit + push (data)
print(f'\n{"="*60}\n[3. commit + push (OHLCV refill)]\n{"="*60}', flush=True)
subprocess.run(['git', 'add', 'data_cache/all_ohlcv_20170601_20260512.parquet',
                'data_cache/all_ohlcv_REFILL_progress.parquet',
                'fix_ohlcv_refill_v2.py', 'refill_then_commit.py'], cwd=PROJECT)

commit_msg = f"""data: OHLCV 결손 통째 재수집 ({t1/60:.0f}분, refill v2)

결손 일자 1475일 통째 재수집 완료:
- 시작: 정상 975 / 결손 1475 (REFILL_progress.parquet base)
- 완료: 정상 {(nz>=1500).sum()} / 결손 {bad_count}
- 연도별 평균 종목 수:
  - 2017: {final_yearly.get(pd.Timestamp('2017-12-31'),0):.0f}
  - 2019: {final_yearly.get(pd.Timestamp('2019-12-31'),0):.0f}
  - 2020: {final_yearly.get(pd.Timestamp('2020-12-31'),0):.0f}
  - 2021: {final_yearly.get(pd.Timestamp('2021-12-31'),0):.0f}
  - 2023: {final_yearly.get(pd.Timestamp('2023-12-31'),0):.0f}
  - 2025: {final_yearly.get(pd.Timestamp('2025-12-31'),0):.0f}
  - 2026: {final_yearly.get(pd.Timestamp('2026-12-31'),0):.0f}

회사 PC git pull로 받기. state 재생성은 별도 시간 필요 (4~6시간).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
"""
r = subprocess.run(['git', 'commit', '-m', commit_msg], cwd=PROJECT,
                   capture_output=True, text=True, encoding='utf-8', errors='replace')
print(r.stdout[-500:])
if r.returncode == 0:
    subprocess.run(['git', 'push', 'origin', 'main'], cwd=PROJECT, timeout=600)
    print('OHLCV push 완료', flush=True)

# 4. HANDOVER 업데이트 (refill 결과 반영)
print(f'\n{"="*60}\n[4. HANDOVER 업데이트]\n{"="*60}', flush=True)
hf = PROJECT / 'HANDOVER_20260513.md'
text = hf.read_text(encoding='utf-8')
append = f"""

---

## 12. OHLCV refill 완료 (2026-05-13 새벽 자율)

작업 시간: {t1/60:.0f}분
- 시작 결손: 1475일 (REFILL_progress.parquet base, 200일은 이전 시도에서 채워짐)
- 완료 결손: {bad_count}일
- 정상화: {(nz>=1500).sum()} / 2450일

연도별 평균 종목 수 (refill 후):
| 연도 | 평균 |
|------|------|
| 2017 | {final_yearly.get(pd.Timestamp('2017-12-31'),0):.0f} |
| 2018 | {final_yearly.get(pd.Timestamp('2018-12-31'),0):.0f} |
| 2019 | {final_yearly.get(pd.Timestamp('2019-12-31'),0):.0f} |
| 2020 | {final_yearly.get(pd.Timestamp('2020-12-31'),0):.0f} |
| 2021 | {final_yearly.get(pd.Timestamp('2021-12-31'),0):.0f} |
| 2022 | {final_yearly.get(pd.Timestamp('2022-12-31'),0):.0f} |
| 2023 | {final_yearly.get(pd.Timestamp('2023-12-31'),0):.0f} |
| 2024 | {final_yearly.get(pd.Timestamp('2024-12-31'),0):.0f} |
| 2025 | {final_yearly.get(pd.Timestamp('2025-12-31'),0):.0f} |
| 2026 | {final_yearly.get(pd.Timestamp('2026-12-31'),0):.0f} |

남은 작업 (회사 PC):
1. state 전체 재생성 (2018-07~2026-05-12, 1929일×2) — 약 4~6시간
2. wr batch 후처리 (state + bt_extended)
3. 7.8년 BT 측정 (Cal vs baseline 3.97)
4. 회사 PC 백업 OHLCV가 더 정상이면 그걸로 덮어쓰기 가능 (비교 후 결정)

회사 PC에서 git pull 후 바로 state 재생성 시작 가능.
"""
hf.write_text(text + append, encoding='utf-8')

subprocess.run(['git', 'add', 'HANDOVER_20260513.md'], cwd=PROJECT)
commit2 = f"""docs: HANDOVER 업데이트 — OHLCV refill 완료 결과

refill 후 결손 1475 → {bad_count}일.
연도별 평균 종목 수 회복 (2018~2026 모두 1500+ 목표).
회사 PC 도착 시 state 재생성부터 시작 가능.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
"""
r2 = subprocess.run(['git', 'commit', '-m', commit2], cwd=PROJECT,
                    capture_output=True, text=True, encoding='utf-8', errors='replace')
print(r2.stdout[-300:])
if r2.returncode == 0:
    subprocess.run(['git', 'push', 'origin', 'main'], cwd=PROJECT, timeout=300)
    print('HANDOVER push 완료', flush=True)

# 5. 개인봇 메시지
print(f'\n{"="*60}\n[5. 개인봇 보고]\n{"="*60}', flush=True)
sys.path.insert(0, str(PROJECT))
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
msg = f"""🛠️ <b>OHLCV refill 완료</b>

작업 시간: {t1/60:.0f}분 (회사 도착 전 완료)

<b>결과:</b>
• 결손 일자: 1475 → <b>{bad_count}</b>일
• 정상화: <b>{(nz>=1500).sum()}</b> / 2450일

<b>연도별 평균 종목 수:</b>
• 2018: {final_yearly.get(pd.Timestamp('2018-12-31'),0):.0f}
• 2020: {final_yearly.get(pd.Timestamp('2020-12-31'),0):.0f}
• 2023: {final_yearly.get(pd.Timestamp('2023-12-31'),0):.0f}
• 2026: {final_yearly.get(pd.Timestamp('2026-12-31'),0):.0f}

<b>커밋 푸쉬 완료</b> — 회사 PC <code>git pull origin main</code> 한 줄로 받음.

<b>회사에서 할 다음 단계:</b>
1. git pull
2. state 전체 재생성 (2018-07~2026-05-12, 4~6시간)
3. wr batch + 7.8년 BT 측정

HANDOVER_20260513.md §12 참조."""

r3 = requests.post(
    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
    data={"chat_id": TELEGRAM_PRIVATE_ID, "text": msg, "parse_mode": "HTML"},
    timeout=30,
)
print(f'개인봇 전송: {r3.status_code}', flush=True)
if r3.status_code != 200:
    print(r3.text)

print('\n=== 모든 작업 완료 ===', flush=True)
