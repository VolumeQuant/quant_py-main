$ErrorActionPreference = "Continue"
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$BASE = "C:\dev\guide"
$ARCHIVE = Join-Path $BASE "99_archive"
$DUPDIR = Join-Path $ARCHIVE "root_duplicates_2026-05-04"

Write-Host "==================================================="
Write-Host "  v6.1 cleanup — root sweep + archive sort"
Write-Host "==================================================="
Write-Host ""

# Ensure target dirs
if (-not (Test-Path $ARCHIVE)) { New-Item -ItemType Directory -Path $ARCHIVE | Out-Null }
if (-not (Test-Path $DUPDIR)) { New-Item -ItemType Directory -Path $DUPDIR | Out-Null }

# (1) rename_and_verify.bat -> 99_archive\
$src1 = Join-Path $BASE "rename_and_verify.bat"
$dst1 = Join-Path $ARCHIVE "rename_and_verify.bat"
if (Test-Path $src1) {
    Move-Item -LiteralPath $src1 -Destination $dst1 -Force
    Write-Host "[OK]   rename_and_verify.bat -> 99_archive\"
} else {
    Write-Host "[SKIP] rename_and_verify.bat (already moved or missing)"
}

# (2) root duplicates -> 99_archive\root_duplicates_2026-05-04\
$dups = @(
    "system_prompt_v6.1_cx_flat_LF_escaped.txt",
    "system_prompt_v6.1_ux_flat_LF_escaped.txt",
    "system_prompt_internal_memo_v11.1.txt"
)
foreach ($f in $dups) {
    $src = Join-Path $BASE $f
    $dst = Join-Path $DUPDIR $f
    if (Test-Path $src) {
        Move-Item -LiteralPath $src -Destination $dst -Force
        Write-Host ("[OK]   " + $f + " -> root_duplicates_2026-05-04\")
    } else {
        Write-Host ("[SKIP] " + $f + " (already moved or missing)")
    }
}

# (3) expert_reviews\*.md — header marker
$reviewDir = Join-Path $BASE "expert_reviews"
$marker = "<!-- 본 문서는 v6.0 시점 작성. v6.1 이후 변경 이력은 CHANGELOG.md 참조 -->"
$reviewFiles = Get-ChildItem -Path $reviewDir -Filter "*.md" -File -ErrorAction SilentlyContinue
foreach ($rf in $reviewFiles) {
    $text = Get-Content -LiteralPath $rf.FullName -Raw -Encoding UTF8
    if ($text -match [regex]::Escape($marker)) {
        Write-Host ("[SKIP] " + $rf.Name + " (marker already present)")
    } else {
        $newText = $marker + "`r`n" + $text
        [System.IO.File]::WriteAllText($rf.FullName, $newText, (New-Object System.Text.UTF8Encoding($false)))
        Write-Host ("[OK]   " + $rf.Name + " (marker added)")
    }
}

Write-Host ""
Write-Host "==================================================="
Write-Host "  Cleanup done."
Write-Host "==================================================="
Write-Host ""
Write-Host "Verify:"
Write-Host "  1. C:\dev\guide root — no v6.1 prompt copies"
Write-Host "  2. 99_archive\rename_and_verify.bat exists"
Write-Host "  3. 99_archive\root_duplicates_2026-05-04\ has 3 files"
Write-Host "  4. expert_reviews\*.md headers carry the marker"
Read-Host "Press Enter to close"
