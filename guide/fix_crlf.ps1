$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$BASE = "C:\dev\guide"
$cx = Join-Path $BASE "01_CX\PROD\system_prompt_v6.1_cx_flat_LF_escaped.txt"
$ux = Join-Path $BASE "03_UX\PROD\system_prompt_v6.1_ux_flat_LF_escaped.txt"
$empDir = Get-ChildItem $BASE -Directory | Where-Object { $_.Name -like "02_*" } | Select-Object -First 1
if ($empDir) {
    $emp = Join-Path $empDir.FullName "PROD\system_prompt_internal_memo_v11.1.txt"
} else {
    $emp = ""
}

$files = @($cx, $emp, $ux)

Write-Host "==================================================="
Write-Host "  CRLF -> LF Conversion"
Write-Host "==================================================="
Write-Host ""

foreach ($f in $files) {
    try {
        if (-not (Test-Path $f)) {
            Write-Host ("[SKIP] " + (Split-Path $f -Leaf) + " - file missing")
            continue
        }

        $bytes = [System.IO.File]::ReadAllBytes($f)
        $crlf_before = 0
        for ($i = 0; $i -lt $bytes.Length - 1; $i++) {
            if ($bytes[$i] -eq 13 -and $bytes[$i+1] -eq 10) {
                $crlf_before++
            }
        }

        $text = [System.Text.Encoding]::UTF8.GetString($bytes)
        $text = $text -replace "`r`n", "`n"
        $text = $text -replace "`r", "`n"

        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        $newBytes = $utf8NoBom.GetBytes($text)
        [System.IO.File]::WriteAllBytes($f, $newBytes)

        $name = Split-Path $f -Leaf
        Write-Host ("[OK] " + $name + " CRLF " + $crlf_before + " -> 0")
    } catch {
        Write-Host ("[FAIL] " + (Split-Path $f -Leaf) + " - " + $_.Exception.Message)
    }
}

Write-Host ""
Write-Host "Done. Run verify.bat again."
