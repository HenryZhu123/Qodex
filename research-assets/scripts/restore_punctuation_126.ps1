param(
    [string]$SourceDirectory = "C:\hyt-agent\外部数据源\结构化试题",
    [string]$DecisionFile = "C:\hyt-agent\outputs\punctuation_single_word_repair_20260820\manual_error_decisions.jsonl",
    [string]$OutputDirectory = "C:\hyt-agent\outputs\punctuation_restore_126_20260826",
    [switch]$PreviewOnly
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Get-ColumnIndex([string]$cellReference) {
    $letters = [regex]::Match($cellReference, '^[A-Z]+').Value
    $value = 0
    foreach ($character in $letters.ToCharArray()) {
        $value = ($value * 26) + ([int][char]$character - [int][char]'A' + 1)
    }
    return $value - 1
}

function Read-ZipEntryText($zip, [string]$entryName) {
    $entry = $zip.GetEntry($entryName)
    if ($null -eq $entry) { return $null }
    $reader = [System.IO.StreamReader]::new($entry.Open())
    try { return $reader.ReadToEnd() } finally { $reader.Dispose() }
}

function Read-XlsxRows([string]$path) {
    $zip = [System.IO.Compression.ZipFile]::OpenRead($path)
    try {
        $sharedStrings = [System.Collections.Generic.List[string]]::new()
        $sharedXmlText = Read-ZipEntryText $zip 'xl/sharedStrings.xml'
        if ($sharedXmlText) {
            [xml]$sharedXml = $sharedXmlText
            $sharedNs = [System.Xml.XmlNamespaceManager]::new($sharedXml.NameTable)
            $sharedNs.AddNamespace('x', 'http://schemas.openxmlformats.org/spreadsheetml/2006/main')
            foreach ($item in $sharedXml.SelectNodes('//x:si', $sharedNs)) {
                $sharedStrings.Add((($item.SelectNodes('.//x:t', $sharedNs) | ForEach-Object { $_.InnerText }) -join ''))
            }
        }

        [xml]$workbookXml = Read-ZipEntryText $zip 'xl/workbook.xml'
        [xml]$relsXml = Read-ZipEntryText $zip 'xl/_rels/workbook.xml.rels'
        $workbookNs = [System.Xml.XmlNamespaceManager]::new($workbookXml.NameTable)
        $workbookNs.AddNamespace('x', 'http://schemas.openxmlformats.org/spreadsheetml/2006/main')
        $workbookNs.AddNamespace('r', 'http://schemas.openxmlformats.org/officeDocument/2006/relationships')
        $relMap = @{}
        foreach ($rel in $relsXml.Relationships.Relationship) { $relMap[[string]$rel.Id] = [string]$rel.Target }

        $result = [System.Collections.Generic.List[object]]::new()
        foreach ($sheet in $workbookXml.SelectNodes('//x:sheets/x:sheet', $workbookNs)) {
            $relId = $sheet.GetAttribute('id', 'http://schemas.openxmlformats.org/officeDocument/2006/relationships')
            $target = $relMap[$relId].Replace('\', '/')
            if ($target.StartsWith('/')) { $sheetEntry = $target.TrimStart('/') }
            elseif ($target.StartsWith('xl/')) { $sheetEntry = $target }
            else { $sheetEntry = 'xl/' + $target.TrimStart('/') }
            [xml]$sheetXml = Read-ZipEntryText $zip $sheetEntry
            $sheetNs = [System.Xml.XmlNamespaceManager]::new($sheetXml.NameTable)
            $sheetNs.AddNamespace('x', 'http://schemas.openxmlformats.org/spreadsheetml/2006/main')
            $rawRows = [System.Collections.Generic.List[object]]::new()
            foreach ($rowNode in $sheetXml.SelectNodes('//x:sheetData/x:row', $sheetNs)) {
                $cells = @{}
                foreach ($cell in $rowNode.SelectNodes('./x:c', $sheetNs)) {
                    $column = Get-ColumnIndex ([string]$cell.r)
                    $type = [string]$cell.t
                    if ($type -eq 's') {
                        $valueNode = $cell.SelectSingleNode('./x:v', $sheetNs)
                        $value = if ($null -ne $valueNode) { $sharedStrings[[int]$valueNode.InnerText] } else { '' }
                    } elseif ($type -eq 'inlineStr') {
                        $value = (($cell.SelectNodes('./x:is//x:t', $sheetNs) | ForEach-Object { $_.InnerText }) -join '')
                    } else {
                        $valueNode = $cell.SelectSingleNode('./x:v', $sheetNs)
                        $value = if ($null -ne $valueNode) { [string]$valueNode.InnerText } else { '' }
                    }
                    $cells[$column] = [string]$value
                }
                $rawRows.Add([pscustomobject]@{ ExcelRow = [int]$rowNode.r; Cells = $cells })
            }
            if ($rawRows.Count -eq 0) { continue }
            $headerRow = $rawRows[0]
            $headers = @{}
            foreach ($key in $headerRow.Cells.Keys) {
                $name = [string]$headerRow.Cells[$key]
                if ([string]::IsNullOrWhiteSpace($name)) { $name = "column_$key" }
                $headers[$key] = $name
            }
            foreach ($rawRow in $rawRows | Select-Object -Skip 1) {
                $named = [ordered]@{}
                foreach ($key in ($headers.Keys | Sort-Object)) { $named[$headers[$key]] = if ($rawRow.Cells.ContainsKey($key)) { $rawRow.Cells[$key] } else { '' } }
                foreach ($key in ($rawRow.Cells.Keys | Where-Object { -not $headers.ContainsKey($_) } | Sort-Object)) { $named["column_$key"] = $rawRow.Cells[$key] }
                $result.Add([pscustomobject]@{
                    SourceFile = $path
                    SourceSheet = [string]$sheet.name
                    ExcelRow = $rawRow.ExcelRow
                    Values = [pscustomobject]$named
                    CellTexts = @($rawRow.Cells.Values | ForEach-Object { [string]$_ })
                })
            }
        }
        return $result
    } finally {
        $zip.Dispose()
    }
}

$decisions = @(Get-Content -LiteralPath $DecisionFile -Encoding UTF8 | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json })
$allRows = [System.Collections.Generic.List[object]]::new()
foreach ($file in (Get-ChildItem -LiteralPath $SourceDirectory -File -Filter '*.xlsx' | Sort-Object Name)) {
    $rows = @(Read-XlsxRows $file.FullName)
    foreach ($row in $rows) { $allRows.Add($row) }
    Write-Host "READ $($file.Name): $($rows.Count) rows"
}

$candidates = [System.Collections.Generic.List[object]]::new()
foreach ($decision in $decisions) {
    foreach ($row in $allRows) {
        foreach ($cellText in $row.CellTexts) {
            $text = [string]$cellText
            if (-not $text.Contains([string]$decision.find)) { continue }
            $occurrences = ([regex]::Matches($text, [regex]::Escape([string]$decision.find))).Count
            if ($occurrences -ne 1) { continue }
            $candidates.Add([pscustomobject]@{
                DecisionIndex = [int]$decision.index
                Find = [string]$decision.find
                Replace = [string]$decision.replace
                Reason = [string]$decision.reason
                SourceFile = [System.IO.Path]::GetFileName($row.SourceFile)
                SourcePath = $row.SourceFile
                SourceSheet = $row.SourceSheet
                SourceExcelRow = $row.ExcelRow
                OriginalQuestion = $text
                ErrorQuestion = $text.Replace([string]$decision.find, [string]$decision.replace)
                SourceValues = $row.Values
            })
        }
    }
}
Write-Host "CANDIDATES: $($candidates.Count)"

$candidateGroups = $candidates | Group-Object DecisionIndex
$diagnostic = foreach ($decision in $decisions) {
    $group = $candidateGroups | Where-Object { [int]$_.Name -eq [int]$decision.index } | Select-Object -First 1
    [pscustomobject]@{
        DecisionIndex = [int]$decision.index
        Find = [string]$decision.find
        CandidateCount = if ($null -eq $group) { 0 } else { $group.Count }
        CandidateFiles = if ($null -eq $group) { '' } else { (($group.Group.SourceFile | Sort-Object -Unique) -join '|') }
    }
}

if ($PreviewOnly) {
    $diagnostic | Sort-Object DecisionIndex | Format-Table -Wrap -AutoSize
    exit 0
}

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$diagnostic | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'candidate_diagnostic.json') -Encoding UTF8
$candidates | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'all_candidates.json') -Encoding UTF8

# The five surviving source workbooks contributed exactly these counts in the original build.
$quotas = [ordered]@{
    '2022重庆理工大学.xlsx' = 26
    '2022重庆理工大学（2）.xlsx' = 26
    '2023重庆理工大学.xlsx' = 26
    '2023重庆理工大学（2）.xlsx' = 26
    '广西民族大学.xlsx' = 22
}

$selected = [System.Collections.Generic.List[object]]::new()
$usedKeys = [System.Collections.Generic.HashSet[string]]::new()
$fileCounts = @{}
foreach ($fileName in $quotas.Keys) { $fileCounts[$fileName] = 0 }

# First accept decisions with only one possible source row.
foreach ($group in ($candidateGroups | Where-Object Count -eq 1 | Sort-Object { [int]$_.Name })) {
    $candidate = $group.Group[0]
    if ($fileCounts[$candidate.SourceFile] -ge $quotas[$candidate.SourceFile]) { continue }
    $key = "$($candidate.SourceFile)|$($candidate.SourceSheet)|$($candidate.SourceExcelRow)"
    if ($usedKeys.Add($key)) {
        $selected.Add($candidate)
        $fileCounts[$candidate.SourceFile]++
    }
}

# Resolve the few repeated phrases by filling the known per-file quotas, preferring unused rows.
# Decision 1 belongs to the missing Wuyi University source. The remaining repeated
# phrases can be resolved from the surviving-workbook quotas and unused source rows.
$ambiguousAssignments = @(
    [pscustomobject]@{ Index = 25; File = '2022重庆理工大学.xlsx'; Row = 216 }
    [pscustomobject]@{ Index = 37; File = '广西民族大学.xlsx'; Row = 118 }
    [pscustomobject]@{ Index = 38; File = '2023重庆理工大学.xlsx'; Row = 44 }
    [pscustomobject]@{ Index = 42; File = '2022重庆理工大学.xlsx'; Row = 220 }
    [pscustomobject]@{ Index = 58; File = '2023重庆理工大学（2）.xlsx'; Row = 170 }
    [pscustomobject]@{ Index = 115; File = '2022重庆理工大学.xlsx'; Row = 160 }
    [pscustomobject]@{ Index = 121; File = '2022重庆理工大学.xlsx'; Row = 166 }
)
foreach ($assignment in $ambiguousAssignments) {
    $decisionIndex = [int]$assignment.Index
    $group = $candidateGroups | Where-Object { [int]$_.Name -eq $decisionIndex } | Select-Object -First 1
    if ($null -eq $group) { continue }
    $options = @($group.Group | Where-Object {
        $_.SourceFile -eq $assignment.File -and $_.SourceExcelRow -eq $assignment.Row
    })
    if ($options.Count -ne 1) { throw "Cannot uniquely resolve decision $decisionIndex" }
    $candidate = $options[0]
    $key = "$($candidate.SourceFile)|$($candidate.SourceSheet)|$($candidate.SourceExcelRow)"
    if ($usedKeys.Add($key)) {
        $selected.Add($candidate)
        $fileCounts[$candidate.SourceFile]++
    }
}

<#
foreach ($group in ($candidateGroups | Where-Object Count -gt 1 | Sort-Object { [int]$_.Name })) {
    if ($selected.DecisionIndex -contains [int]$group.Name) { continue }
    $options = @($group.Group | Where-Object {
        $key = "$($_.SourceFile)|$($_.SourceSheet)|$($_.SourceExcelRow)"
        (-not $usedKeys.Contains($key)) -and ($fileCounts[$_.SourceFile] -lt $quotas[$_.SourceFile])
    } | Sort-Object @{Expression={ $quotas[$_.SourceFile] - $fileCounts[$_.SourceFile] }; Descending=$true}, SourceFile, SourceExcelRow)
    if ($options.Count -eq 0) { continue }
    $candidate = $options[0]
    $key = "$($candidate.SourceFile)|$($candidate.SourceSheet)|$($candidate.SourceExcelRow)"
    if ($usedKeys.Add($key)) {
        $selected.Add($candidate)
        $fileCounts[$candidate.SourceFile]++
    }
}
#>

$selected = @($selected | Sort-Object DecisionIndex)
$recoveredJsonl = Join-Path $OutputDirectory 'punctuation_recovered_126.jsonl'
$trainingLines = [System.Collections.Generic.List[string]]::new()
$trainingSource = 'C:\hyt-agent\训练集-微调版提示词\标点符号错误_训练集.jsonl'
$firstTrainingRecord = (Get-Content -LiteralPath $trainingSource -Encoding UTF8 -TotalCount 1) | ConvertFrom-Json
$systemPrompt = [string]$firstTrainingRecord.messages[0].content
$jsonLines = foreach ($item in $selected) {
    $subtype = if ($item.DecisionIndex -eq 1) { '引号、括号、书名号等配对错误' }
        elseif ($item.DecisionIndex -eq 2) { '停顿符号误用' }
        elseif ($item.DecisionIndex -eq 3) { '省略号误用' }
        elseif ($item.DecisionIndex -le 5) { '标点冗余或缺失' }
        elseif ($item.DecisionIndex -le 10) { '破折号、连接号误用' }
        elseif ($item.DecisionIndex -le 31) { '引号滥用或缺失' }
        elseif ($item.DecisionIndex -le 67) { '句末点号误用' }
        else { '引号内外标点位置' }
    $goldAnswer = [ordered]@{
        reason = [string]$item.Reason
        has_error = $true
        total_errors = 1
        errors = @([ordered]@{
            error_type = '标点符号错误'
            position = ('题干中“{0}”所在位置' -f $item.Replace)
            original_text = [string]$item.Replace
            anchor_text = [string]$item.ErrorQuestion
            correction = [string]$item.Find
            description = [string]$item.Reason
            suggestion = ('将“{0}”改为“{1}”。' -f $item.Replace, $item.Find)
        })
    }
    $record = [ordered]@{
        recovery_id = "punctuation_restore_20260826_$(('{0:D3}' -f [int]$item.DecisionIndex))"
        decision_index = $item.DecisionIndex
        error_type = '标点符号错误'
        error_subtype = $subtype
        source_file = $item.SourceFile
        source_path = $item.SourcePath
        source_sheet = $item.SourceSheet
        source_excel_row = $item.SourceExcelRow
        original_question = $item.OriginalQuestion
        error_question = $item.ErrorQuestion
        find = $item.Find
        replace = $item.Replace
        reason = $item.Reason
        standard_answer = $goldAnswer
        source_values = $item.SourceValues
    }
    $subject = [string]$item.SourceValues.school
    $questionType = [string]$item.SourceValues.title
    $reference = "【学科】$subject`n【试卷标题】# $subject`n【题型或其它信息】$questionType"
    $payload = [ordered]@{ reference = $reference; detection_content = [string]$item.ErrorQuestion }
    $trainingRecord = [ordered]@{
        messages = @(
            [ordered]@{ role = 'system'; content = $systemPrompt }
            [ordered]@{ role = 'user'; content = "[INPUT_PAYLOAD]`n$($payload | ConvertTo-Json -Compress -Depth 5)" }
            [ordered]@{ role = 'assistant'; content = ($goldAnswer | ConvertTo-Json -Compress -Depth 6) }
        )
    }
    $trainingLines.Add(($trainingRecord | ConvertTo-Json -Compress -Depth 10))
    $record | ConvertTo-Json -Compress -Depth 8
}
[System.IO.File]::WriteAllLines($recoveredJsonl, $jsonLines, [System.Text.UTF8Encoding]::new($false))
[System.IO.File]::WriteAllLines((Join-Path $OutputDirectory 'punctuation_recovered_126_training.jsonl'), $trainingLines, [System.Text.UTF8Encoding]::new($false))

$selected | Select-Object DecisionIndex,SourceFile,SourceSheet,SourceExcelRow,OriginalQuestion,ErrorQuestion,Find,Replace,Reason |
    Export-Csv -LiteralPath (Join-Path $OutputDirectory 'punctuation_recovered_126.csv') -NoTypeInformation -Encoding UTF8

$verification = [ordered]@{
    generated_at = (Get-Date).ToString('s')
    decision_total = $decisions.Count
    recovered_total = $selected.Count
    unrecovered_decision_indices = @($decisions.index | Where-Object { $selected.DecisionIndex -notcontains [int]$_ })
    recovered_by_source = [ordered]@{}
    exact_one_replacement = (@($selected | Where-Object {
        $_.OriginalQuestion -ne $_.ErrorQuestion -and
        ([regex]::Matches($_.OriginalQuestion, [regex]::Escape($_.Find))).Count -eq 1
    }).Count -eq $selected.Count)
    unique_source_rows = ($usedKeys.Count -eq $selected.Count)
}
foreach ($fileName in $quotas.Keys) { $verification.recovered_by_source[$fileName] = [int]$fileCounts[$fileName] }
$verification | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'verification.json') -Encoding UTF8

$verification | ConvertTo-Json -Depth 8
