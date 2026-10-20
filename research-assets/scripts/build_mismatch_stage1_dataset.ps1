param(
    [string]$WorkspaceRoot = (Split-Path -Parent $PSScriptRoot),
    [int]$PositiveTarget = 203,
    [int]$NegativeTarget = 247,
    [int]$Seed = 20260824
)

$ErrorActionPreference = 'Stop'

$sourcePath = Join-Path $WorkspaceRoot '训练集-微调版提示词\题目与题型不一致_训练集.jsonl'
$promptPath = Join-Path $WorkspaceRoot '提示词-微调版\题目与题型不一致_v2.txt'
$outputDir = Join-Path $WorkspaceRoot '训练集-微调版提示词\train_v1_restart'
$outputPath = Join-Path $outputDir '题目与题型不一致_训练集_450.jsonl'
$manifestPath = Join-Path $outputDir '题目与题型不一致_训练集_450_manifest.jsonl'
$reportPath = Join-Path $outputDir '题目与题型不一致_训练集_450_构建报告.md'

New-Item -ItemType Directory -Path $outputDir -Force | Out-Null

$newTaskCard = [System.IO.File]::ReadAllText($promptPath, [System.Text.Encoding]::UTF8).TrimEnd()
$taskCardPattern = '(?ms)^# 任务：题目与题型不一致\s*$.*?(?=^# 统一输出约束\s*$)'
$tracePattern = '错误样本|原题|改造|构造|故意|刻意|注入|生成要求'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Get-Sha256([string]$Text) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
        return -join ($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString('x2') })
    }
    finally {
        $sha.Dispose()
    }
}

function Get-NormalizedContent([string]$Text) {
    return (($Text.Normalize([System.Text.NormalizationForm]::FormKC) -replace '\s+', ' ').Trim())
}

$rows = New-Object System.Collections.Generic.List[object]
$lineNumber = 0

foreach ($line in [System.IO.File]::ReadLines($sourcePath, [System.Text.Encoding]::UTF8)) {
    $lineNumber++
    $record = $line | ConvertFrom-Json
    $systemMessage = $record.messages | Where-Object { $_.role -eq 'system' } | Select-Object -First 1
    $userMessage = $record.messages | Where-Object { $_.role -eq 'user' } | Select-Object -First 1
    $assistantMessage = $record.messages | Where-Object { $_.role -eq 'assistant' } | Select-Object -Last 1

    if ($null -eq $systemMessage -or $null -eq $userMessage -or $null -eq $assistantMessage) {
        throw "源文件第 $lineNumber 行消息结构不完整"
    }

    $payloadText = $userMessage.content -replace '^\[INPUT_PAYLOAD\]\s*', ''
    $payload = $payloadText | ConvertFrom-Json
    $answer = $assistantMessage.content | ConvertFrom-Json
    $normalizedContent = Get-NormalizedContent ([string]$payload.detection_content)

    if ([string]::IsNullOrWhiteSpace($normalizedContent)) {
        throw "源文件第 $lineNumber 行题目正文为空"
    }

    $rows.Add([pscustomobject]@{
        source_line = $lineNumber
        record = $record
        has_error = [bool]$answer.has_error
        has_generation_trace = ($assistantMessage.content -match $tracePattern)
        normalized_content = $normalizedContent
        content_hash = Get-Sha256 $normalizedContent
        rank = Get-Sha256 "$Seed|row|$lineNumber|$normalizedContent"
    })
}

$groups = @{}
foreach ($row in $rows) {
    if (-not $groups.ContainsKey($row.content_hash)) {
        $groups[$row.content_hash] = New-Object System.Collections.Generic.List[object]
    }
    $groups[$row.content_hash].Add($row)
}

$positiveOnlyGroups = New-Object System.Collections.Generic.List[object]
$negativeOnlyGroups = New-Object System.Collections.Generic.List[object]
$crossLabelGroups = New-Object System.Collections.Generic.List[object]

foreach ($entry in $groups.GetEnumerator()) {
    $groupRows = @($entry.Value | ForEach-Object { $_ })
    $positiveCandidates = @($groupRows | Where-Object { $_.has_error -and -not $_.has_generation_trace } | Sort-Object rank)
    $negativeCandidates = @($groupRows | Where-Object { -not $_.has_error } | Sort-Object rank)
    $groupInfo = [pscustomobject]@{
        content_hash = $entry.Key
        group_rows = $groupRows
        positive_candidates = $positiveCandidates
        negative_candidates = $negativeCandidates
        rank = Get-Sha256 "$Seed|group|$($entry.Key)"
    }

    if ($positiveCandidates.Count -gt 0 -and $negativeCandidates.Count -gt 0) {
        $crossLabelGroups.Add($groupInfo)
    }
    elseif ($positiveCandidates.Count -gt 0) {
        $positiveOnlyGroups.Add($groupInfo)
    }
    elseif ($negativeCandidates.Count -gt 0) {
        $negativeOnlyGroups.Add($groupInfo)
    }
}

$selected = New-Object System.Collections.Generic.List[object]
$usedGroups = @{}

foreach ($group in @($positiveOnlyGroups | Sort-Object rank)) {
    if (@($selected | Where-Object { $_.has_error }).Count -ge $PositiveTarget) { break }
    $selected.Add($group.positive_candidates[0])
    $usedGroups[$group.content_hash] = $true
}

foreach ($group in @($crossLabelGroups | Sort-Object rank)) {
    if (@($selected | Where-Object { $_.has_error }).Count -ge $PositiveTarget) { break }
    if (-not $usedGroups.ContainsKey($group.content_hash)) {
        $selected.Add($group.positive_candidates[0])
        $usedGroups[$group.content_hash] = $true
    }
}

foreach ($group in @($negativeOnlyGroups | Sort-Object rank)) {
    if (@($selected | Where-Object { -not $_.has_error }).Count -ge $NegativeTarget) { break }
    $selected.Add($group.negative_candidates[0])
    $usedGroups[$group.content_hash] = $true
}

foreach ($group in @($crossLabelGroups | Sort-Object rank)) {
    if (@($selected | Where-Object { -not $_.has_error }).Count -ge $NegativeTarget) { break }
    if (-not $usedGroups.ContainsKey($group.content_hash)) {
        $selected.Add($group.negative_candidates[0])
        $usedGroups[$group.content_hash] = $true
    }
}

$selectedPositive = @($selected | Where-Object { $_.has_error }).Count
$selectedNegative = @($selected | Where-Object { -not $_.has_error }).Count
if ($selectedPositive -ne $PositiveTarget -or $selectedNegative -ne $NegativeTarget) {
    throw "无法满足配额：实际正/负=$selectedPositive/$selectedNegative，目标=$PositiveTarget/$NegativeTarget"
}

$selected = @($selected | Sort-Object @{ Expression = { Get-Sha256 "$Seed|final|$($_.source_line)|$($_.content_hash)" } })
$outputWriter = New-Object System.IO.StreamWriter($outputPath, $false, $utf8NoBom)
$manifestWriter = New-Object System.IO.StreamWriter($manifestPath, $false, $utf8NoBom)

try {
    $sampleIndex = 0
    foreach ($row in $selected) {
        $sampleIndex++
        $systemMessage = $row.record.messages | Where-Object { $_.role -eq 'system' } | Select-Object -First 1
        $matches = [regex]::Matches($systemMessage.content, $taskCardPattern)
        if ($matches.Count -ne 1) {
            throw "源文件第 $($row.source_line) 行未唯一匹配旧任务卡"
        }
        $systemMessage.content = [regex]::Replace(
            $systemMessage.content,
            $taskCardPattern,
            [System.Text.RegularExpressions.MatchEvaluator]{ param($match) "$newTaskCard`n`n" }
        )

        $groupRows = @($groups[$row.content_hash] | ForEach-Object { $_ })
        $groupLabels = @($groupRows | ForEach-Object { $_.has_error } | Select-Object -Unique)
        $sampleId = 'RESTART-MISMATCH-{0:D4}' -f $sampleIndex
        $outputWriter.WriteLine(($row.record | ConvertTo-Json -Depth 100 -Compress))
        $manifestWriter.WriteLine(([ordered]@{
            sample_id = $sampleId
            task_type = '题目与题型不一致'
            has_error = $row.has_error
            source_file = $sourcePath
            source_line = $row.source_line
            normalized_content_sha256 = $row.content_hash
            source_content_group_size = $groupRows.Count
            source_group_has_both_labels = ($groupLabels.Count -gt 1)
            selection_seed = $Seed
            prompt_file = $promptPath
        } | ConvertTo-Json -Compress))
    }
}
finally {
    $outputWriter.Dispose()
    $manifestWriter.Dispose()
}

$selectedCrossPositive = @($selected | Where-Object {
    $_.has_error -and (@($groups[$_.content_hash] | ForEach-Object { $_.has_error } | Select-Object -Unique).Count -gt 1)
}).Count
$selectedCrossNegative = @($selected | Where-Object {
    (-not $_.has_error) -and (@($groups[$_.content_hash] | ForEach-Object { $_.has_error } | Select-Object -Unique).Count -gt 1)
}).Count

$report = @"
# 题目与题型不一致训练集构建报告

## 配额

| 项目 | 数量 | 占比 |
|---|---:|---:|
| 总样本 | $($PositiveTarget + $NegativeTarget) | 100.00% |
| 正样本 | $PositiveTarget | $([math]::Round(100 * $PositiveTarget / ($PositiveTarget + $NegativeTarget), 2))% |
| 负样本 | $NegativeTarget | $([math]::Round(100 * $NegativeTarget / ($PositiveTarget + $NegativeTarget), 2))% |

## 构建约束

- 来源：``$sourcePath``。
- 专项提示词：``$promptPath``。
- 规范化题目正文严格唯一，共 $($selected.Count) 个题目、$($selected.Count) 条样本。
- 同一题目的正负版本不会同时入选。
- 正样本排除包含“错误样本、原题、改造、构造、故意、刻意、注入、生成要求”等生成过程痕迹的答案。
- 来源中属于正负对照组但本次只选一个版本的样本：正样本 $selectedCrossPositive 条，负样本 $selectedCrossNegative 条。
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
    unique_normalized_questions = @($selected | Select-Object -ExpandProperty content_hash -Unique).Count
} | ConvertTo-Json -Compress
