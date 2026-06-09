@echo off
chcp 65001 >nul 2>&1
setlocal
set PYTHONIOENCODING=utf-8
REM KR EPS local scheduled runner (Task Scheduler 16:30 KST). Replaces GA cron.
REM ASCII-only on purpose: cmd misparses UTF-8 Korean in .bat. Korean lives in the .py.
if exist "C:\Users\jkw88\miniconda3\envs\volumequant\python.exe" (
  set "PY=C:\Users\jkw88\miniconda3\envs\volumequant\python.exe"
) else if exist "C:\Users\user\miniconda3\envs\volumequant\python.exe" (
  set "PY=C:\Users\user\miniconda3\envs\volumequant\python.exe"
) else (
  echo ERROR: volumequant python not found
  exit /b 1
)
if not exist "C:\dev\kr_eps_momentum\logs" mkdir "C:\dev\kr_eps_momentum\logs"
"%PY%" "C:\dev\kr_eps_momentum\run_local_scheduled.py" >> "C:\dev\kr_eps_momentum\logs\local_run.log" 2>&1
echo Done %date% %time%
endlocal
