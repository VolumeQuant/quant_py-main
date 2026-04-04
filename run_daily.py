"""
로컬 PC 자동 실행 — 매일 포트폴리오 생성 + 텔레그램 전송 + git push

GitHub Actions telegram_daily.yml과 동일한 파이프라인.
Windows Task Scheduler에서 호출.
"""

import subprocess
import sys
import os
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

# ── 경로 설정 ──
SCRIPT_DIR = Path(__file__).parent.resolve()
PYTHON = sys.executable
LOG_DIR = SCRIPT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)


def log(msg: str, f=None):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    if f:
        f.write(line + "\n")
        f.flush()


def run_script(name: str, timeout: int, logfile, extra_env=None):
    """subprocess로 Python 스크립트 실행"""
    script = SCRIPT_DIR / name
    log(f"실행: {name}", logfile)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        [PYTHON, str(script)],
        cwd=str(SCRIPT_DIR),
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if result.stdout:
        logfile.write(result.stdout)
    if result.stderr:
        logfile.write(result.stderr)
    logfile.flush()
    return result.returncode == 0


def send_error_notification():
    """포트폴리오 생성 실패 시 텔레그램 에러 알림"""
    try:
        import requests
        sys.path.insert(0, str(SCRIPT_DIR))
        from config import TELEGRAM_BOT_TOKEN, TELEGRAM_PRIVATE_ID
        msg = (
            "<b>[시스템 알림]</b>\n\n"
            "데이터 소스(KRX) 점검 중으로 오늘 리포트를 생성하지 못했습니다.\n"
            "기존 포트폴리오를 유지해 주세요.\n\n"
            "<i>pykrx/KRX API 복구 시 자동 정상화됩니다.</i>"
        )
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_PRIVATE_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
        print("에러 알림 전송 완료")
    except Exception as e:
        print(f"에러 알림 전송 실패: {e}")


def git_push_state(logfile):
    """state/ 디렉토리 git commit + push"""
    repo_root = SCRIPT_DIR  # git 루트 = 스크립트 디렉토리
    today = datetime.now().strftime("%Y%m%d")
    cmds = [
        ["git", "add", "state/"],
        ["git", "diff", "--cached", "--quiet"],
    ]
    # git add
    subprocess.run(cmds[0], cwd=str(repo_root), capture_output=True)
    # 변경 확인
    result = subprocess.run(cmds[1], cwd=str(repo_root), capture_output=True)
    if result.returncode != 0:  # 변경 있음
        subprocess.run(
            ["git", "commit", "-m", f"state: daily ranking {today}"],
            cwd=str(repo_root), capture_output=True,
        )
        push = subprocess.run(
            ["git", "push"],
            cwd=str(repo_root), capture_output=True, text=True, timeout=30,
        )
        log(f"git push: {'성공' if push.returncode == 0 else '실패'}", logfile)
    else:
        log("git: 변경 없음", logfile)


def main():
    today = datetime.now().strftime("%Y%m%d")
    log_path = LOG_DIR / f"daily_{today}.log"
    lock_file = LOG_DIR / f"daily_{today}.lock"

    # 중복 실행 방지 (TEST_MODE에서는 스킵)
    is_test = os.environ.get('TEST_MODE') == '1'
    if lock_file.exists() and not is_test:
        print(f"[스킵] 오늘({today}) 이미 실행 완료됨 ({lock_file})")
        return

    with open(log_path, "a", encoding="utf-8") as logfile:
        log("=" * 50, logfile)
        log("퀀트 데일리 파이프라인 시작", logfile)
        log("=" * 50, logfile)

        # 0. DART 증분 갱신 (매일, 비공시 시즌에는 스크립트 내부에서 즉시 종료)
        # 종목명 캐시 — 별도 스케줄러 (매주 월요일 09시)
        log("DART 캐시 증분 갱신", logfile)
        try:
            ok_dart = run_script("refresh_dart_cache.py", timeout=600, logfile=logfile)
            log(f"DART 갱신: {'성공' if ok_dart else '실패'}", logfile)
        except subprocess.TimeoutExpired:
            log("DART 갱신 타임아웃 (10분) — 기존 캐시로 진행", logfile)
        except Exception as e:
            log(f"DART 갱신 오류: {e} — 기존 캐시로 진행", logfile)

        # 0.5. 국면 판단
        log("국면 판단 (KOSPI+KOSDAQ MA60)", logfile)
        try:
            sys.path.insert(0, str(SCRIPT_DIR))
            from regime_indicator import get_current_regime, get_regime_params
            import krx_auth
            krx_auth.login()
            from pykrx import stock as pykrx_stock
            import time as _time
            import pandas as pd

            # KOSPI
            kospi_df = pykrx_stock.get_market_ohlcv(
                (datetime.now() - __import__('datetime').timedelta(days=90)).strftime('%Y%m%d'),
                today, '005930'
            )
            _time.sleep(1)
            kospi_idx = pykrx_stock.get_index_ohlcv(
                (datetime.now() - __import__('datetime').timedelta(days=90)).strftime('%Y%m%d'),
                today, '1001'
            )
            kospi_close = kospi_idx.iloc[-1, 3] if not kospi_idx.empty else None
            kospi_ma60 = kospi_idx.iloc[:, 3].rolling(60).mean().iloc[-1] if len(kospi_idx) >= 60 else None

            _time.sleep(1)
            kosdaq_idx = pykrx_stock.get_index_ohlcv(
                (datetime.now() - __import__('datetime').timedelta(days=90)).strftime('%Y%m%d'),
                today, '2001'
            )
            kosdaq_close = kosdaq_idx.iloc[-1, 3] if not kosdaq_idx.empty else None
            kosdaq_ma60 = kosdaq_idx.iloc[:, 3].rolling(60).mean().iloc[-1] if len(kosdaq_idx) >= 60 else None

            regime = get_current_regime(
                kospi_close=kospi_close, kospi_ma60=kospi_ma60,
                kosdaq_close=kosdaq_close, kosdaq_ma60=kosdaq_ma60,
                date_str=today
            )
            params = get_regime_params(regime['mode'])
            log(f"국면: {params['icon']} {params['label']} (신호={regime['signal']}, 연속={regime['streak']}일, 전환={regime['switched']})", logfile)
        except Exception as e:
            log(f"국면 판단 실패: {e} — 기본 방어 모드", logfile)
            from regime_indicator import get_regime_params
            regime = {'mode': 'cal3', 'switched': False, 'signal': 'cal3', 'streak': 0, 'prev_mode': 'cal3'}
            params = get_regime_params('cal3')

        # 1. 포트폴리오 생성 (국면 파라미터 환경변수 주입)
        regime_env = {
            'FACTOR_V_W': str(params['V_W']),
            'FACTOR_Q_W': str(params['Q_W']),
            'FACTOR_G_W': str(params['G_W']),
            'FACTOR_M_W': str(params['M_W']),
            'G_REVENUE_WEIGHT': str(params['G_REV']),
            'USE_REV_ACCEL': '1' if params['USE_REV_ACCEL'] else '0',
            'REGIME_MODE': regime['mode'],
            'REGIME_ENTRY_RANK': str(params['ENTRY_RANK']),
            'REGIME_EXIT_RANK': str(params['EXIT_RANK']),
            'REGIME_MAX_SLOTS': str(params['MAX_SLOTS']),
        }
        try:
            ok = run_script("create_current_portfolio.py", timeout=1200, logfile=logfile, extra_env=regime_env)
        except subprocess.TimeoutExpired:
            log("포트폴리오 생성 타임아웃 (20분)", logfile)
            ok = False
        except Exception as e:
            log(f"포트폴리오 생성 오류: {e}", logfile)
            ok = False

        if not ok:
            log("포트폴리오 실패 → 에러 알림 전송", logfile)
            send_error_notification()
            return

        # 2. 텔레그램 전송
        try:
            ok2 = run_script("send_telegram_auto.py", timeout=180, logfile=logfile, extra_env=regime_env)
            log(f"텔레그램 전송: {'성공' if ok2 else '실패'}", logfile)
        except subprocess.TimeoutExpired:
            log("텔레그램 전송 타임아웃 (3분)", logfile)
        except Exception as e:
            log(f"텔레그램 전송 오류: {e}", logfile)

        # 3. git push
        try:
            git_push_state(logfile)
        except Exception as e:
            log(f"git push 오류: {e}", logfile)

        # 완료 lock 생성 (TEST_MODE에서는 생성 안 함)
        if not is_test:
            lock_file.write_text(datetime.now().isoformat(), encoding="utf-8")
        log("파이프라인 완료", logfile)


if __name__ == "__main__":
    main()
