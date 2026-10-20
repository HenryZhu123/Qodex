param(
    [string]$WorkspaceRoot = (Split-Path -Parent $PSScriptRoot),
    [int]$PositiveTarget = 188,
    [int]$NegativeTarget = 262,
    [int]$Seed = 20260824
)

$ErrorActionPreference = 'Stop'
$baseTrainPath = Join-Path $WorkspaceRoot '训练集-微调版提示词\train_v1\train_v3.jsonl'
$heldoutPaths = @(
    (Join-Path $WorkspaceRoot '训练集-微调版提示词\train_v1\val_v3.jsonl'),
    (Join-Path $WorkspaceRoot '训练集-微调版提示词\train_v1\test_v3.jsonl')
)
$sourcePath = Join-Path $WorkspaceRoot '训练集-微调版提示词\选项结构错误_训练集.jsonl'
$promptPath = Join-Path $WorkspaceRoot '提示词-微调版\选项结构错误.txt'
$outputDir = Join-Path $WorkspaceRoot '训练集-微调版提示词\train_v1_restart'
$outputPath = Join-Path $outputDir '选项结构错误_训练集_450.jsonl'
$manifestPath = Join-Path $outputDir '选项结构错误_训练集_450_manifest.jsonl'
$reportPath = Join-Path $outputDir '选项结构错误_训练集_450_构建报告.md'

New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
$newTaskCard = [IO.File]::ReadAllText($promptPath, [Text.Encoding]::UTF8).TrimEnd()
$taskCardPattern = '(?ms)^# 任务：选项结构错误\s*$.*?(?=^# 统一输出约束\s*$)'
$tracePattern = '错误样本|原题|改造|构造|故意|刻意|注入|生成要求|为了满足'
$utf8NoBom = New-Object Text.UTF8Encoding($false)

function Get-Sha256([string]$Text) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return -join ($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)) | ForEach-Object { $_.ToString('x2') }) }
    finally { $sha.Dispose() }
}

function Get-NormalizedContent([string]$Text) {
    return (($Text.Normalize([Text.NormalizationForm]::FormKC) -replace '\s+', ' ').Trim())
}

function Read-OptionRows([string]$Path, [string]$Origin) {
    $result = @()
    $lineNumber = 0
    foreach ($line in [IO.File]::ReadLines($Path, [Text.Encoding]::UTF8)) {
        $lineNumber++
        $record = $line | ConvertFrom-Json
        $systemMessage = $record.messages | Where-Object { $_.role -eq 'system' } | Select-Object -First 1
        if ($systemMessage.content -notmatch '(?m)^# 任务：选项结构错误\s*$') { continue }
        $userMessage = $record.messages | Where-Object { $_.role -eq 'user' } | Select-Object -First 1
        $assistantMessage = $record.messages | Where-Object { $_.role -eq 'assistant' } | Select-Object -Last 1
        $payload = (($userMessage.content -replace '^\[INPUT_PAYLOAD\]\s*', '') | ConvertFrom-Json)
        $answer = $assistantMessage.content | ConvertFrom-Json
        $normalizedContent = Get-NormalizedContent ([string]$payload.detection_content)
        $result += [pscustomobject]@{
            source_file = $Path
            source_line = $lineNumber
            origin = $Origin
            record = $record
            has_error = [bool]$answer.has_error
            has_generation_trace = ($assistantMessage.content -match $tracePattern)
            content_hash = Get-Sha256 $normalizedContent
            rank = Get-Sha256 "$Seed|$Origin|$lineNumber|$normalizedContent"
        }
    }
    return $result
}

$baseRows = @(Read-OptionRows $baseTrainPath 'train_v1保留')
$basePositive = @($baseRows | Where-Object { $_.has_error }).Count
$baseNegative = @($baseRows | Where-Object { -not $_.has_error }).Count
if ($basePositive -ne 125 -or $baseNegative -ne 175) {
    throw "现有选项结构错误配额异常：正/负=$basePositive/$baseNegative"
}

$excludedHashes = @{}
foreach ($row in $baseRows) { $excludedHashes[$row.content_hash] = $true }
foreach ($heldoutPath in $heldoutPaths) {
    foreach ($row in @(Read-OptionRows $heldoutPath '锁定评测集')) { $excludedHashes[$row.content_hash] = $true }
}

$selected = @($baseRows)
$usedHashes = @{}
foreach ($row in $selected) {
    if ($usedHashes.ContainsKey($row.content_hash)) { throw "原训练集存在完全重复选项题：$($row.source_line)" }
    $usedHashes[$row.content_hash] = $true
}

$positiveNeeded = $PositiveTarget - $basePositive
$negativeNeeded = $NegativeTarget - $baseNegative
$candidates = @(Read-OptionRows $sourcePath '原专项数据新增' | Where-Object {
    -not $_.has_generation_trace -and -not $excludedHashes.ContainsKey($_.content_hash)
} | Sort-Object rank)

foreach ($row in @($candidates | Where-Object { $_.has_error })) {
    if ($positiveNeeded -le 0) { break }
    if (-not $usedHashes.ContainsKey($row.content_hash)) {
        $selected += $row
        $usedHashes[$row.content_hash] = $true
        $positiveNeeded--
    }
}

foreach ($row in @($candidates | Where-Object { -not $_.has_error })) {
    if ($negativeNeeded -le 0) { break }
    if (-not $usedHashes.ContainsKey($row.content_hash)) {
        $selected += $row
        $usedHashes[$row.content_hash] = $true
        $negativeNeeded--
    }
}

if ($positiveNeeded -ne 0 -or $negativeNeeded -ne 0) { throw "新增候选不足：尚缺正/负=$positiveNeeded/$negativeNeeded" }
$selectedPositive = @($selected | Where-Object { $_.has_error }).Count
$selectedNegative = @($selected | Where-Object { -not $_.has_error }).Count
$selected = @($selected | Sort-Object @{ Expression = { Get-Sha256 "$Seed|final|$($_.source_file)|$($_.source_line)" } })

$outputWriter = New-Object IO.StreamWriter($outputPath, $false, $utf8NoBom)
$manifestWriter = New-Object IO.StreamWriter($manifestPath, $false, $utf8NoBom)
try {
    $sampleIndex = 0
    foreach ($row in $selected) {
        $sampleIndex++
        $systemMessage = $row.record.messages | Where-Object { $_.role -eq 'system' } | Select-Object -First 1
        if ([regex]::Matches($systemMessage.content, $taskCardPattern).Count -ne 1) {
            throw "源样本未唯一匹配选项任务卡：$($row.source_file):$($row.source_line)"
        }
        $systemMessage.content = [regex]::Replace(
            $systemMessage.content,
            $taskCardPattern,
            [Text.RegularExpressions.MatchEvaluator]{ param($match) "$newTaskCard`n`n" }
        )
        $outputWriter.WriteLine(($row.record | ConvertTo-Json -Depth 100 -Compress))
        $manifestWriter.WriteLine(([ordered]@{
            sample_id = ('RESTART-OPTION-{0:D4}' -f $sampleIndex)
            task_type = '选项结构错误'
            has_error = $row.has_error
            origin = $row.origin
            source_file = $row.source_file
            source_line = $row.source_line
            normalized_content_sha256 = $row.content_hash
            selection_seed = $Seed
            prompt_file = $promptPath
        } | ConvertTo-Json -Compress))
    }
}
finally {
    $outputWriter.Dispose()
    $manifestWriter.Dispose()
}

$addedPositive = $PositiveTarget - $basePositive
$addedNegative = $NegativeTarget - $baseNegative
$report = @"
# 选项结构错误训练集450条构建报告

| 项目 | 数量 | 占比 |
|---|---:|---:|
| 总样本 | 450 | 100.00% |
| 正样本 | $PositiveTarget | $([math]::Round(100 * $PositiveTarget / 450, 2))% |
| 负样本 | $NegativeTarget | $([math]::Round(100 * $NegativeTarget / 450, 2))% |

- 保留原 train_v1：125 正 / 175 负，共300条。
- 新增：$addedPositive 正 / $addedNegative 负，共150条。
- 新增样本与原训练、验证、测试的规范化题目正文不重复。
- 最终450条题目正文严格唯一。
- 专项提示词：``$promptPath``。
- 固定选择种子：``$Seed``。
"@
[IO.File]::WriteAllText($reportPath, $report, $utf8NoBom)

[ordered]@{
    output = $outputPath
    manifest = $manifestPath
    report = $reportPath
    total = $selected.Count
    positive = $selectedPositive
    negative = $selectedNegative
    added_positive = $addedPositive
    added_negative = $addedNegative
    unique_questions = $usedHashes.Count
} | ConvertTo-Json -Compress
