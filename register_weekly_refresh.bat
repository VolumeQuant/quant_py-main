@echo off
schtasks /Create /SC WEEKLY /D SUN /TN "QuantWeeklyRefresh" /TR "C:\Users\jkw88\miniconda3\envs\volumequant\python.exe \"C:\dev\claude-code\quant_py-main\run_weekly_refresh.py\"" /ST 21:00 /F
echo Done. Task "QuantWeeklyRefresh" registered for every Sunday 21:00.
pause
