@echo off
chcp 65001 > nul
echo 정답데이터1·2 xlsx 전수 추출 시작...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0extract_xlsx.ps1"
echo.
echo 작업 완료. 아무 키나 누르면 창이 닫힙니다.
pause
