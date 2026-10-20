param(
    [string]$WorkspaceRoot = (Split-Path -Parent $PSScriptRoot),
    [int]$PositiveTarget = 330,
    [int]$NegativeTarget = 270,
    [int]$Seed = 20260824
)

$ErrorActionPreference = 'Stop'

$baseTrainPath = Join-Path $WorkspaceRoot '训练集-微调版提示词\train_v1\train_v3.jsonl'
$heldoutPaths = @(
    (Join-Path $WorkspaceRoot '训练集-微调版提示词\train_v1\val_v3.jsonl'),
    (Join-Path $WorkspaceRoot '训练集-微调版提示词\train_v1\test_v3.jsonl')
)
$newPositivePath = Join-Path $WorkspaceRoot '训练集-微调版提示词\v2_新增错别字正样本_162\train_v2_new_typo_positive_162.jsonl'
$newNegativePath = Join-Path $WorkspaceRoot '训练集-微调版提示词\v2_新增错别字负样本_198\train_v2_new_typo_negative_198.jsonl'
$promptPath = Join-Path $WorkspaceRoot '提示词-微调版\错别字_v4.txt'
$outputDir = Join-Path $WorkspaceRoot '训练集-微调版提示词\train_v1_restart'
$outputPath = Join-Path $outputDir '错别字_训练集_600.jsonl'
$manifestPath = Join-Path $outputDir '错别字_训练集_600_manifest.jsonl'
$reportPath = Join-Path $outputDir '错别字_训练集_600_构建报告.md'

New-Item -ItemType Directory -Path $outputDir -Force | Out-Null

$newTaskCard = [System.IO.File]::ReadAllText($promptPath, [System.Text.Encoding]::UTF8).TrimEnd()
$taskCardPattern = '(?ms)^# 任务：错别字\s*$.*?(?=^# 统一输出约束\s*$)'
$tracePattern = '错误样本|原题|改造|构造|故意|刻意|注入|生成要求|为了满足'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Get-Sha256([string]$Text) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return -join ($sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Text)) | ForEach-Object { $_.ToString('x2') })
    }
    finally {
        $sha.Dispose()
    }
}

function Get-NormalizedContent([string]$Text) {
    return (($Text.Normalize([System.Text.NormalizationForm]::FormKC) -replace '\s+', ' ').Trim())
}

function Test-V4Positive($Answer) {
    if (-not $Answer.has_error -or $Answer.errors.Count -eq 0) { return $false }
    foreach ($errorItem in $Answer.errors) {
        $original = [string]$errorItem.original_text
        $correction = [string]$errorItem.correction
        if ($original -notmatch '^[\u3400-\u9fff]+$' -or $correction -notmatch '^[\u3400-\u9fff]+$') { return $false }
        if ($original.Length -ne $correction.Length) { return $false }
        $differenceCount = 0
        for ($index = 0; $index -lt $original.Length; $index++) {
            if ($original[$index] -ne $correction[$index]) { $differenceCount++ }
        }
        if ($differenceCount -ne 1) { return $false }
    }
    return $true
}

function Read-TypoRows([string]$Path, [string]$Origin) {
    $result = @()
    $lineNumber = 0
    foreach ($line in [System.IO.File]::ReadLines($Path, [System.Text.Encoding]::UTF8)) {
        $lineNumber++
        $record = $line | ConvertFrom-Json
        $systemMessage = $record.messages | Where-Object { $_.role -eq 'system' } | Select-Object -First 1
        if ($systemMessage.content -notmatch '(?m)^# 任务：错别字\s*$') { continue }
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
            answer = $answer
            has_error = [bool]$answer.has_error
            v4_positive = Test-V4Positive $answer
            has_generation_trace = ($assistantMessage.content -match $tracePattern)
            normalized_content = $normalizedContent
            content_hash = Get-Sha256 $normalizedContent
            rank = Get-Sha256 "$Seed|$Origin|$lineNumber|$normalizedContent"
        }
    }
    return $result
}

$baseRows = @(Read-TypoRows $baseTrainPath 'train_v1保留')
$heldoutHashes = @{}
foreach ($heldoutPath in $heldoutPaths) {
    foreach ($row in @(Read-TypoRows $heldoutPath '锁定评测集')) {
        $heldoutHashes[$row.content_hash] = $true
    }
}

$allOriginalSplitHashes = @{}
foreach ($row in $baseRows) { $allOriginalSplitHashes[$row.content_hash] = $true }
foreach ($key in $heldoutHashes.Keys) { $allOriginalSplitHashes[$key] = $true }

$selected = @($baseRows | Where-Object {
    (-not $_.has_error) -or ($_.has_error -and $_.v4_positive -and -not $_.has_generation_trace)
})

$basePositive = @($selected | Where-Object { $_.has_error }).Count
$baseNegative = @($selected | Where-Object { -not $_.has_error }).Count
if ($basePositive -gt $PositiveTarget -or $baseNegative -gt $NegativeTarget) {
    throw "保留样本已超过目标配额：正/负=$basePositive/$baseNegative"
}

$usedHashes = @{}
foreach ($row in $selected) {
    if ($usedHashes.ContainsKey($row.content_hash)) { throw "现有保留样本出现重复题目：$($row.source_line)" }
    $usedHashes[$row.content_hash] = $true
}

$positiveNeeded = $PositiveTarget - $basePositive
$negativeNeeded = $NegativeTarget - $baseNegative
$newPositiveCandidates = @(Read-TypoRows $newPositivePath '新增正样本' | Where-Object {
    $_.has_error -and $_.v4_positive -and -not $_.has_generation_trace -and
    -not $allOriginalSplitHashes.ContainsKey($_.content_hash) -and -not $usedHashes.ContainsKey($_.content_hash)
} | Sort-Object rank)

foreach ($row in $newPositiveCandidates) {
    if ($positiveNeeded -le 0) { break }
    if (-not $usedHashes.ContainsKey($row.content_hash)) {
        $selected += $row
        $usedHashes[$row.content_hash] = $true
        $positiveNeeded--
    }
}

$newNegativeCandidates = @(Read-TypoRows $newNegativePath '新增困难负样本' | Where-Object {
    -not $_.has_error -and -not $_.has_generation_trace -and
    -not $allOriginalSplitHashes.ContainsKey($_.content_hash) -and -not $usedHashes.ContainsKey($_.content_hash)
} | Sort-Object rank)

foreach ($row in $newNegativeCandidates) {
    if ($negativeNeeded -le 0) { break }
    if (-not $usedHashes.ContainsKey($row.content_hash)) {
        $selected += $row
        $usedHashes[$row.content_hash] = $true
        $negativeNeeded--
    }
}

if ($positiveNeeded -ne 0 -or $negativeNeeded -ne 0) {
    throw "新增候选不足，尚缺正/负=$positiveNeeded/$negativeNeeded"
}

$selectedPositive = @($selected | Where-Object { $_.has_error }).Count
$selectedNegative = @($selected | Where-Object { -not $_.has_error }).Count
if ($selectedPositive -ne $PositiveTarget -or $selectedNegative -ne $NegativeTarget) {
    throw "最终配额错误：正/负=$selectedPositive/$selectedNegative"
}

$selected = @($selected | Sort-Object @{ Expression = { Get-Sha256 "$Seed|final|$($_.source_file)|$($_.source_line)" } })
$outputWriter = New-Object System.IO.StreamWriter($outputPath, $false, $utf8NoBom)
$manifestWriter = New-Object System.IO.StreamWriter($manifestPath, $false, $utf8NoBom)

try {
    $sampleIndex = 0
    foreach ($row in $selected) {
        $sampleIndex++
        $systemMessage = $row.record.messages | Where-Object { $_.role -eq 'system' } | Select-Object -First 1
        $matches = [regex]::Matches($systemMessage.content, $taskCardPattern)
        if ($matches.Count -ne 1) { throw "源样本未唯一匹配错别字任务卡：$($row.source_file):$($row.source_line)" }
        $systemMessage.content = [regex]::Replace(
            $systemMessage.content,
            $taskCardPattern,
            [System.Text.RegularExpressions.MatchEvaluator]{ param($match) "$newTaskCard`n`n" }
        )
        $outputWriter.WriteLine(($row.record | ConvertTo-Json -Depth 100 -Compress))
        $manifestWriter.WriteLine(([ordered]@{
            sample_id = ('RESTART-TYPO-{0:D4}' -f $sampleIndex)
            task_type = '错别字'
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

$keptPositive = @($selected | Where-Object { $_.has_error -and $_.origin -eq 'train_v1保留' }).Count
$keptNegative = @($selected | Where-Object { -not $_.has_error -and $_.origin -eq 'train_v1保留' }).Count
$addedPositive = $PositiveTarget - $keptPositive
$addedNegative = $NegativeTarget - $keptNegative
$removedPositive = @($baseRows | Where-Object { $_.has_error }).Count - $keptPositive

$report = @"
# 错别字训练集600条构建报告

## 最终配额

| 项目 | 数量 | 占比 |
|---|---:|---:|
| 总样本 | $($PositiveTarget + $NegativeTarget) | 100.00% |
| 正样本 | $PositiveTarget | $([math]::Round(100 * $PositiveTarget / ($PositiveTarget + $NegativeTarget), 2))% |
| 负样本 | $NegativeTarget | $([math]::Round(100 * $NegativeTarget / ($PositiveTarget + $NegativeTarget), 2))% |

## 调整构成

- 原 train_v1 错别字：390 正 / 181 负，共571条。
- 保留符合 v4 范围的原正样本：$keptPositive 条；移除旧范围正样本：$removedPositive 条。
- 保留原负样本：$keptNegative 条。
- 从 v2 新增专项数据补入：正样本 $addedPositive 条、困难负样本 $addedNegative 条。
- 最终所有样本统一使用 ``$promptPath``。
- 新增样本与原训练、验证、测试的规范化题目正文均不重复。
- 最终规范化题目正文 $($selected.Count) 条，唯一题目 $($usedHashes.Count) 道。
- 固定选择种子：``$Seed``。
"@
[System.IO.File]::WriteAllText($reportPath, $report, $utf8NoBom)

[ordered]@{
    output = $outputPath
    manifest = $manifestPath
    report = $reportPath
    total = $selected.Count
    positive = $selectedPositive
    negative = $selectedNegative
    kept_positive = $keptPositive
    removed_positive = $removedPositive
    added_positive = $addedPositive
    added_negative = $addedNegative
    unique_questions = $usedHashes.Count
} | ConvertTo-Json -Compress
