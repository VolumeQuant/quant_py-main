$ErrorActionPreference = "Continue"
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$RESULT = "C:\dev\guide\verify_result.txt"
$BASE = "C:\dev\guide"

# Resolve paths via directory pattern (avoid hangul literal in script)
$cx = Join-Path $BASE "01_CX\PROD\system_prompt_v6.1_cx_flat_LF_escaped.txt"
$ux = Join-Path $BASE "03_UX\PROD\system_prompt_v6.1_ux_flat_LF_escaped.txt"
$empDir = Get-ChildItem $BASE -Directory | Where-Object { $_.Name -like "02_*" } | Select-Object -First 1
if ($empDir) {
    $emp = Join-Path $empDir.FullName "PROD\system_prompt_internal_memo_v11.1.txt"
} else {
    $emp = ""
}

$lines = New-Object System.Collections.ArrayList

function Add-Line($t) { [void]$lines.Add($t); Write-Host $t }

Add-Line "==================================================="
Add-Line "  Mi-Tone v6.1/v11.1/v6.1 Integrity Check"
Add-Line ("  Run: " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
Add-Line "==================================================="
Add-Line ""

$files = [ordered]@{ 'CX' = $cx; 'EMP' = $emp; 'UX' = $ux }

# [1] byte
Add-Line "[1] Byte size (limit 65258 / hard limit 65508)"
Add-Line "---------------------------------------------------"
foreach ($k in $files.Keys) {
    $f = $files[$k]
    if ($f -and (Test-Path $f)) {
        $size = (Get-Item $f).Length
        if ($size -lt 65258) { $st = "[OK]   " }
        elseif ($size -lt 65508) { $st = "[WARN] " }
        else { $st = "[FAIL] " }
        Add-Line ($st + $k.PadRight(8) + $size.ToString().PadLeft(8) + " byte")
    } else {
        Add-Line ("[FAIL] " + $k + " - file missing")
    }
}
Add-Line ""

# [2] CRLF
Add-Line "[2] CRLF check (LF only)"
Add-Line "---------------------------------------------------"
foreach ($k in $files.Keys) {
    $f = $files[$k]
    if ($f -and (Test-Path $f)) {
        $bytes = [System.IO.File]::ReadAllBytes($f)
        $crlf = 0
        for ($i = 0; $i -lt $bytes.Length - 1; $i++) {
            if ($bytes[$i] -eq 13 -and $bytes[$i+1] -eq 10) { $crlf++ }
        }
        if ($crlf -eq 0) { $st = "[OK]   " } else { $st = "[FAIL] " }
        Add-Line ($st + $k.PadRight(8) + "CRLF " + $crlf)
    }
}
Add-Line ""

# [3] Single brace violation
# A "single brace" = { not preceded/followed by { . LangChain reserved {context}/{question} are allowed.
# violation = single-open count - allowed count, clamped at 0
Add-Line "[3] Single brace violation (allow context/question)"
Add-Line "---------------------------------------------------"
foreach ($k in $files.Keys) {
    $f = $files[$k]
    if ($f -and (Test-Path $f)) {
        $text = Get-Content $f -Raw -Encoding UTF8
        $so = ([regex]::Matches($text, '(?<!\{)\{(?!\{)')).Count
        # Only count {context} / {question} where { is single (matches single-open pattern)
        $allowed = ([regex]::Matches($text, '(?<!\{)\{(context|question)\}(?!\})')).Count
        $vio = [Math]::Max(0, $so - $allowed)
        if ($vio -eq 0) { $st = "[OK]   " } else { $st = "[FAIL] " }
        Add-Line ($st + $k.PadRight(8) + "single-open " + $so + " / allowed " + $allowed + " / violation " + $vio)
    }
}
Add-Line ""

# [4] section sign residue
Add-Line "[4] Section sign residue (rule-block 1 each only)"
Add-Line "---------------------------------------------------"
foreach ($k in $files.Keys) {
    $f = $files[$k]
    if ($f -and (Test-Path $f)) {
        $text = Get-Content $f -Raw -Encoding UTF8
        $cnt = ([regex]::Matches($text, [char]0x00A7)).Count
        if ($cnt -le 1) { $st = "[OK]   " } else { $st = "[FAIL] " }
        Add-Line ($st + $k.PadRight(8) + "section-sign " + $cnt)
    }
}
Add-Line ""

# [5] extract xlsx
Add-Line "[5] Extract answer-data xlsx"
Add-Line "---------------------------------------------------"
$extractPs1 = "C:\dev\guide\extract_xlsx.ps1"
if (Test-Path $extractPs1) {
    Add-Line "[run] extract_xlsx.ps1"
    try {
        & $extractPs1 *>&1 | ForEach-Object { Add-Line ("  " + $_) }
    } catch {
        Add-Line ("[FAIL] extract error: " + $_)
    }
    $dumps = Get-ChildItem -LiteralPath $BASE -Filter "*_xlsx_dump.txt" -File -ErrorAction SilentlyContinue
    if ($dumps -and $dumps.Count -ge 2) {
        Add-Line ("[OK]   " + $dumps.Count + " dump files generated:")
        foreach ($d in $dumps) {
            $kb = [math]::Round($d.Length / 1KB, 1)
            Add-Line ("       - " + $d.Name + " (" + $kb + " KB)")
        }
    } elseif ($dumps -and $dumps.Count -eq 1) {
        Add-Line ("[WARN] only 1 dump file (expect 2):")
        Add-Line ("       - " + $dumps[0].Name)
    } else {
        Add-Line "[FAIL] no dump file generated (check xlsx file location)"
    }
} else {
    Add-Line "[WARN] extract_xlsx.ps1 missing - skip"
}
Add-Line ""

Add-Line "==================================================="
Add-Line "  Summary: count [FAIL] / [WARN] above"
Add-Line "  All [OK] = production-ready"
Add-Line ""
Add-Line "  Next:"
Add-Line "    1. python C:\dev\guide\eda_pipeline.py"
Add-Line "    2. apply 13 verification cases"
Add-Line "==================================================="

# Save result
$lines | Out-File -FilePath $RESULT -Encoding UTF8

Write-Host ""
Write-Host ("Result: " + $RESULT)
Start-Process notepad.exe -ArgumentList $RESULT
