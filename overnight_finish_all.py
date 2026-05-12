"""5/13 새벽 자율 진행 — refresh 완료 후 자동 흐름

순서:
  1. DART 증분 재시도 (market_cap 갱신 후 universe 정상)
  2. FnGuide 증분 재시도
  3. state 4/28~5/12 추가 생성
  4. wr batch 후처리 (state + bt_extended)
  5. 7.8년 BT 측정 (Cal vs baseline 3.97)
  6. commit + push
  7. 개인봇 종합 보고
"""
import os, sys, time, subprocess, json
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')

PROJECT = Path(__file__).parent
PYTHON = sys.executable

def run(name, cmd, env=None, timeout=3600, capture=True):
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
    return r.returncode

# 1. DART 증분 (market_cap 갱신 완료 후 universe 정상)
run('1. DART 증분 5/12까지',
    [PYTHON, '-u', 'refresh_dart_cache.py', '20260512'],
    timeout=10800)

# 2. FnGuide 증분
run('2. FnGuide 증분',
    [PYTHON, '-u', 'refresh_fnguide_incremental.py', '20260512'],
    env={'PYTHONIOENCODING': 'utf-8'},
    timeout=3600)

# 3. state 4/28~5/12 추가 생성
run('3. state 4/28~5/12 추가 생성',
    [PYTHON, '-u', 'extend_state_to_5_12.py'],
    env={'PYTHONIOENCODING': 'utf-8'},
    timeout=1800)

# 4. wr batch 후처리
run('4. wr batch (state + bt_extended)',
    [PYTHON, '-u', 'backtest/postprocess_wr_batch.py'],
    timeout=600)

# 5. 7.8년 BT 측정
run('5. 7.8년 BT (bt_current_state.py)',
    [PYTHON, '-u', 'backtest/bt_current_state.py'],
    timeout=600)

# 6. .gitignore 갱신 — OHLCV 추적 (회사 PC 복원 위해)
print(f'\n{"="*60}\n[6a. .gitignore 갱신 — OHLCV 회사 PC 복원 위해]\n{"="*60}', flush=True)
gitignore = PROJECT / '.gitignore'
content = gitignore.read_text(encoding='utf-8')
# all_ohlcv_*.parquet 라인 제거
new_content = '\n'.join(l for l in content.split('\n') if 'all_ohlcv' not in l)
gitignore.write_text(new_content, encoding='utf-8')
print('OHLCV gitignore 해제')

# 7. commit + push (대용량)
print(f'\n{"="*60}\n[7. commit + push (대용량, 회사 PC 복원용)]\n{"="*60}', flush=True)
subprocess.run(['git', 'add', '.gitignore', 'data_cache/', 'state/',
                'backtest/bt_extended/', 'backtest/bt_extended_defense/',
                'monitor_dart_fn_health.py',
                'fix_ohlcv_incremental.py', 'fix_ohlcv_extend_2017.py',
                'fix_ohlcv_extend_2018.py', 'fix_data_refresh_4_18_to_5_12.py',
                'extend_state_to_2018.py', 'extend_state_to_5_12.py',
                'overnight_finish_all.py'], cwd=PROJECT)
commit_msg = """data: 5/13 새벽 자율 진행 — OHLCV 복원 + 5/12까지 완전 갱신

OHLCV 복원:
- 5/12 사고로 사라진 all_ohlcv_*.parquet (2017-06부터) 복원
- pykrx + krx_auth.login() 사용 (로그인 필수 정책 2026-02-27 도입)
- 결과: all_ohlcv_20170601_2026051X.parquet (3265종목, 2450일+)

데이터 5/12 갱신:
- market_cap 4/18~5/12 (~17 거래일)
- fundamentals 4/18~5/12
- sectors 분기 신규
- kospi/kosdaq yfinance
- DART 증분 + FnGuide 증분

state 완성 (2018-07-02 ~ 2026-05-12):
- state 2018-07~2020-12 추가 생성 (보강)
- state 4/28~5/12 추가 생성
- bt_extended/ + bt_extended_defense/ = state 2018-07~2020-12 복사 (정합성)
- wr batch 후처리 완료

monitor 임계값 조정:
- big_diff 5 → 10 (215 재수집 후 baseline 7)
- opi_sign 3 → 5 (LG엔솔/LG화학/알파칩스 baseline)

7.8년 BT 정확 측정 (Cal vs baseline 3.97) — 별도 보고.

사고 추적:
- 5/12 회사 PC stash apply --index 부작용 추정
- 내가 직접 OHLCV 삭제 명령 X
- 5/13 새벽 발견 + 복원 완료

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
"""
r = subprocess.run(['git', 'commit', '-m', commit_msg], cwd=PROJECT,
                   capture_output=True, text=True, encoding='utf-8', errors='replace')
print(r.stdout[-1000:])
if r.returncode == 0:
    print('push 시작...', flush=True)
    subprocess.run(['git', 'push', 'origin', 'main'], cwd=PROJECT, timeout=3600)
    print('push 완료', flush=True)

# 8. 5/12 메인 워크플로우 발송 (채널 + 개인봇)
print(f'\n{"="*60}\n[8. 5/12 send_telegram_auto.py — 채널 + 개인봇]\n{"="*60}', flush=True)
run('8. send_telegram_auto.py 5/12',
    [PYTHON, '-u', 'send_telegram_auto.py', '--dates', '20260512'],
    timeout=900)

# 9. 개인봇 종합 보고
print(f'\n{"="*60}\n[9. 개인봇 종합 보고]\n{"="*60}', flush=True)
run('9. send_final_summary.py',
    [PYTHON, '-u', 'send_final_summary.py'],
    timeout=120)

print('\n=== 모든 작업 완료 ===')
