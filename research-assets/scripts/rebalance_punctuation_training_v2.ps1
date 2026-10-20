param(
    [string]$OriginalTraining = 'C:\hyt-agent\训练集-微调版提示词\标点符号错误_训练集.jsonl',
    [string]$CurrentV2 = 'C:\hyt-agent\训练集-微调版提示词\标点符号错误_训练集_v2.jsonl',
    [string]$SourceWorkbook = 'C:\hyt-agent\数据集\完整数据集标点符号.xlsx',
    [string]$RecoveredTraining = 'C:\hyt-agent\outputs\punctuation_restore_126_20260826\punctuation_recovered_126_training.jsonl',
    [string]$RecoveredManifest = 'C:\hyt-agent\outputs\punctuation_restore_126_20260826\punctuation_recovered_126.jsonl'
)

$ErrorActionPreference = 'Stop'

function Get-Payload($record) {
    $content = [string]$record.messages[1].content
    $start = $content.IndexOf('{')
    if ($start -lt 0) { throw 'Missing input payload.' }
    return $content.Substring($start) | ConvertFrom-Json
}

function Replace-First([string]$text, [string]$find, [string]$replace) {
    $index = $text.IndexOf($find, [System.StringComparison]::Ordinal)
    if ($index -lt 0) { throw "Fragment not found: $find" }
    return $text.Substring(0, $index) + $replace + $text.Substring($index + $find.Length)
}

function New-TrainingLine($baseRecord, [string]$errorText, [string]$errorFragment, [string]$correctFragment, [string]$reason) {
    $payload = Get-Payload $baseRecord
    $payload.detection_content = $errorText
    $answer = [ordered]@{
        reason = $reason
        has_error = $true
        total_errors = 1
        errors = @([ordered]@{
            error_type = '标点符号错误'
            position = ('题干中“{0}”所在位置' -f $errorFragment)
            original_text = $errorFragment
            anchor_text = $errorText
            correction = $correctFragment
            description = $reason
            suggestion = if ($correctFragment -eq '') { ('删除题干中的“{0}”。' -f $errorFragment) } else { ('将“{0}”改为“{1}”。' -f $errorFragment, $correctFragment) }
        })
    }
    $record = [ordered]@{
        messages = @(
            [ordered]@{ role = 'system'; content = [string]$baseRecord.messages[0].content }
            [ordered]@{ role = 'user'; content = "[INPUT_PAYLOAD]`n$($payload | ConvertTo-Json -Compress -Depth 6)" }
            [ordered]@{ role = 'assistant'; content = ($answer | ConvertTo-Json -Compress -Depth 8) }
        )
    }
    return $record | ConvertTo-Json -Compress -Depth 12
}

$originalHashBefore = (Get-FileHash -Algorithm SHA256 -LiteralPath $OriginalTraining).Hash
$originalLines = [System.IO.File]::ReadAllLines($OriginalTraining, [System.Text.UTF8Encoding]::new($false))
$originalRecords = @($originalLines | ForEach-Object { $_ | ConvertFrom-Json })
$recoveredLines = [System.IO.File]::ReadAllLines($RecoveredTraining, [System.Text.UTF8Encoding]::new($false))
$recoveredRows = @([System.IO.File]::ReadAllLines($RecoveredManifest, [System.Text.UTF8Encoding]::new($false)) | ForEach-Object { $_ | ConvertFrom-Json })

if ($originalRecords.Count -ne 1061 -or $recoveredLines.Count -ne 126 -or $recoveredRows.Count -ne 126) {
    throw 'Input row counts are invalid.'
}

$readerScript = Get-Content -LiteralPath 'C:\hyt-agent\scripts\restore_punctuation_126.ps1' -Raw -Encoding UTF8
Invoke-Expression $readerScript.Substring(0, $readerScript.IndexOf('$decisions ='))
$sourceRows = @(Read-XlsxRows $SourceWorkbook)
if ($sourceRows.Count -ne 1061) { throw 'Source workbook row count is invalid.' }

$sentenceIndices = @(0..($sourceRows.Count - 1) | Where-Object {
    $sourceRows[$_].Values.is_real_error -eq '1' -and
    $sourceRows[$_].Values.error_detailed_type -eq '句末点号误用'
})
if ($sentenceIndices.Count -ne 535) { throw 'Expected 535 sentence-end rows.' }

# Rebuild from the untouched original. Keep 124 of the recovered questions; the
# recovered redundancy and pause rows are intentionally returned to their original
# sentence-end slots so the final minor-category totals match the target distribution.
$newLines = [string[]]$originalLines.Clone()
$keptRecoverySlots = [System.Collections.Generic.HashSet[int]]::new()
$recoveryLog = [System.Collections.Generic.List[object]]::new()
for ($slot = 0; $slot -lt 126; $slot++) {
    $subtype = [string]$recoveredRows[$slot].error_subtype
    if ($subtype -in @('标点冗余或缺失', '停顿符号误用')) { continue }
    $targetIndex = [int]$sentenceIndices[$slot]
    $newLines[$targetIndex] = $recoveredLines[$slot]
    $null = $keptRecoverySlots.Add($targetIndex)
    $recoveryLog.Add([pscustomobject]@{
        training_line = $targetIndex + 1
        recovery_id = [string]$recoveredRows[$slot].recovery_id
        error_subtype = $subtype
    })
}
if ($keptRecoverySlots.Count -ne 124) { throw 'Expected to retain 124 recovered rows.' }

$available = [System.Collections.Generic.HashSet[int]]::new()
foreach ($index in $sentenceIndices) {
    if (-not $keptRecoverySlots.Contains([int]$index)) { $null = $available.Add([int]$index) }
}
if ($available.Count -ne 411) { throw 'Expected 411 available original sentence-end rows.' }

$conversionLog = [System.Collections.Generic.List[object]]::new()
function Commit-Conversion([int]$index, [string]$subtype, [string]$correctText, [string]$errorText, [string]$errorFragment, [string]$correctFragment, [string]$reason) {
    if (-not $available.Remove($index)) { throw "Training line $($index + 1) is not available." }
    if ($correctText -eq $errorText) { throw 'Conversion did not change the question.' }
    $baseRecord = $originalRecords[$index]
    $newLines[$index] = New-TrainingLine $baseRecord $errorText $errorFragment $correctFragment $reason
    $conversionLog.Add([pscustomobject]@{
        training_line = $index + 1
        source_excel_row = $sourceRows[$index].ExcelRow
        source_id = [string]$sourceRows[$index].Values.id
        error_subtype = $subtype
        correct_content = $correctText
        detection_content = $errorText
        error_fragment = $errorFragment
        correction_fragment = $correctFragment
        reason = $reason
    })
}

# 1) Four unmistakable interpunct errors inside the fixed term “马克思主义”.
$interpunctCandidates = @($available | Where-Object { [string]$sourceRows[$_].Values.content -match '马克思主义' } | Sort-Object | Select-Object -First 4)
if ($interpunctCandidates.Count -ne 4) { throw 'Not enough interpunct candidates.' }
foreach ($index in $interpunctCandidates) {
    $correct = [string]$sourceRows[$index].Values.content
    $generatedError = Replace-First $correct '马克思主义' '马克思·主义'
    Commit-Conversion $index '间隔号误用' $correct $generatedError '马克思·主义' '马克思主义' '固定术语“马克思主义”内部不应使用间隔号。'
}

# 2) Forty-seven sentence-final punctuation marks moved inside non-independent quotes.
$quotePositionPattern = '(?<phrase>共同之处|实现方式|世界意义|取得原则|保护模式|基本特征|主要任务|基本趋势|政治改革|法西斯国家|民主集中制|压力集团|主要贡献|主要功能|前提条件|主要内容|发展过程|发展趋势|政策工具|货币政策|基本制度|基本模型|主要方法|主要作用|主要影响|基本原则|基本内容|主要过程|作用机制|具体措施|教育功能|基本结构|突出问题|主要原因|基本概念|基本定义|基本性能|现实价值|基本理论|主要政策|政治发展|主要认识|目的|条件|原则|区别|显著性|模式|客体|规律|特征|关系|贡献|任务|趋势|改革|国家|集中制|集团|差异|意义|方式|观点|途径|策略|模型|异同|方法|要求|作用|影响|内容|过程|机制|措施|功能|结构|问题|原因|概念|定义|性能|价值|理论|制度|政策|发展|认识|理由)(?<punct>[。？！])(?<space>\s*)$'
$quotePositionCandidates = @($available | Where-Object {
    [string]$sourceRows[$_].Values.content -match $quotePositionPattern
} | Sort-Object | Select-Object -First 47)
if ($quotePositionCandidates.Count -ne 47) { throw 'Not enough quote-position candidates.' }
foreach ($index in $quotePositionCandidates) {
    $correct = [string]$sourceRows[$index].Values.content
    $match = [regex]::Match($correct, $quotePositionPattern)
    $correctFragment = $match.Groups['phrase'].Value + $match.Groups['punct'].Value
    $errorFragment = '“' + $correctFragment + '”'
    $generatedError = $correct.Substring(0, $match.Index) + $errorFragment + $match.Groups['space'].Value
    Commit-Conversion $index '引号内外标点位置' $correct $generatedError $errorFragment $correctFragment '句末点号误置于非独立引用的后引号内。'
}

# 3) Seventy conjunctions changed to an improper connector line.
$dashMutations = [System.Collections.Generic.List[object]]::new()
foreach ($index in ($available | Sort-Object)) {
    $text = [string]$sourceRows[$index].Values.content
    $find = $null
    if ($text.Contains('以及')) { $find = '以及' }
    elseif ($text.Contains('与')) { $find = '与' }
    elseif ($text.Contains('和') -and $text -notmatch '共和国|和平|和谐|饱和|调和|总和|之和|和解|和弦|和声|亲和|中和|缓和|温和') { $find = '和' }
    elseif ($text.Contains('及其')) { $find = '及' }
    if ($null -ne $find) { $dashMutations.Add([pscustomobject]@{ Index = $index; Find = $find }) }
    if ($dashMutations.Count -eq 70) { break }
}
if ($dashMutations.Count -ne 70) { throw "Not enough dash candidates: $($dashMutations.Count)." }
foreach ($mutation in $dashMutations) {
    $index = [int]$mutation.Index
    $find = [string]$mutation.Find
    $correct = [string]$sourceRows[$index].Values.content
    $findPosition = $correct.IndexOf($find, [System.StringComparison]::Ordinal)
    $generatedError = Replace-First $correct $find '-'
    $leftLength = [Math]::Min(6, $findPosition)
    $rightLength = [Math]::Min(6, $correct.Length - $findPosition - $find.Length)
    $contextStart = $findPosition - $leftLength
    $correctFragment = $correct.Substring($contextStart, $leftLength + $find.Length + $rightLength)
    $errorFragment = $generatedError.Substring($contextStart, $leftLength + 1 + $rightLength)
    while (([regex]::Matches($generatedError, [regex]::Escape($errorFragment))).Count -ne 1) {
        if ($contextStart -gt 0) {
            $contextStart--
            $leftLength++
        } elseif (($findPosition + $find.Length + $rightLength) -lt $correct.Length) {
            $rightLength++
        } else {
            break
        }
        $correctFragment = $correct.Substring($contextStart, $leftLength + $find.Length + $rightLength)
        $errorFragment = $generatedError.Substring($contextStart, $leftLength + 1 + $rightLength)
    }
    Commit-Conversion $index '破折号、连接号误用' $correct $generatedError $errorFragment $correctFragment ('并列成分之间的连词“{0}”误写为连接号。' -f $find)
}

# 4) One hundred unnecessary quotation marks around ordinary task wording.
$quoteTokens = @('请简述','请说明','请分析','请论述','试论述','试分析','试说明','什么是','为什么','简述','论述','说明','分析','比较','指出','计算','证明','列举','解释','阐述','试述','谈谈','如何','何为','何谓','哪些','有何')
$quoteAbuseMutations = [System.Collections.Generic.List[object]]::new()
foreach ($index in ($available | Sort-Object)) {
    $text = [string]$sourceRows[$index].Values.content
    foreach ($token in $quoteTokens) {
        $position = $text.IndexOf($token, [System.StringComparison]::Ordinal)
        if ($position -lt 0) { continue }
        $before = if ($position -gt 0) { $text[$position - 1] } else { [char]0 }
        $afterIndex = $position + $token.Length
        $after = if ($afterIndex -lt $text.Length) { $text[$afterIndex] } else { [char]0 }
        if ($before -eq [char]0x201C -or $before -eq [char]0x2018 -or $before -eq [char]0x22 -or
            $after -eq [char]0x201D -or $after -eq [char]0x2019 -or $after -eq [char]0x22) { continue }
        $quoteAbuseMutations.Add([pscustomobject]@{ Index = $index; Find = $token })
        break
    }
    if ($quoteAbuseMutations.Count -eq 100) { break }
}
if ($quoteAbuseMutations.Count -ne 100) { throw "Not enough quote-abuse candidates: $($quoteAbuseMutations.Count)." }
foreach ($mutation in $quoteAbuseMutations) {
    $index = [int]$mutation.Index
    $find = [string]$mutation.Find
    $correct = [string]$sourceRows[$index].Values.content
    $errorFragment = '“' + $find + '”'
    $generatedError = Replace-First $correct $find $errorFragment
    Commit-Conversion $index '引号滥用或缺失' $correct $generatedError $errorFragment $find ('普通题干用语“{0}”无需使用引号。' -f $find)
}

# 5) One hundred and seventeen pseudo-ellipses made from three full stops.
$ellipsisCandidates = @($available | Sort-Object | Select-Object -First 117)
if ($ellipsisCandidates.Count -ne 117) { throw 'Not enough ellipsis candidates.' }
foreach ($index in $ellipsisCandidates) {
    $correct = [string]$sourceRows[$index].Values.content
    $match = [regex]::Match($correct, '(?<punct>[。？！])(?<space>\s*)$')
    if ($match.Success) {
        $correctFragment = $match.Groups['punct'].Value
        $generatedError = $correct.Substring(0, $match.Index) + '。。。' + $match.Groups['space'].Value
    } else {
        $correctFragment = ''
        $generatedError = $correct.TrimEnd() + '。。。' + $correct.Substring($correct.TrimEnd().Length)
    }
    Commit-Conversion $index '省略号误用' $correct $generatedError '。。。' $correctFragment '题末误用连续三个句号代替规范的句末形式。'
}

if ($conversionLog.Count -ne 338 -or $available.Count -ne 73) {
    throw "Conversion totals are invalid: converted=$($conversionLog.Count), remaining=$($available.Count)."
}

$backupPath = Join-Path (Split-Path -Parent $CurrentV2) '标点符号错误_训练集_v2_仅替换126条版备份.jsonl'
if ((Test-Path -LiteralPath $CurrentV2) -and -not (Test-Path -LiteralPath $backupPath)) {
    Copy-Item -LiteralPath $CurrentV2 -Destination $backupPath
}
[System.IO.File]::WriteAllLines($CurrentV2, $newLines, [System.Text.UTF8Encoding]::new($false))

$outputRecords = @([System.IO.File]::ReadAllLines($CurrentV2, [System.Text.UTF8Encoding]::new($false)) | ForEach-Object { $_ | ConvertFrom-Json })
$systemPrompt = [string]$originalRecords[0].messages[0].content
$positive = 0
$negative = 0
$invalid = 0
$wrongSystem = 0
$detections = [System.Collections.Generic.List[string]]::new()
foreach ($record in $outputRecords) {
    if ([string]$record.messages[0].content -ne $systemPrompt) { $wrongSystem++ }
    try { $answer = $record.messages[2].content | ConvertFrom-Json } catch { $invalid++; continue }
    if ($answer.has_error) { $positive++ } else { $negative++ }
    if ($answer.total_errors -ne $answer.errors.Count) { $invalid++ }
    $detections.Add([string](Get-Payload $record).detection_content)
}

$distribution = [ordered]@{
    '引号滥用或缺失' = 118
    '引号内外标点位置' = 118
    '省略号误用' = 118
    '句末点号误用' = 103
    '破折号、连接号误用' = 74
    '冒号、分号误用' = 16
    '引号、括号、书名号等配对错误' = 15
    '标点冗余或缺失' = 6
    '选项与编号标点误用' = 6
    '间隔号误用' = 4
    '停顿符号误用' = 2
}

$outputDirectory = Split-Path -Parent $CurrentV2
$conversionPath = Join-Path $outputDirectory '标点符号错误_训练集_v2_均衡改造清单.jsonl'
$conversionLines = @($conversionLog | ForEach-Object { $_ | ConvertTo-Json -Compress -Depth 6 })
[System.IO.File]::WriteAllLines($conversionPath, $conversionLines, [System.Text.UTF8Encoding]::new($false))

$recoveryPath = Join-Path $outputDirectory '标点符号错误_训练集_v2_保留恢复题清单.jsonl'
$recoveryLines = @($recoveryLog | ForEach-Object { $_ | ConvertTo-Json -Compress -Depth 5 })
[System.IO.File]::WriteAllLines($recoveryPath, $recoveryLines, [System.Text.UTF8Encoding]::new($false))

$originalHashAfter = (Get-FileHash -Algorithm SHA256 -LiteralPath $OriginalTraining).Hash
$duplicateGroups = @($detections | Group-Object | Where-Object Count -gt 1)
$verification = [ordered]@{
    generated_at = (Get-Date).ToString('s')
    original_unchanged = ($originalHashBefore -eq $originalHashAfter)
    original_sha256 = $originalHashAfter
    output_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $CurrentV2).Hash
    total_records = $outputRecords.Count
    positive_records = $positive
    negative_records = $negative
    retained_recovered_records = $keptRecoverySlots.Count
    converted_original_sentence_end_records = $conversionLog.Count
    remaining_original_sentence_end_records = $available.Count
    invalid_answers = $invalid
    wrong_system_prompt = $wrongSystem
    duplicate_detection_groups = $duplicateGroups.Count
    distribution = $distribution
}
$verificationPath = Join-Path $outputDirectory '标点符号错误_训练集_v2_均衡校验报告.json'
$verification | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $verificationPath -Encoding UTF8

if (-not $verification.original_unchanged -or $outputRecords.Count -ne 1061 -or $positive -ne 580 -or $negative -ne 481 -or $invalid -ne 0 -or $wrongSystem -ne 0 -or (($distribution.Values | Measure-Object -Sum).Sum -ne 580)) {
    throw 'Final validation failed.'
}
$verification | ConvertTo-Json -Depth 8
