param(
    [string]$WorkspaceRoot = (Split-Path -Parent $PSScriptRoot),
    [int]$Seed = 20260824
)

$ErrorActionPreference = 'Stop'
$componentDir = Join-Path $WorkspaceRoot '训练集-微调版提示词\train_v1_restart'
$outputDir = Join-Path $WorkspaceRoot '训练集-微调版提示词\train_v1.1'
$outputPath = Join-Path $outputDir 'train_v1.1.jsonl'
$manifestPath = Join-Path $outputDir 'train_v1.1_manifest.jsonl'
$reportPath = Join-Path $outputDir 'TRAIN_V1.1_REPORT.md'
$utf8NoBom = New-Object Text.UTF8Encoding($false)

$components = @(
    [pscustomobject]@{
        task = '错别字'
        expected_total = 600
        data = Join-Path $componentDir '错别字_训练集_600.jsonl'
        manifest = Join-Path $componentDir '错别字_训练集_600_manifest.jsonl'
    },
    [pscustomobject]@{
        task = '选项结构错误'
        expected_total = 450
        data = Join-Path $componentDir '选项结构错误_训练集_450.jsonl'
        manifest = Join-Path $componentDir '选项结构错误_训练集_450_manifest.jsonl'
    },
    [pscustomobject]@{
        task = '题目与题型不一致'
        expected_total = 450
        data = Join-Path $componentDir '题目与题型不一致_训练集_450.jsonl'
        manifest = Join-Path $componentDir '题目与题型不一致_训练集_450_manifest.jsonl'
    }
)

function Get-Sha256([string]$Text) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return -join ($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)) | ForEach-Object { $_.ToString('x2') }) }
    finally { $sha.Dispose() }
}

New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
$mergedRows = @()

foreach ($component in $components) {
    $dataLines = @([IO.File]::ReadAllLines($component.data, [Text.Encoding]::UTF8))
    $manifestLines = @([IO.File]::ReadAllLines($component.manifest, [Text.Encoding]::UTF8))
    if ($dataLines.Count -ne $component.expected_total -or $manifestLines.Count -ne $component.expected_total) {
        throw "$($component.task) 数量异常：data/manifest=$($dataLines.Count)/$($manifestLines.Count)"
    }

    for ($index = 0; $index -lt $dataLines.Count; $index++) {
        $record = $dataLines[$index] | ConvertFrom-Json
        $sourceManifest = $manifestLines[$index] | ConvertFrom-Json
        $systemMessage = $record.messages | Where-Object { $_.role -eq 'system' } | Select-Object -First 1
        $assistantMessage = $record.messages | Where-Object { $_.role -eq 'assistant' } | Select-Object -Last 1
        $answer = $assistantMessage.content | ConvertFrom-Json
        if ($systemMessage.content -notmatch "(?m)^# 任务：$([regex]::Escape($component.task))\s*$") {
            throw "$($component.task) 第 $($index + 1) 条任务卡不一致"
        }
        if ([bool]$answer.has_error -ne [bool]$sourceManifest.has_error) {
            throw "$($component.task) 第 $($index + 1) 条标签与 manifest 不一致"
        }
        $mergedRows += [pscustomobject]@{
            task = $component.task
            data_line = $dataLines[$index]
            source_manifest = $sourceManifest
            has_error = [bool]$answer.has_error
            content_hash = [string]$sourceManifest.normalized_content_sha256
            rank = Get-Sha256 "$Seed|merge|$($component.task)|$($sourceManifest.sample_id)"
        }
    }
}

$mergedRows = @($mergedRows | Sort-Object rank)
$outputWriter = New-Object IO.StreamWriter($outputPath, $false, $utf8NoBom)
$manifestWriter = New-Object IO.StreamWriter($manifestPath, $false, $utf8NoBom)

try {
    for ($index = 0; $index -lt $mergedRows.Count; $index++) {
        $row = $mergedRows[$index]
        $outputWriter.WriteLine($row.data_line)
        $newManifest = [ordered]@{
            sample_id = ('TRAIN-V1.1-{0:D4}' -f ($index + 1))
            merged_line = $index + 1
            task_type = $row.task
            has_error = $row.has_error
            component_sample_id = $row.source_manifest.sample_id
            normalized_content_sha256 = $row.content_hash
            source_file = $row.source_manifest.source_file
            source_line = $row.source_manifest.source_line
            origin = $row.source_manifest.origin
            prompt_file = $row.source_manifest.prompt_file
            selection_seed = $row.source_manifest.selection_seed
            merge_seed = $Seed
        }
        if ($null -ne $row.source_manifest.source_content_group_size) {
            $newManifest.source_content_group_size = $row.source_manifest.source_content_group_size
            $newManifest.source_group_has_both_labels = $row.source_manifest.source_group_has_both_labels
        }
        $manifestWriter.WriteLine(($newManifest | ConvertTo-Json -Compress))
    }
}
finally {
    $outputWriter.Dispose()
    $manifestWriter.Dispose()
}

$taskStats = @{}
foreach ($task in @('错别字', '选项结构错误', '题目与题型不一致')) {
    $taskRows = @($mergedRows | Where-Object { $_.task -eq $task })
    $taskStats[$task] = [pscustomobject]@{
        total = $taskRows.Count
        positive = @($taskRows | Where-Object { $_.has_error }).Count
        negative = @($taskRows | Where-Object { -not $_.has_error }).Count
    }
}

$withinTaskDuplicateGroups = 0
foreach ($task in $taskStats.Keys) {
    $withinTaskDuplicateGroups += @($mergedRows | Where-Object { $_.task -eq $task } | Group-Object content_hash | Where-Object { $_.Count -gt 1 }).Count
}
$crossTaskQuestionGroups = @($mergedRows | Group-Object content_hash | Where-Object {
    (@($_.Group | Select-Object -ExpandProperty task -Unique).Count -gt 1)
}).Count

$totalPositive = @($mergedRows | Where-Object { $_.has_error }).Count
$totalNegative = @($mergedRows | Where-Object { -not $_.has_error }).Count
$report = @"
# train_v1.1 构建报告

## 任务构成

| 错误类型 | 总量 | 类型占比 | 正样本 | 负样本 |
|---|---:|---:|---:|---:|
| 错别字 | $($taskStats['错别字'].total) | 40.00% | $($taskStats['错别字'].positive) | $($taskStats['错别字'].negative) |
| 选项结构错误 | $($taskStats['选项结构错误'].total) | 30.00% | $($taskStats['选项结构错误'].positive) | $($taskStats['选项结构错误'].negative) |
| 题目与题型不一致 | $($taskStats['题目与题型不一致'].total) | 30.00% | $($taskStats['题目与题型不一致'].positive) | $($taskStats['题目与题型不一致'].negative) |
| 合计 | $($mergedRows.Count) | 100.00% | $totalPositive | $totalNegative |

## 验收

- 三类数据按固定种子 ``$Seed`` 统一打散。
- 每类内部规范化题目重复组：$withinTaskDuplicateGroups。
- 跨任务使用相同题面组：$crossTaskQuestionGroups；不同任务卡下复用题面属于多任务训练，不属于同一专项内重复。
- 主训练文件和 manifest 均为 $($mergedRows.Count) 行。
- 原三个专项文件保留不变。
"@
[IO.File]::WriteAllText($reportPath, $report, $utf8NoBom)

[ordered]@{
    output = $outputPath
    manifest = $manifestPath
    report = $reportPath
    total = $mergedRows.Count
    positive = $totalPositive
    negative = $totalNegative
    within_task_duplicate_groups = $withinTaskDuplicateGroups
    cross_task_question_groups = $crossTaskQuestionGroups
} | ConvertTo-Json -Compress
