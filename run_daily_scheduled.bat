@echo off
cd /d C:\dev\claude-code\quant_py-main
REM 콘솔 로그는 별도 파일로 — run_daily.py 내부 로그(daily_*.log)와 같은 파일을 잡으면
REM cmd 리다이렉트의 공유 잠금 때문에 내부 open이 PermissionError로 죽음 (2026-07-22 사고)
C:\Users\jkw88\miniconda3\envs\volumequant\python.exe -u run_daily.py >> logs\daily_console_%date:~0,4%%date:~5,2%%date:~8,2%.log 2>&1
