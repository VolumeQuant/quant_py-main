@echo off
cd /d C:\dev\claude-code\quant_py-main
C:\Users\jkw88\miniconda3\envs\volumequant\python.exe -u run_daily.py >> logs\daily_%date:~0,4%%date:~5,2%%date:~8,2%.log 2>&1
