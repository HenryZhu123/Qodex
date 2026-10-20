param(
    [string]$WorkspaceRoot = (Split-Path -Parent $PSScriptRoot),
    [int]$Seed = 20260825
)

$ErrorActionPreference = 'Stop'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$tracePattern = '错误样本|原题|改造|构造|故意|刻意|注入|生成要求|为了满足'

$trainPath = Join-Path $WorkspaceRoot '训练集-微调版提示词\train_v1.1\train_v1.1.jsonl'
$oldValPath = Join-Path $WorkspaceRoot '训练集-微调版提示词\train_v1\val_v3.jsonl'
$oldTestPath = Join-Path $WorkspaceRoot '训练集-微调版提示词\train_v1\test_v3.jsonl'
$typoSourcePaths = @(
    $oldValPath,
    (Join-Path $WorkspaceRoot '训练集-微调版提示词\错别字_训练集.jsonl'),
    (Join-Path $WorkspaceRoot '训练集-微调版提示词\v2_新增错别字正样本_162\train_v2_new_typo_positive_162.jsonl'),
    (Join-Path $WorkspaceRoot '训练集-微调版提示词\v2_新增错别字负样本_198\train_v2_new_typo_negative_198.jsonl')
)
$optionSourcePaths = @(
    $oldValPath,
    (Join-Path $WorkspaceRoot '训练集-微调版提示词\选项结构错误_训练集.jsonl')
)

$promptPaths = @{
    '错别字' = Join-Path $WorkspaceRoot '提示词-微调版\错别字_v4.txt'
    '选项结构错误' = Join-Path $WorkspaceRoot '提示词-微调版\选项结构错误.txt'
    '题目与题型不一致' = Join-Path $WorkspaceRoot '提示词-微调版\题目与题型不一致_v2.txt'
}
$taskPatterns = @{
    '错别字' = '(?ms)^# 任务：错别字\s*$.*?(?=^# 统一输出约束\s*$)'
    '选项结构错误' = '(?ms)^# 任务：选项结构错误\s*$.*?(?=^# 统一输出约束\s*$)'
    '题目与题型不一致' = '(?ms)^# 任务：题目与题型不一致\s*$.*?(?=^# 统一输出约束\s*$)'
}
$outputDir = Join-Path $WorkspaceRoot '验证集'
$outputPath = Join-Path $outputDir 'val_1.1.jsonl'
$manifestPath = Join-Path $outputDir 'val_1.1_manifest.jsonl'
$reportPath = Join-Path $outputDir 'VAL_1.1_REPORT.md'

function Get-Sha256([string]$Text) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return -join ($sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Text)) | ForEach-Object { $_.ToString('x2') })
    }
    finally { $sha.Dispose() }
}

function Get-NormalizedContent([string]$Text) {
    return (($Text.Normalize([System.Text.NormalizationForm]::FormKC) -replace '\s+', ' ').Trim())
}

function Get-TaskType($Record) {
    $system = $Record.messages | Where-Object { $_.role -eq 'system' } | Select-Object -First 1
    if ($system.content -match '(?m)^# 任务：错别字\s*$') { return '错别字' }
    if ($system.content -match '(?m)^# 任务：选项结构错误\s*$') { return '选项结构错误' }
    if ($system.content -match '(?m)^# 任务：题目与题型不一致\s*$') { return '题目与题型不一致' }
    return $null
}

function Read-Rows([string]$Path, [string]$ExpectedTask, [string]$Origin) {
    $rows = New-Object System.Collections.Generic.List[object]
    $lineNumber = 0
    foreach ($line in [System.IO.File]::ReadLines($Path, [System.Text.Encoding]::UTF8)) {
        $lineNumber++
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $record = $line | ConvertFrom-Json
        $task = Get-TaskType $record
        if ($ExpectedTask -and $task -ne $ExpectedTask) { continue }
        if (-not $task) { continue }
        $user = $record.messages | Where-Object { $_.role -eq 'user' } | Select-Object -First 1
        $assistant = $record.messages | Where-Object { $_.role -eq 'assistant' } | Select-Object -Last 1
        if ($null -eq $user -or $null -eq $assistant) { throw "消息结构不完整：${Path}:$lineNumber" }
        $payload = (($user.content -replace '^\[INPUT_PAYLOAD\]\s*', '') | ConvertFrom-Json)
        $answer = $assistant.content | ConvertFrom-Json
        $normalized = Get-NormalizedContent ([string]$payload.detection_content)
        if ([string]::IsNullOrWhiteSpace($normalized)) { throw "题目正文为空：${Path}:$lineNumber" }
        $rows.Add([pscustomobject]@{
            task_type = $task
            record = $record
            has_error = [bool]$answer.has_error
            has_generation_trace = ($assistant.content -match $tracePattern)
            answer = $answer
            source_file = $Path
            source_line = $lineNumber
            origin = $Origin
            normalized_content = $normalized
            detection_content = [string]$payload.detection_content
            reference = [string]$payload.reference
            content_hash = Get-Sha256 $normalized
            rank = Get-Sha256 "$Seed|$task|$Origin|$lineNumber|$normalized"
        })
    }
    return @($rows | ForEach-Object { $_ })
}

function Test-TypoV4Positive($Row) {
    if (-not $Row.has_error -or $Row.answer.errors.Count -eq 0) { return $false }
    foreach ($errorItem in $Row.answer.errors) {
        $original = [string]$errorItem.original_text
        $correction = [string]$errorItem.correction
        if ($original -notmatch '^[\u3400-\u9fff]+$' -or $correction -notmatch '^[\u3400-\u9fff]+$') { return $false }
        if ($original.Length -ne $correction.Length) { return $false }
        $differences = 0
        for ($index = 0; $index -lt $original.Length; $index++) {
            if ($original[$index] -ne $correction[$index]) { $differences++ }
        }
        if ($differences -ne 1) { return $false }
    }
    return $true
}

function Set-CurrentPrompt($Row) {
    $task = $Row.task_type
    $newTaskCard = [System.IO.File]::ReadAllText($promptPaths[$task], [System.Text.Encoding]::UTF8).TrimEnd()
    $system = $Row.record.messages | Where-Object { $_.role -eq 'system' } | Select-Object -First 1
    $pattern = $taskPatterns[$task]
    if ([regex]::Matches($system.content, $pattern).Count -ne 1) {
        throw "未唯一匹配任务卡：$($Row.source_file):$($Row.source_line)"
    }
    $system.content = [regex]::Replace(
        $system.content,
        $pattern,
        [System.Text.RegularExpressions.MatchEvaluator]{ param($match) "$newTaskCard`n`n" }
    )
    if ($task -eq '选项结构错误') {
        $assistant = $Row.record.messages | Where-Object { $_.role -eq 'assistant' } | Select-Object -Last 1
        $answer = $assistant.content | ConvertFrom-Json
        foreach ($errorItem in @($answer.errors)) {
            $errorItem.error_type = '选项错误'
        }
        $assistant.content = $answer | ConvertTo-Json -Depth 20 -Compress
    }
}

function New-MismatchPairRow($BaseRow, [bool]$HasError) {
    $record = (($BaseRow.record | ConvertTo-Json -Depth 100 -Compress) | ConvertFrom-Json)
    $system = $record.messages | Where-Object { $_.role -eq 'system' } | Select-Object -First 1
    $optionPattern = $taskPatterns['选项结构错误']
    $mismatchTaskCard = [System.IO.File]::ReadAllText($promptPaths['题目与题型不一致'], [System.Text.Encoding]::UTF8).TrimEnd()
    if ([regex]::Matches($system.content, $optionPattern).Count -ne 1) {
        throw "构造题型验证对照时未唯一匹配选项任务卡：$($BaseRow.source_file):$($BaseRow.source_line)"
    }
    $system.content = [regex]::Replace(
        $system.content,
        $optionPattern,
        [System.Text.RegularExpressions.MatchEvaluator]{ param($match) "$mismatchTaskCard`n`n" }
    )

    $user = $record.messages | Where-Object { $_.role -eq 'user' } | Select-Object -First 1
    $assistant = $record.messages | Where-Object { $_.role -eq 'assistant' } | Select-Object -Last 1
    $payload = (($user.content -replace '^\[INPUT_PAYLOAD\]\s*', '') | ConvertFrom-Json)
    if ($HasError) {
        $payload.reference = [regex]::Replace(
            [string]$payload.reference,
            '(?m)(【题型或其它信息】)[^\r\n]*',
            [System.Text.RegularExpressions.MatchEvaluator]{ param($match) ($match.Groups[1].Value + '填空题') }
        )
        $rawDetection = ([string]$payload.detection_content).Trim()
        $originalLength = [math]::Min(20, $rawDetection.Length)
        $anchorLength = [math]::Min(60, $rawDetection.Length)
        $answer = [ordered]@{
            reason = '选择题>填空题'
            has_error = $true
            total_errors = 1
            errors = @([ordered]@{
                error_type = '题目与题型不一致'
                position = '题目整体的作答形式'
                original_text = $rawDetection.Substring(0, $originalLength)
                anchor_text = $rawDetection.Substring(0, $anchorLength)
                correction = '将题目改写为符合填空题要求的作答形式'
                description = '题目含明确备选项，实际呈现为选择题，与填空题标注不一致。'
                suggestion = '改写题目作答形式，或将题型标注修改为选择题。'
            })
        }
    }
    else {
        $answer = [ordered]@{
            reason = '题目含明确备选项，与选择题标注一致。'
            has_error = $false
            total_errors = 0
            errors = @()
        }
    }
    $user.content = '[INPUT_PAYLOAD]' + "`n" + ($payload | ConvertTo-Json -Depth 20 -Compress)
    $assistant.content = $answer | ConvertTo-Json -Depth 20 -Compress

    return [pscustomobject]@{
        task_type = '题目与题型不一致'
        record = $record
        has_error = $HasError
        has_generation_trace = $false
        source_file = $BaseRow.source_file
        source_line = $BaseRow.source_line
        origin = '未使用正常选择题构造题型标注对照'
        normalized_content = $BaseRow.normalized_content
        detection_content = $BaseRow.detection_content
        reference = [string]$payload.reference
        content_hash = $BaseRow.content_hash
        rank = Get-Sha256 "$Seed|mismatch-pair|$HasError|$($BaseRow.source_file)|$($BaseRow.source_line)"
    }
}

function Select-UniqueRows($Candidates, [int]$PositiveTarget, [int]$NegativeTarget, [hashtable]$UsedHashes) {
    $result = New-Object System.Collections.Generic.List[object]
    foreach ($label in @($true, $false)) {
        $target = if ($label) { $PositiveTarget } else { $NegativeTarget }
        $count = 0
        foreach ($row in @($Candidates | Where-Object { $_.has_error -eq $label } | Sort-Object rank)) {
            if ($count -ge $target) { break }
            if (-not $UsedHashes.ContainsKey($row.content_hash)) {
                $result.Add($row)
                $UsedHashes[$row.content_hash] = $true
                $count++
            }
        }
        if ($count -ne $target) { throw "候选不足：标签=$label，目标=$target，实际=$count" }
    }
    return @($result | ForEach-Object { $_ })
}

# 用全部训练题面做全局隔离；旧 test_v3 也保留为独立测试集，不作为验证集候选。
$trainHashes = @{}
foreach ($row in @(Read-Rows $trainPath $null 'train_v1.1')) { $trainHashes[$row.content_hash] = $true }
$testHashes = @{}
foreach ($row in @(Read-Rows $oldTestPath $null '旧测试集')) { $testHashes[$row.content_hash] = $true }
$usedValidationHashes = @{}

$typoCandidates = New-Object System.Collections.Generic.List[object]
foreach ($path in $typoSourcePaths) {
    foreach ($row in @(Read-Rows $path '错别字' ('错别字候选：' + [System.IO.Path]::GetFileName($path)))) {
        if ($trainHashes.ContainsKey($row.content_hash) -or $testHashes.ContainsKey($row.content_hash)) { continue }
        if ($row.has_generation_trace) { continue }
        if ($row.has_error -and -not (Test-TypoV4Positive $row)) { continue }
        $typoCandidates.Add($row)
    }
}
$typoSelected = @(Select-UniqueRows @($typoCandidates | ForEach-Object { $_ }) 60 60 $usedValidationHashes)

$optionCandidates = New-Object System.Collections.Generic.List[object]
foreach ($path in $optionSourcePaths) {
    foreach ($row in @(Read-Rows $path '选项结构错误' ('选项候选：' + [System.IO.Path]::GetFileName($path)))) {
        if ($trainHashes.ContainsKey($row.content_hash) -or $testHashes.ContainsKey($row.content_hash)) { continue }
        if ($row.has_generation_trace) { continue }
        $optionCandidates.Add($row)
    }
}
$optionSelected = @(Select-UniqueRows @($optionCandidates | ForEach-Object { $_ }) 45 45 $usedValidationHashes)

# 题型不一致验证集从未使用的正常选择题构造正负题型标注对照。
# 正负版本只改变 reference 中的题型标注，detection_content 保持完全一致，并作为一组留在验证集。
$pairBaseCandidates = @($optionCandidates | Where-Object {
    (-not $_.has_error) -and
    (-not $_.has_generation_trace) -and
    $_.reference -match '(?m)【题型或其它信息】选择题\s*$' -and
    (-not $trainHashes.ContainsKey($_.content_hash)) -and
    (-not $testHashes.ContainsKey($_.content_hash)) -and
    (-not $usedValidationHashes.ContainsKey($_.content_hash))
} | Sort-Object rank)
$uniquePairBases = New-Object System.Collections.Generic.List[object]
$pairBaseHashes = @{}
foreach ($row in $pairBaseCandidates) {
    if ($uniquePairBases.Count -ge 45) { break }
    if (-not $pairBaseHashes.ContainsKey($row.content_hash)) {
        $uniquePairBases.Add($row)
        $pairBaseHashes[$row.content_hash] = $true
    }
}
if ($uniquePairBases.Count -ne 45) { throw "可用于题型对照的未使用正常选择题不足45道：实际=$($uniquePairBases.Count)" }
$mismatchSelected = New-Object System.Collections.Generic.List[object]
foreach ($baseRow in @($uniquePairBases | ForEach-Object { $_ })) {
    $mismatchSelected.Add((New-MismatchPairRow $baseRow $true))
    $mismatchSelected.Add((New-MismatchPairRow $baseRow $false))
    $usedValidationHashes[$baseRow.content_hash] = $true
}

$allSelected = @($typoSelected + $optionSelected + @($mismatchSelected | ForEach-Object { $_ }))
if ($allSelected.Count -ne 300) { throw "总量异常：$($allSelected.Count)" }
$allSelected = @($allSelected | Sort-Object @{ Expression = { Get-Sha256 "$Seed|final|$($_.task_type)|$($_.source_file)|$($_.source_line)" } })

New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
$outputWriter = New-Object System.IO.StreamWriter($outputPath, $false, $utf8NoBom)
$manifestWriter = New-Object System.IO.StreamWriter($manifestPath, $false, $utf8NoBom)
try {
    $sampleIndex = 0
    foreach ($row in $allSelected) {
        $sampleIndex++
        Set-CurrentPrompt $row
        $sampleId = 'VAL-V1.1-{0:D4}' -f $sampleIndex
        $outputWriter.WriteLine(($row.record | ConvertTo-Json -Depth 100 -Compress))
        $manifestWriter.WriteLine(([ordered]@{
            sample_id = $sampleId
            task_type = $row.task_type
            has_error = $row.has_error
            source_file = $row.source_file
            source_line = $row.source_line
            origin = $row.origin
            normalized_content_sha256 = $row.content_hash
            selection_seed = $Seed
            prompt_file = $promptPaths[$row.task_type]
        } | ConvertTo-Json -Compress))
    }
}
finally {
    $outputWriter.Dispose()
    $manifestWriter.Dispose()
}

$stats = @{}
foreach ($task in @('错别字', '选项结构错误', '题目与题型不一致')) {
    $taskRows = @($allSelected | Where-Object { $_.task_type -eq $task })
    $stats[$task] = [ordered]@{
        total = $taskRows.Count
        positive = @($taskRows | Where-Object { $_.has_error }).Count
        negative = @($taskRows | Where-Object { -not $_.has_error }).Count
    }
}
$uniqueQuestionCount = @($allSelected | Select-Object -ExpandProperty content_hash -Unique).Count
$report = @"
# val_1.1 构建报告

| 错误类型 | 总数 | 占比 | 正样本 | 负样本 |
|---|---:|---:|---:|---:|
| 错别字 | 120 | 40.00% | 60 | 60 |
| 选项结构错误 | 90 | 30.00% | 45 | 45 |
| 题目与题型不一致 | 90 | 30.00% | 45 | 45 |
| 合计 | 300 | 100.00% | 150 | 150 |

## 隔离与质量约束

- 与 ``train_v1.1.jsonl`` 的规范化题目正文重合：0。
- 与旧 ``test_v3.jsonl`` 的规范化题目正文重合：0，旧测试集保持独立。
- 验证集共 300 条、$uniqueQuestionCount 个规范化题面。
- 错别字正样本全部符合 v4 边界：仅汉字等长替换，且每个错误为单字替换；不含多字、漏字等旧范围问题。
- 错别字与选项结构错误题面在验证集内各自唯一。
- 题目与题型不一致使用 45 道未用于训练、旧测试及其他验证类型的正常选择题构造完整正负对照：负样本保留“选择题”标注，正样本只将题型标注替换为“填空题”，题目正文不变。
- 每道题的正负两个版本均留在 ``val_1.1``，整组不进入训练集。
- 三类样本分别使用当前提示词：错别字 v4、选项结构错误当前版、题目与题型不一致 v2。
- 固定选择种子：``$Seed``。
"@
[System.IO.File]::WriteAllText($reportPath, $report, $utf8NoBom)

[ordered]@{
    output = $outputPath
    manifest = $manifestPath
    report = $reportPath
    total = $allSelected.Count
    positive = @($allSelected | Where-Object { $_.has_error }).Count
    negative = @($allSelected | Where-Object { -not $_.has_error }).Count
    unique_questions = $uniqueQuestionCount
    task_stats = $stats
    mismatch_pair_groups = 45
} | ConvertTo-Json -Depth 10 -Compress
