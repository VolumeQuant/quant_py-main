@echo off
REM KR yf daily probe — Windows Task Scheduler용
REM 실행: 매일 새벽 (장 시작 전 권장)
REM 로그: yf_eps_workspace/logs/daily/run_YYYYMMDD.log

set PY=C:\Users\user\miniconda3\envs\volumequant\python.exe
set SCRIPT=C:\dev\yf_eps_workspace\code\daily_probe.py
set LOG_DIR=C:\dev\yf_eps_workspace\logs\daily

REM 오늘 날짜로 로그 파일
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value 2^>nul ^| find "="') do set DT=%%I
set TODAY=%DT:~0,8%

"%PY%" "%SCRIPT%" > "%LOG_DIR%\run_%TODAY%.log" 2>&1
