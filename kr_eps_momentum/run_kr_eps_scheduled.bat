@echo off
chcp 65001 >nul 2>&1
REM KR EPS Momentum 로컬 스케줄 러너 (Task Scheduler 16:30 KST용) — GA cron 대체.
set PYTHONIOENCODING=utf-8

REM Python 경로 자동 감지 (직장PC jkw88 / 집PC user) — production run_daily.bat 패턴
if exist "C:\Users\jkw88\miniconda3\envs\volumequant\python.exe" (
    set PY=C:\Users\jkw88\miniconda3\envs\volumequant\python.exe
) else if exist "C:\Users\user\miniconda3\envs\volumequant\python.exe" (
    set PY=C:\Users\user\miniconda3\envs\volumequant\python.exe
) else (
    echo ERROR: volumequant python not found & exit /b 1
)

if not exist "C:\dev\kr_eps_momentum\logs" mkdir "C:\dev\kr_eps_momentum\logs"
"%PY%" "C:\dev\kr_eps_momentum\run_local_scheduled.py" >> "C:\dev\kr_eps_momentum\logs\local_%date:~0,4%%date:~5,2%%date:~8,2%.log" 2>&1
echo Done: %date% %time%
