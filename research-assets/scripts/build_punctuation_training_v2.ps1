param(
    [string]$OriginalTraining = 'C:\hyt-agent\训练集-微调版提示词\标点符号错误_训练集.jsonl',
    [string]$SourceWorkbook = 'C:\hyt-agent\数据集\完整数据集标点符号.xlsx',
    [string]$RecoveredTraining = 'C:\hyt-agent\outputs\punctuation_restore_126_20260826\punctuation_recovered_126_training.jsonl',
    [string]$RecoveredManifest = 'C:\hyt-agent\outputs\punctuation_restore_126_20260826\punctuation_recovered_126.jsonl',
    [string]$OutputTraining = 'C:\hyt-agent\训练集-微调版提示词\标点符号错误_训练集_v2.jsonl'
)

$ErrorActionPreference = 'Stop'

function Get-DetectionContent($record) {
    $content = [string]$record.messages[1].content
    $start = $content.IndexOf('{')
    if ($start -lt 0) { throw 'User message does not contain an input payload.' }
    return [string](($content.Substring($start) | ConvertFrom-Json).detection_content)
}

function Normalize-Newlines([string]$text) {
    return $text.Replace('\r\n', "`n").Replace('\n', "`n").Replace("`r`n", "`n").Replace("`r", "`n").TrimEnd()
}

$originalHashBefore = (Get-FileHash -Algorithm SHA256 -LiteralPath $OriginalTraining).Hash
$originalLines = [System.IO.File]::ReadAllLines($OriginalTraining, [System.Text.UTF8Encoding]::new($false))
$originalRecords = @($originalLines | ForEach-Object { $_ | ConvertFrom-Json })
$recoveredLines = [System.IO.File]::ReadAllLines($RecoveredTraining, [System.Text.UTF8Encoding]::new($false))
$recoveredRecords = @($recoveredLines | ForEach-Object { $_ | ConvertFrom-Json })
$recoveredManifestRows = @([System.IO.File]::ReadAllLines($RecoveredManifest, [System.Text.UTF8Encoding]::new($false)) | ForEach-Object { $_ | ConvertFrom-Json })

if ($originalRecords.Count -ne 1061) { throw "Expected 1061 original records, got $($originalRecords.Count)." }
if ($recoveredRecords.Count -ne 126 -or $recoveredManifestRows.Count -ne 126) { throw 'Recovered inputs must both contain 126 records.' }

# Reuse the tested XLSX reader from the recovery script without running its build body.
$readerScriptPath = 'C:\hyt-agent\scripts\restore_punctuation_126.ps1'
$readerScript = Get-Content -LiteralPath $readerScriptPath -Raw -Encoding UTF8
$readerPrefix = $readerScript.Substring(0, $readerScript.IndexOf('$decisions ='))
Invoke-Expression $readerPrefix
$sourceRows = @(Read-XlsxRows $SourceWorkbook)
if ($sourceRows.Count -ne $originalRecords.Count) { throw 'Workbook and training row counts differ.' }

$mappingMismatches = [System.Collections.Generic.List[int]]::new()
for ($index = 0; $index -lt $originalRecords.Count; $index++) {
    $trainingText = Normalize-Newlines (Get-DetectionContent $originalRecords[$index])
    $workbookText = Normalize-Newlines ([string]$sourceRows[$index].Values.error_content)
    if ($trainingText -ne $workbookText) { $mappingMismatches.Add($index + 1) }
}
if ($mappingMismatches.Count -ne 0) { throw "Training/workbook mapping mismatches: $($mappingMismatches.Count)." }

$sentenceEndIndices = @(
    0..($sourceRows.Count - 1) | Where-Object {
        $sourceRows[$_].Values.is_real_error -eq '1' -and
        $sourceRows[$_].Values.error_detailed_type -eq '句末点号误用'
    }
)
if ($sentenceEndIndices.Count -ne 535) { throw "Expected 535 sentence-end records, got $($sentenceEndIndices.Count)." }
$replaceIndices = @($sentenceEndIndices | Select-Object -First 126)

$systemPrompt = [string]$originalRecords[0].messages[0].content
foreach ($record in $recoveredRecords) {
    $answer = $record.messages[2].content | ConvertFrom-Json
    if ([string]$record.messages[0].content -ne $systemPrompt -or -not $answer.has_error -or $answer.total_errors -ne 1) {
        throw 'Recovered record prompt or answer validation failed.'
    }
}

$newLines = [string[]]$originalLines.Clone()
$replacementLog = [System.Collections.Generic.List[object]]::new()
for ($slot = 0; $slot -lt 126; $slot++) {
    $index = [int]$replaceIndices[$slot]
    $oldAnswer = $originalRecords[$index].messages[2].content | ConvertFrom-Json
    if (-not $oldAnswer.has_error) { throw "Replacement target $index is not a positive record." }
    $newLines[$index] = $recoveredLines[$slot]
    $replacementLog.Add([pscustomobject]@{
        training_line = $index + 1
        source_excel_row = $sourceRows[$index].ExcelRow
        removed_id = [string]$sourceRows[$index].Values.id
        removed_error_subtype = [string]$sourceRows[$index].Values.error_detailed_type
        removed_detection_content = Get-DetectionContent $originalRecords[$index]
        inserted_recovery_id = [string]$recoveredManifestRows[$slot].recovery_id
        inserted_decision_index = [int]$recoveredManifestRows[$slot].decision_index
        inserted_error_subtype = [string]$recoveredManifestRows[$slot].error_subtype
        inserted_detection_content = [string]$recoveredManifestRows[$slot].error_question
    })
}

[System.IO.File]::WriteAllLines($OutputTraining, $newLines, [System.Text.UTF8Encoding]::new($false))
$outputRecords = @([System.IO.File]::ReadAllLines($OutputTraining, [System.Text.UTF8Encoding]::new($false)) | ForEach-Object { $_ | ConvertFrom-Json })

$positiveCount = 0
$negativeCount = 0
$invalidAnswers = 0
$wrongSystemPrompt = 0
$detections = [System.Collections.Generic.List[string]]::new()
foreach ($record in $outputRecords) {
    if ([string]$record.messages[0].content -ne $systemPrompt) { $wrongSystemPrompt++ }
    try { $answer = $record.messages[2].content | ConvertFrom-Json } catch { $invalidAnswers++; continue }
    if ($answer.has_error) { $positiveCount++ } else { $negativeCount++ }
    if ($answer.total_errors -ne $answer.errors.Count) { $invalidAnswers++ }
    $detections.Add((Get-DetectionContent $record))
}
$duplicateDetectionCount = @($detections | Group-Object | Where-Object Count -gt 1).Count

$distribution = [ordered]@{}
foreach ($row in $sourceRows) {
    if ($row.Values.is_real_error -ne '1') { continue }
    $type = [string]$row.Values.error_detailed_type
    if (-not $distribution.Contains($type)) { $distribution[$type] = 0 }
    $distribution[$type]++
}
$distribution['句末点号误用'] -= 126
foreach ($row in $recoveredManifestRows) {
    $type = [string]$row.error_subtype
    if (-not $distribution.Contains($type)) { $distribution[$type] = 0 }
    $distribution[$type]++
}
$distribution = [ordered]@{
    '句末点号误用' = [int]$distribution['句末点号误用']
    '引号内外标点位置' = [int]$distribution['引号内外标点位置']
    '引号滥用或缺失' = [int]$distribution['引号滥用或缺失']
    '冒号、分号误用' = [int]$distribution['冒号、分号误用']
    '引号、括号、书名号等配对错误' = [int]$distribution['引号、括号、书名号等配对错误']
    '标点冗余或缺失' = [int]$distribution['标点冗余或缺失']
    '选项与编号标点误用' = [int]$distribution['选项与编号标点误用']
    '破折号、连接号误用' = [int]$distribution['破折号、连接号误用']
    '停顿符号误用' = [int]$distribution['停顿符号误用']
    '省略号误用' = [int]$distribution['省略号误用']
}

$outputDirectory = Split-Path -Parent $OutputTraining
$logPath = Join-Path $outputDirectory '标点符号错误_训练集_v2_替换清单.jsonl'
$logLines = @($replacementLog | ForEach-Object { $_ | ConvertTo-Json -Compress -Depth 6 })
[System.IO.File]::WriteAllLines($logPath, $logLines, [System.Text.UTF8Encoding]::new($false))

$originalHashAfter = (Get-FileHash -Algorithm SHA256 -LiteralPath $OriginalTraining).Hash
$verification = [ordered]@{
    generated_at = (Get-Date).ToString('s')
    original_training = $OriginalTraining
    output_training = $OutputTraining
    original_sha256_before = $originalHashBefore
    original_sha256_after = $originalHashAfter
    original_unchanged = ($originalHashBefore -eq $originalHashAfter)
    output_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $OutputTraining).Hash
    total_records = $outputRecords.Count
    positive_records = $positiveCount
    negative_records = $negativeCount
    replaced_sentence_end_records = 126
    inserted_recovered_records = 126
    invalid_answers = $invalidAnswers
    wrong_system_prompt = $wrongSystemPrompt
    duplicate_detection_groups = $duplicateDetectionCount
    distribution = $distribution
}
$verificationPath = Join-Path $outputDirectory '标点符号错误_训练集_v2_校验报告.json'
$verification | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $verificationPath -Encoding UTF8

if (-not $verification.original_unchanged -or $positiveCount -ne 580 -or $negativeCount -ne 481 -or $invalidAnswers -ne 0 -or $wrongSystemPrompt -ne 0) {
    throw 'Final validation failed.'
}
$verification | ConvertTo-Json -Depth 8
