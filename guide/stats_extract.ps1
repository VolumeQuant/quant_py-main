$ErrorActionPreference = "Continue"
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$BASE = "C:\dev\guide"
$DUMP1 = Join-Path $BASE "정답데이터1_xlsx_dump.txt"
$DUMP2 = Join-Path $BASE "정답데이터2_xlsx_dump.txt"
$OUT = Join-Path $BASE "stats_550_full.md"

Write-Host "Reading dumps..."
$text1 = if (Test-Path $DUMP1) { Get-Content $DUMP1 -Raw -Encoding UTF8 } else { "" }
$text2 = if (Test-Path $DUMP2) { Get-Content $DUMP2 -Raw -Encoding UTF8 } else { "" }

# Split by Row markers, then keep ASIS [H?] and TOBE [I?] columns only
function Get-Cases([string]$text, [string]$label) {
    $cases = @()
    $rows = $text -split "(?m)^--- Row \d+ ---"
    Write-Host "  $label rows split: $($rows.Count)"
    foreach ($row in $rows) {
        if ($row.Trim().Length -lt 50) { continue }
        # Extract [H?] block (ASIS) and [I?] block (TOBE)
        $asisMatch = [regex]::Match($row, '\[H\d+\](.*?)(?=\[\w\d+\]|\z)', 'Singleline')
        $tobeMatch = [regex]::Match($row, '\[I\d+\](.*?)(?=\[\w\d+\]|\z)', 'Singleline')
        if ($asisMatch.Success -or $tobeMatch.Success) {
            $cases += [PSCustomObject]@{
                ASIS = if ($asisMatch.Success) { $asisMatch.Groups[1].Value } else { "" }
                TOBE = if ($tobeMatch.Success) { $tobeMatch.Groups[1].Value } else { "" }
            }
        }
    }
    return $cases
}

$cases1 = Get-Cases $text1 "정답데이터1"
$cases2 = Get-Cases $text2 "정답데이터2"
$all = $cases1 + $cases2
Write-Host "  Total cases (with ASIS or TOBE): $($all.Count)"

$tobeOnly = $all | Where-Object { $_.TOBE.Trim().Length -gt 30 }
Write-Host "  TOBE non-empty: $($tobeOnly.Count)"

# Extract all "■ XXX" headers from TOBE
$blockNames = @{}
foreach ($c in $tobeOnly) {
    $matches = [regex]::Matches($c.TOBE, '■\s*([^\r\n/]+?)(?=\r?\n| / |$)')
    foreach ($m in $matches) {
        $name = $m.Groups[1].Value.Trim() -replace '\s+', ' '
        if ($name.Length -gt 0 -and $name.Length -lt 50) {
            if ($blockNames.ContainsKey($name)) { $blockNames[$name]++ } else { $blockNames[$name] = 1 }
        }
    }
}

# Extract ASIS patterns to convert
$asisPatterns = @{
    "ASIS_미래에셋대우" = ($all | Where-Object { $_.ASIS -match '\[미래에셋대우\]' }).Count
    "ASIS_단독_고객님" = ($all | Where-Object { $_.ASIS -match '#\{고객명\}\s*고객님\s*\r?\n' }).Count
    "ASIS_phone_emoji" = ($all | Where-Object { $_.ASIS -match '☎' }).Count
    "ASIS_당사" = ($all | Where-Object { $_.ASIS -match '당사' }).Count
    "ASIS_익일" = ($all | Where-Object { $_.ASIS -match '익일|익영업일' }).Count
    "ASIS_상기_하기" = ($all | Where-Object { $_.ASIS -match '상기|하기' }).Count
    "ASIS_삼각형_화살표" = ($all | Where-Object { $_.ASIS -match '▶|▷' }).Count
    "ASIS_사각공백" = ($all | Where-Object { $_.ASIS -match '※' }).Count
    "ASIS_원문자_dot" = ($all | Where-Object { $_.ASIS -match '●' }).Count
    "ASIS_box" = ($all | Where-Object { $_.ASIS -match '□' }).Count
    "ASIS_하시기바랍니다" = ($all | Where-Object { $_.ASIS -match '하시기 바랍니다|하시기바랍니다' }).Count
    "ASIS_드리오니" = ($all | Where-Object { $_.ASIS -match '드리오니' }).Count
    "ASIS_안내드립니다" = ($all | Where-Object { $_.ASIS -match '안내드립니다|알려드립니다' }).Count
    "ASIS_양지" = ($all | Where-Object { $_.ASIS -match '양지' }).Count
}

# Extract TOBE patterns
$tobePatterns = @{
    "TOBE_미래에셋증권" = ($tobeOnly | Where-Object { $_.TOBE -match '\[미래에셋증권\]' }).Count
    "TOBE_고객님_콤마" = ($tobeOnly | Where-Object { $_.TOBE -match '#\{고객명\} 고객님,' }).Count
    "TOBE_block_count_avg" = 0  # computed below
    "TOBE_꼭_확인해_주세요" = ($tobeOnly | Where-Object { $_.TOBE -match '■ 꼭 확인해 주세요' }).Count
    "TOBE_문의" = ($tobeOnly | Where-Object { $_.TOBE -match '■ 문의' }).Count
    "TOBE_법령_쌍꺾쇠" = ($tobeOnly | Where-Object { $_.TOBE -match '「[^」]+」' }).Count
    "TOBE_제N조" = ($tobeOnly | Where-Object { $_.TOBE -match '제\d+조' }).Count
    "TOBE_dash_item" = ($tobeOnly | Where-Object { $_.TOBE -match '(?m)^\s*-\s*\S+:' }).Count
    "TOBE_star_item" = ($tobeOnly | Where-Object { $_.TOBE -match '(?m)^\s*\*\s' }).Count
    "TOBE_평일0800" = ($tobeOnly | Where-Object { $_.TOBE -match '평일 \d{2}:\d{2}~\d{2}:\d{2}' }).Count
    "TOBE_해주세요" = ($tobeOnly | Where-Object { $_.TOBE -match '해 주세요|해주세요' }).Count
    "TOBE_드립니다" = ($tobeOnly | Where-Object { $_.TOBE -match '안내해 드립니다|알려 드립니다' }).Count
}

# Compute average ■ blocks per TOBE
$blockCounts = $tobeOnly | ForEach-Object {
    ([regex]::Matches($_.TOBE, '■')).Count
}
$avgBlocks = if ($blockCounts.Count -gt 0) { ($blockCounts | Measure-Object -Average).Average } else { 0 }

# Write result
$lines = New-Object System.Collections.ArrayList

[void]$lines.Add("# 정답데이터 550건 전수 패턴 통계")
[void]$lines.Add("")
[void]$lines.Add("실행: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
[void]$lines.Add("정답데이터1: $($cases1.Count) cases / 정답데이터2: $($cases2.Count) cases / 합계: $($all.Count)")
[void]$lines.Add("TOBE 본문 있는 케이스: $($tobeOnly.Count)")
[void]$lines.Add("")
[void]$lines.Add("---")
[void]$lines.Add("")

[void]$lines.Add("## 1. ■ 블록 명칭 빈도 (TOBE 전수)")
[void]$lines.Add("")
[void]$lines.Add("| ■ 블록 명칭 | 빈도 | 빈도 % (TOBE $($tobeOnly.Count) 기준) |")
[void]$lines.Add("|---|---|---|")
$sorted = $blockNames.GetEnumerator() | Sort-Object Value -Descending
foreach ($kv in $sorted) {
    if ($kv.Value -lt 2) { continue }  # skip singletons
    $pct = [math]::Round($kv.Value / $tobeOnly.Count * 100, 1)
    [void]$lines.Add("| ■ $($kv.Key) | $($kv.Value) | $pct% |")
}
[void]$lines.Add("")

[void]$lines.Add("## 2. ASIS 패턴 빈도 (변환 대상)")
[void]$lines.Add("")
[void]$lines.Add("| 패턴 | 빈도 | 빈도 % |")
[void]$lines.Add("|---|---|---|")
foreach ($kv in $asisPatterns.GetEnumerator() | Sort-Object Value -Descending) {
    $pct = [math]::Round($kv.Value / $all.Count * 100, 1)
    [void]$lines.Add("| $($kv.Key) | $($kv.Value) | $pct% |")
}
[void]$lines.Add("")

[void]$lines.Add("## 3. TOBE 패턴 빈도 (변환 결과)")
[void]$lines.Add("")
[void]$lines.Add("| 패턴 | 빈도 | 빈도 % |")
[void]$lines.Add("|---|---|---|")
foreach ($kv in $tobePatterns.GetEnumerator() | Sort-Object Value -Descending) {
    if ($kv.Key -eq "TOBE_block_count_avg") { continue }
    $pct = [math]::Round($kv.Value / $tobeOnly.Count * 100, 1)
    [void]$lines.Add("| $($kv.Key) | $($kv.Value) | $pct% |")
}
[void]$lines.Add("")
[void]$lines.Add("**TOBE 평균 ■ 블록 수**: $([math]::Round($avgBlocks, 2))")
[void]$lines.Add("")

[void]$lines.Add("---")
[void]$lines.Add("")
[void]$lines.Add("## 4. 등급 분류 (가이드 backing)")
[void]$lines.Add("")
[void]$lines.Add("- 필수 (≥80% TOBE 등장): 시스템 프롬프트 anchor에 박혀야 함")
[void]$lines.Add("- 조건부 (30-80%): 채널·도메인별 등장")
[void]$lines.Add("- 선택 (<30%): 특수 도메인")
[void]$lines.Add("")

$lines | Out-File -FilePath $OUT -Encoding UTF8

Write-Host ""
Write-Host "Output: $OUT"
