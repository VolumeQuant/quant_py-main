"""
주간 FnGuide 캐시 갱신 — 매주 일요일 21:00 KST

Windows Task Scheduler에서 호출.
refresh_fnguide_cache.py를 실행하여 전 종목 재무제표를 최신화.
"""

import subprocess
import sys
import os
from datetime import datetime
from pathlib import Path

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


def main():
    today = datetime.now().strftime("%Y%m%d")
    log_path = LOG_DIR / f"weekly_refresh_{today}.log"

    # 중복 실행 방지
    lock_path = LOG_DIR / f"weekly_refresh_{today}.lock"
    if lock_path.exists():
        print(f"이미 실행됨: {lock_path}")
        return
    lock_path.write_text(today)

    with open(log_path, "w", encoding="utf-8") as lf:
        log("=== 주간 FnGuide 캐시 갱신 시작 ===", lf)

        try:
            result = subprocess.run(
                [PYTHON, str(SCRIPT_DIR / "refresh_fnguide_cache.py")],
                cwd=str(SCRIPT_DIR),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3600,  # 1시간 타임아웃
            )
            log(f"exit code: {result.returncode}", lf)
            if result.stdout:
                for line in result.stdout.strip().split("\n")[-20:]:
                    log(f"  {line}", lf)
            if result.returncode != 0 and result.stderr:
                for line in result.stderr.strip().split("\n")[-10:]:
                    log(f"  ERR: {line}", lf)
        except subprocess.TimeoutExpired:
            log("TIMEOUT: 1시간 초과", lf)
        except Exception as e:
            log(f"ERROR: {e}", lf)

        log("=== 주간 FnGuide 캐시 갱신 완료 ===", lf)


if __name__ == "__main__":
    main()
