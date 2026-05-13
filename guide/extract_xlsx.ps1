# Extract xlsx files using directory pattern matching (ASCII-only, hangul-safe)
# Run via: extract.bat or directly powershell -ExecutionPolicy Bypass -File extract_xlsx.ps1

$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Add-Type -AssemblyName System.IO.Compression.FileSystem

$BASE = "C:\dev\guide"
$VECTOR_DIR = Join-Path $BASE "01_CX\vector_db"

function Extract-Xlsx {
    param([string]$xlsxPath, [string]$outPath, [string]$label)

    Write-Host ""
    Write-Host "==================================="
    Write-Host "Extract: $label"
    Write-Host "  src: $xlsxPath"
    Write-Host "  out: $outPath"
    Write-Host "==================================="

    if (-not (Test-Path -LiteralPath $xlsxPath)) {
        Write-Host "  [ERROR] file not found"
        return
    }

    $tempDir = Join-Path $env:TEMP "xlsx_extract_$(Get-Random)"

    try {
        [System.IO.Compression.ZipFile]::ExtractToDirectory($xlsxPath, $tempDir)

        # 1. shared strings
        $ssPath = Join-Path $tempDir "xl\sharedStrings.xml"
        $strings = New-Object System.Collections.ArrayList
        if (Test-Path $ssPath) {
            [xml]$ss = [System.IO.File]::ReadAllText($ssPath, [System.Text.Encoding]::UTF8)
            $nsmSs = New-Object System.Xml.XmlNamespaceManager($ss.NameTable)
            $nsmSs.AddNamespace("x", "http://schemas.openxmlformats.org/spreadsheetml/2006/main")
            foreach ($si in $ss.SelectNodes("//x:si", $nsmSs)) {
                $tNodes = $si.SelectNodes(".//x:t", $nsmSs)
                $combined = ""
                foreach ($t in $tNodes) { $combined += $t.InnerText }
                [void]$strings.Add($combined)
            }
        }
        Write-Host "  shared strings: $($strings.Count)"

        # 2. sheet name map
        $wbPath = Join-Path $tempDir "xl\workbook.xml"
        $sheetMap = @{}
        if (Test-Path $wbPath) {
            [xml]$wb = [System.IO.File]::ReadAllText($wbPath, [System.Text.Encoding]::UTF8)
            $nsmWb = New-Object System.Xml.XmlNamespaceManager($wb.NameTable)
            $nsmWb.AddNamespace("x", "http://schemas.openxmlformats.org/spreadsheetml/2006/main")
            $idx = 1
            foreach ($sheet in $wb.SelectNodes("//x:sheet", $nsmWb)) {
                $sheetMap["sheet$idx"] = $sheet.name
                $idx++
            }
        }
        Write-Host "  sheets: $($sheetMap.Count)"

        # 3. parse sheets
        $out = New-Object System.Text.StringBuilder
        [void]$out.AppendLine("################################################")
        [void]$out.AppendLine("# $label : $xlsxPath")
        [void]$out.AppendLine("################################################")

        $sheets = Get-ChildItem (Join-Path $tempDir "xl\worksheets\sheet*.xml") | Sort-Object {
            [int]($_.BaseName -replace 'sheet', '')
        }

        foreach ($sf in $sheets) {
            $sheetKey = $sf.BaseName
            $sheetName = if ($sheetMap.ContainsKey($sheetKey)) { $sheetMap[$sheetKey] } else { $sheetKey }

            [void]$out.AppendLine("")
            [void]$out.AppendLine("================================================")
            [void]$out.AppendLine("=== Sheet: $sheetName ($sheetKey) ===")
            [void]$out.AppendLine("================================================")

            [xml]$sx = [System.IO.File]::ReadAllText($sf.FullName, [System.Text.Encoding]::UTF8)
            $nsmSx = New-Object System.Xml.XmlNamespaceManager($sx.NameTable)
            $nsmSx.AddNamespace("x", "http://schemas.openxmlformats.org/spreadsheetml/2006/main")

            $rows = $sx.SelectNodes("//x:row", $nsmSx)
            $rowCount = 0
            foreach ($row in $rows) {
                $rowNum = $row.r
                $cellsText = New-Object System.Collections.ArrayList
                foreach ($c in $row.SelectNodes(".//x:c", $nsmSx)) {
                    $cellRef = $c.r
                    $val = ""
                    if ($c.t -eq "s") {
                        $vNode = $c.SelectSingleNode("x:v", $nsmSx)
                        if ($vNode) {
                            $strIdx = [int]$vNode.InnerText
                            if ($strIdx -lt $strings.Count) { $val = $strings[$strIdx] }
                        }
                    } elseif ($c.t -eq "inlineStr") {
                        $tNode = $c.SelectSingleNode(".//x:t", $nsmSx)
                        if ($tNode) { $val = $tNode.InnerText }
                    } else {
                        $vNode = $c.SelectSingleNode("x:v", $nsmSx)
                        if ($vNode) { $val = $vNode.InnerText }
                    }
                    if ($val -and $val.Length -gt 0) {
                        [void]$cellsText.Add("[$cellRef] $val")
                    }
                }
                if ($cellsText.Count -gt 0) {
                    [void]$out.AppendLine("--- Row $rowNum ---")
                    foreach ($ct in $cellsText) { [void]$out.AppendLine($ct) }
                    $rowCount++
                }
            }
            Write-Host "  $sheetName : $rowCount rows"
        }

        # 4. save UTF-8 with BOM
        [System.IO.File]::WriteAllText($outPath, $out.ToString(), [System.Text.UTF8Encoding]::new($true))

        $sizeKb = [math]::Round((Get-Item $outPath).Length / 1KB, 1)
        Write-Host "  [OK] saved: $sizeKb KB"
    }
    finally {
        if (Test-Path $tempDir) {
            Remove-Item -Recurse -Force $tempDir -ErrorAction SilentlyContinue
        }
    }
}

# Find xlsx files via directory pattern matching (avoid hangul literals)
$subdirs = Get-ChildItem -LiteralPath $VECTOR_DIR -Directory -ErrorAction SilentlyContinue

foreach ($sub in $subdirs) {
    $xlsx = Get-ChildItem -LiteralPath $sub.FullName -Filter "*.xlsx" -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($xlsx) {
        $outName = $sub.Name + "_xlsx_dump.txt"
        $outPath = Join-Path $BASE $outName
        $label = $sub.Name
        Extract-Xlsx -xlsxPath $xlsx.FullName -outPath $outPath -label $label
    } else {
        Write-Host "[skip] $($sub.Name) - no xlsx"
    }
}

Write-Host ""
Write-Host "==================================="
Write-Host "  All extraction done"
Write-Host "==================================="
Get-ChildItem -LiteralPath $BASE -Filter "*_xlsx_dump.txt" -File | ForEach-Object {
    Write-Host ("  - " + $_.Name + " (" + [math]::Round($_.Length / 1KB, 1) + " KB)")
}
Write-Host "==================================="
