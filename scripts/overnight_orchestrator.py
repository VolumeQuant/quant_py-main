"""밤샘 자동 orchestrator — Phase 2 완료 대기 → Phase 3 → 4 → 5-7

이미 Phase 2가 백그라운드에서 돌고 있다고 가정.
로그 파일 및 수집 결과물로 Phase 2 완료 감지 후 다음 단계 진행.

실행:
    python scripts/overnight_orchestrator.py &
"""
import os, sys, time, subprocess, traceback, json
from pathlib import Path
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')
PROJECT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT))

LOG_FILE = PROJECT / 'logs' / 'overnight_orchestrator.log'
LOG_FILE.parent.mkdir(exist_ok=True)


def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line, flush=True)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def send_tg(msg):
    try:
        import requests
        from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
        url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
        MAX = 4000
        for i in range(0, len(msg), MAX):
            requests.post(url, data={'chat_id': TELEGRAM_PRIVATE_ID, 'text': msg[i:i+MAX]}, timeout=30)
            time.sleep(0.3)
    except Exception as e:
        log(f'텔레그램 실패: {e}')


def wait_phase2_complete(max_wait_min=180):
    """Phase 2 완료 감지. DART/pykrx 로그 'Phase 2 완료' 메시지 확인."""
    log('[Wait] Phase 2 완료 대기 시작')
    main_log = PROJECT / 'logs' / 'collect_7y8_main.log'
    t0 = time.time()
    while time.time() - t0 < max_wait_min * 60:
        if main_log.exists():
            with open(main_log, 'r', encoding='utf-8') as f:
                content = f.read()
            if 'Phase 2 완료' in content:
                log('[Wait] Phase 2 완료 감지')
                return True
        time.sleep(60)
    log('[Wait] Phase 2 타임아웃')
    return False


def run_phase(name, script_path, timeout=3600):
    log(f'=== {name} 시작: {script_path} ===')
    send_tg(f'[{name}] 시작')
    t0 = time.time()
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(PROJECT),
            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
            capture_output=True, text=True,
            encoding='utf-8', errors='replace',
            timeout=timeout,
        )
        elapsed = (time.time() - t0) / 60
        log(f'{name} 종료: rc={result.returncode}, {elapsed:.1f}분')
        if result.returncode != 0:
            tail = (result.stderr or result.stdout or '')[-1000:]
            log(f'{name} stderr: {tail}')
            send_tg(f'[{name}] 실패 (rc={result.returncode})\n{tail[:500]}')
            return False
        return True
    except subprocess.TimeoutExpired:
        log(f'{name} 타임아웃')
        send_tg(f'[{name}] 타임아웃')
        return False
    except Exception as e:
        log(f'{name} 예외: {e}')
        log(traceback.format_exc())
        send_tg(f'[{name}] 예외: {e}')
        return False


def main():
    log('=== Overnight Orchestrator 시작 ===')
    send_tg('🌙 밤샘 자동 진행 시작\n\nPhase 2 → 3 → 4 → 5 → 6 → 7 순차 실행')

    # Phase 2 완료 대기
    if not wait_phase2_complete(max_wait_min=180):
        send_tg('Phase 2 완료 못함 → 중단')
        return 1

    # Phase 3: BT 재생성 (32분 예상)
    if not run_phase('Phase 3 BT 재생성', PROJECT / 'scripts' / 'regenerate_bt_7y8.py', timeout=3600):
        return 1

    # Phase 4: 그리드서치 + 안정성 + WF (25분 예상)
    if not run_phase('Phase 4 그리드서치', PROJECT / 'scripts' / 'grid_search_7y8.py', timeout=3600):
        return 1

    # Phase 5-7: 비교 + 프로덕션 + 커밋
    if not run_phase('Phase 5-7 마무리', PROJECT / 'scripts' / 'finalize_overnight.py', timeout=3600):
        return 1

    log('=== 모든 Phase 완료 ===')
    return 0


if __name__ == '__main__':
    try:
        rc = main()
        sys.exit(rc)
    except Exception as e:
        log(f'orchestrator 치명적 오류: {e}')
        log(traceback.format_exc())
        send_tg(f'orchestrator 오류: {e}')
        sys.exit(1)
