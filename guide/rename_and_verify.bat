@echo off
chcp 65001 > nul
echo === Mi-Tone 파일 rename (v6.0/v11.0/v6.0 -^> v6.1/v11.1/v6.1) ===
echo.

ren "C:\dev\guide\01_CX\PROD\system_prompt_v6.0_cx_flat_LF_escaped.txt" "system_prompt_v6.1_cx_flat_LF_escaped.txt"
if errorlevel 1 (echo [FAIL] CX rename) else (echo [OK]   CX  v6.0  -^> v6.1)

ren "C:\dev\guide\02_직원용\PROD\system_prompt_internal_memo_v11.0.txt" "system_prompt_internal_memo_v11.1.txt"
if errorlevel 1 (echo [FAIL] EMP rename) else (echo [OK]   EMP v11.0 -^> v11.1)

ren "C:\dev\guide\03_UX\PROD\system_prompt_v6.0_ux_flat_LF_escaped.txt" "system_prompt_v6.1_ux_flat_LF_escaped.txt"
if errorlevel 1 (echo [FAIL] UX rename) else (echo [OK]   UX  v6.0  -^> v6.1)

echo.
echo === verify.bat 실행 ===
echo.

call "C:\dev\guide\verify.bat"
