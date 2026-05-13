@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

set "RESULT=C:\dev\guide\verify_result.txt"
set "CX=C:\dev\guide\01_CX\PROD\system_prompt_v6.1_cx_flat_LF_escaped.txt"
set "EMP=C:\dev\guide\02_직원용\PROD\system_prompt_internal_memo_v11.1.txt"
set "UX=C:\dev\guide\03_UX\PROD\system_prompt_v6.1_ux_flat_LF_escaped.txt"
set "FAIL_COUNT=0"
set "WARN_COUNT=0"

(
echo ===================================================
echo   Mi-Tone v6.1/v11.1/v6.1 무결성 검증
echo   실행: %date% %time%
echo ===================================================
echo.
echo 한도 기준:
echo   - byte:    65,258 byte 이하 = OK / 65,508 이상 = FAIL
echo   - CRLF:    0 = OK / 1 이상 = FAIL
echo   - 단일 중괄호: context/question 외 = FAIL
echo   - 본문 §:  룰 차단 명시 1줄씩 외 = FAIL
echo.
) > "%RESULT%"

REM ────────────── (a) byte 측정 ──────────────
(
echo [1] byte 측정
echo ---------------------------------------------------
) >> "%RESULT%"

powershell -NoProfile -Command "$files = @{'CX'='%CX%';'직원용'='%EMP%';'UX'='%UX%'}; foreach ($k in $files.Keys) { $size = (Get-Item $files[$k]).Length; $status = if ($size -lt 65258) { '[OK]    ' } elseif ($size -lt 65508) { '[WARN]  ' } else { '[FAIL]  ' }; '{0}{1,-10} {2,8} byte (한도 65,258 / 한계 65,508)' -f $status, $k, $size }" >> "%RESULT%"
echo. >> "%RESULT%"

REM ────────────── (b) CRLF 검증 ──────────────
(
echo [2] CRLF 검증 (LF only 강제)
echo ---------------------------------------------------
) >> "%RESULT%"

for %%F in ("%CX%" "%EMP%" "%UX%") do (
    findstr /R /C:"\r$" "%%F" > nul
    if !errorlevel! equ 0 (
        echo [FAIL]  %%~nF — CRLF 발견 ^(LF로 정정 필요^) >> "%RESULT%"
        set /a FAIL_COUNT+=1
    ) else (
        echo [OK]    %%~nF — CRLF 0건 >> "%RESULT%"
    )
)
echo. >> "%RESULT%"

REM ────────────── (c) 단일 중괄호 위반 ──────────────
(
echo [3] 단일 중괄호 위반 ^(context/question 제외^)
echo ---------------------------------------------------
) >> "%RESULT%"

powershell -NoProfile -Command "$files = @{'CX'='%CX%';'직원용'='%EMP%';'UX'='%UX%'}; foreach ($k in $files.Keys) { $text = Get-Content $files[$k] -Raw -Encoding UTF8; $singleOpen = ([regex]::Matches($text, '(?<!\{)\{(?!\{)')).Count; $singleClose = ([regex]::Matches($text, '(?<!\})\}(?!\})')).Count; $allowed = ([regex]::Matches($text, '\{(context|question)\}')).Count; $vio = $singleOpen - $allowed; $status = if ($vio -eq 0) { '[OK]   ' } else { '[FAIL] ' }; '{0}{1,-10} 단일{{ {2} / 단일}} {3} / 허용 (context/question) {4} / 위반 {5}' -f $status, $k, $singleOpen, $singleClose, $allowed, $vio }" >> "%RESULT%"
echo. >> "%RESULT%"

REM ────────────── (d) § 잔재 검출 ──────────────
(
echo [4] § 기호 본문 잔재 ^(룰 차단 명시 1줄씩 외^)
echo ---------------------------------------------------
) >> "%RESULT%"

for %%F in ("%CX%" "%EMP%" "%UX%") do (
    powershell -NoProfile -Command "$cnt = ((Select-String -Path '%%F' -Pattern '§').Count); if ($cnt -le 1) { Write-Output ('[OK]    %%~nF — § ' + $cnt + '건 (룰 차단 명시 라인)') } else { Write-Output ('[FAIL]  %%~nF — § ' + $cnt + '건 (1건 초과 - 본문 잔재 의심)') }" >> "%RESULT%"
)
echo. >> "%RESULT%"

REM ────────────── (e) 정답데이터 추출 ──────────────
(
echo [5] 정답데이터1·2 xlsx 추출
echo ---------------------------------------------------
) >> "%RESULT%"

if exist "C:\dev\guide\extract.bat" (
    echo [실행] extract.bat 호출 중... >> "%RESULT%"
    call C:\dev\guide\extract.bat >> "%RESULT%" 2>&1
    if exist "C:\dev\guide\정답데이터2_xlsx_dump.txt" (
        echo [OK]    정답데이터2_xlsx_dump.txt 생성됨 >> "%RESULT%"
    ) else (
        echo [WARN]  정답데이터2_xlsx_dump.txt 미생성 >> "%RESULT%"
    )
) else (
    echo [WARN]  extract.bat 없음 - skip >> "%RESULT%"
)
echo. >> "%RESULT%"

REM ────────────── 종합 결과 ──────────────
(
echo ===================================================
echo   종합 결과
echo ===================================================
echo.
echo [FAIL] / [WARN] 개수를 위에서 확인하세요.
echo 모두 [OK]면 production 배포 안전.
echo.
echo 다음 작업:
echo   1. python C:\dev\guide\eda_pipeline.py    ^(EDA 자동 실행^)
echo   2. verification_cases.md 케이스 production 챗봇 입력 검증
echo.
echo 결과 파일: %RESULT%
echo ===================================================
) >> "%RESULT%"

echo.
echo 검증 완료. 결과 파일을 메모장으로 엽니다.
notepad "%RESULT%"
endlocal
