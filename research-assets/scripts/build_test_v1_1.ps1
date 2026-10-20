param(
    [string]$WorkspaceRoot = (Split-Path -Parent $PSScriptRoot),
    [int]$Seed = 20260824
)

$ErrorActionPreference = 'Stop'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$tracePattern = '错误样本|原题|改造|构造|故意|刻意|注入|生成要求|为了满足'

$trainPath = Join-Path $WorkspaceRoot '训练集-微调版提示词\train_v1.1\train_v1.1.jsonl'
$valPath = Join-Path $WorkspaceRoot '验证集\val_1.1.jsonl'
$oldTestPath = Join-Path $WorkspaceRoot '训练集-微调版提示词\train_v1\test_v3.jsonl'
$oldValPath = Join-Path $WorkspaceRoot '训练集-微调版提示词\train_v1\val_v3.jsonl'
$typoSourcePaths = @(
    $oldValPath,
    (Join-Path $WorkspaceRoot '训练集-微调版提示词\错别字_训练集.jsonl'),
    (Join-Path $WorkspaceRoot '训练集-微调版提示词\v2_新增错别字正样本_162\train_v2_new_typo_positive_162.jsonl'),
    (Join-Path $WorkspaceRoot '训练集-微调版提示词\v2_新增错别字负样本_198\train_v2_new_typo_negative_198.jsonl')
)
$optionSourcePath = Join-Path $WorkspaceRoot '训练集-微调版提示词\选项结构错误_训练集.jsonl'
$mismatchSourcePath = Join-Path $WorkspaceRoot '训练集-微调版提示词\题目与题型不一致_训练集.jsonl'
$mismatchBaseSourcePaths = @(
    $optionSourcePath
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

$outputDir = Join-Path $WorkspaceRoot '测试集'
$outputPath = Join-Path $outputDir 'test_v1.1.jsonl'
$manifestPath = Join-Path $outputDir 'test_v1.1_manifest.jsonl'
$reportPath = Join-Path $outputDir 'TEST_V1.1_REPORT.md'
$auditPath = Join-Path $outputDir 'test_v1.1_audit.json'

function Get-Sha256([string]$Text) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return -join ($sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Text)) | ForEach-Object { $_.ToString('x2') }) }
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
    if ($system.content -match '(?m)^# 任务：语义不清\s*$') { return '语义不清' }
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
        $payload = (($user.content -replace '^\[INPUT_PAYLOAD\]\s*', '') | ConvertFrom-Json)
        $answer = $assistant.content | ConvertFrom-Json
        $normalized = Get-NormalizedContent ([string]$payload.detection_content)
        if ([string]::IsNullOrWhiteSpace($normalized)) { throw "题目正文为空：${Path}:$lineNumber" }
        $rows.Add([pscustomobject]@{
            task_type = $task
            record = $record
            answer = $answer
            has_error = [bool]$answer.has_error
            has_generation_trace = ($assistant.content -match $tracePattern)
            source_file = $Path
            source_line = $lineNumber
            origin = $Origin
            detection_content = [string]$payload.detection_content
            reference = [string]$payload.reference
            normalized_content = $normalized
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
        $differenceCount = 0
        for ($index = 0; $index -lt $original.Length; $index++) {
            if ($original[$index] -ne $correction[$index]) { $differenceCount++ }
        }
        if ($differenceCount -ne 1) { return $false }
    }
    return $true
}

function Set-CurrentPrompt($Row) {
    $task = $Row.task_type
    $system = $Row.record.messages | Where-Object { $_.role -eq 'system' } | Select-Object -First 1
    $newTaskCard = [System.IO.File]::ReadAllText($promptPaths[$task], [System.Text.Encoding]::UTF8).TrimEnd()
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
        foreach ($errorItem in @($answer.errors)) { $errorItem.error_type = '选项错误' }
        $assistant.content = $answer | ConvertTo-Json -Depth 30 -Compress
    }
}

function New-MismatchRowFromOption($BaseRow, [bool]$HasError) {
    $record = (($BaseRow.record | ConvertTo-Json -Depth 100 -Compress) | ConvertFrom-Json)
    $system = $record.messages | Where-Object { $_.role -eq 'system' } | Select-Object -First 1
    $sourceTaskPattern = '(?ms)^# 任务：[^\r\n]+\s*$.*?(?=^# 统一输出约束\s*$)'
    $mismatchTaskCard = [System.IO.File]::ReadAllText($promptPaths['题目与题型不一致'], [System.Text.Encoding]::UTF8).TrimEnd()
    if ([regex]::Matches($system.content, $sourceTaskPattern).Count -ne 1) {
        throw "构造题型测试样本时未唯一匹配源任务卡：$($BaseRow.source_file):$($BaseRow.source_line)"
    }
    $system.content = [regex]::Replace(
        $system.content,
        $sourceTaskPattern,
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
        $answer = [ordered]@{
            reason = '选择题>填空题'
            has_error = $true
            total_errors = 1
            errors = @([ordered]@{
                error_type = '题目与题型不一致'
                position = '题目整体的作答形式'
                original_text = $rawDetection.Substring(0, [math]::Min(20, $rawDetection.Length))
                anchor_text = $rawDetection.Substring(0, [math]::Min(60, $rawDetection.Length))
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
        answer = $answer
        has_error = $HasError
        has_generation_trace = $false
        source_file = $BaseRow.source_file
        source_line = $BaseRow.source_line
        origin = if ($HasError) { '未使用正常选择题改换题型标注' } else { '未使用正常选择题保留正确题型标注' }
        detection_content = $BaseRow.detection_content
        reference = [string]$payload.reference
        normalized_content = $BaseRow.normalized_content
        content_hash = $BaseRow.content_hash
        rank = Get-Sha256 "$Seed|test-mismatch|$HasError|$($BaseRow.source_file)|$($BaseRow.source_line)"
    }
}

# 训练集、验证集题面全部排除；旧测试集题面也作为已使用题排除新增样本。
$trainHashes = @{}
foreach ($row in @(Read-Rows $trainPath $null 'train_v1.1')) { $trainHashes[$row.content_hash] = $true }
$valHashes = @{}
foreach ($row in @(Read-Rows $valPath $null 'val_1.1')) { $valHashes[$row.content_hash] = $true }
$oldTestRows = @(Read-Rows $oldTestPath $null '旧test_v3')
$oldTestHashes = @{}
foreach ($row in $oldTestRows) { $oldTestHashes[$row.content_hash] = $true }

$selected = New-Object System.Collections.Generic.List[object]
$usedTestHashes = @{}

# 保留旧测试中的合格错别字和全部选项样本。
$keptTypoRows = @($oldTestRows | Where-Object {
    $_.task_type -eq '错别字' -and
    (-not $trainHashes.ContainsKey($_.content_hash)) -and
    (-not $valHashes.ContainsKey($_.content_hash)) -and
    ((-not $_.has_error) -or (Test-TypoV4Positive $_))
})
foreach ($row in $keptTypoRows) {
    if ($usedTestHashes.ContainsKey($row.content_hash)) { throw '旧错别字测试题内部重复' }
    $selected.Add($row); $usedTestHashes[$row.content_hash] = $true
}
$keptOptionRows = @($oldTestRows | Where-Object {
    $_.task_type -eq '选项结构错误' -and
    (-not $trainHashes.ContainsKey($_.content_hash)) -and
    (-not $valHashes.ContainsKey($_.content_hash))
})
foreach ($row in $keptOptionRows) {
    if ($usedTestHashes.ContainsKey($row.content_hash)) { throw '保留测试题跨类型重复' }
    $selected.Add($row); $usedTestHashes[$row.content_hash] = $true
}

$typoCandidates = New-Object System.Collections.Generic.List[object]
foreach ($path in $typoSourcePaths) {
    foreach ($row in @(Read-Rows $path '错别字' ('错别字补充：' + [System.IO.Path]::GetFileName($path)))) {
        if ($row.has_generation_trace) { continue }
        if ($row.has_error -and -not (Test-TypoV4Positive $row)) { continue }
        if ($trainHashes.ContainsKey($row.content_hash) -or $valHashes.ContainsKey($row.content_hash) -or $oldTestHashes.ContainsKey($row.content_hash) -or $usedTestHashes.ContainsKey($row.content_hash)) { continue }
        $typoCandidates.Add($row)
    }
}
$addedTypoPositive = 0
$addedTypoNegative = 0
foreach ($label in @($true, $false)) {
    $keptCount = @($keptTypoRows | Where-Object { $_.has_error -eq $label }).Count
    $target = if ($label) { 38 } else { 39 }
    $needed = $target - $keptCount
    $added = 0
    foreach ($row in @($typoCandidates | Where-Object { $_.has_error -eq $label } | Sort-Object rank)) {
        if ($added -ge $needed) { break }
        if (-not $usedTestHashes.ContainsKey($row.content_hash)) {
            $selected.Add($row); $usedTestHashes[$row.content_hash] = $true; $added++
        }
    }
    if ($added -ne $needed) { throw "合格错别字候选不足：标签=$label，需要=$needed，实际=$added" }
    if ($label) { $addedTypoPositive = $added } else { $addedTypoNegative = $added }
}

# 若旧选项题与训练/验证存在跨任务题面复用，则从专项数据按原39正/39负等量补齐。
$optionSupplementCandidates = @(Read-Rows $optionSourcePath '选项结构错误' '选项专项补充' | Where-Object {
    (-not $_.has_generation_trace) -and
    (-not $trainHashes.ContainsKey($_.content_hash)) -and
    (-not $valHashes.ContainsKey($_.content_hash)) -and
    (-not $oldTestHashes.ContainsKey($_.content_hash)) -and
    (-not $usedTestHashes.ContainsKey($_.content_hash))
} | Sort-Object rank)
$addedOptionPositive = 0
$addedOptionNegative = 0
foreach ($label in @($true, $false)) {
    $keptCount = @($keptOptionRows | Where-Object { $_.has_error -eq $label }).Count
    $needed = 39 - $keptCount
    $added = 0
    foreach ($row in @($optionSupplementCandidates | Where-Object { $_.has_error -eq $label })) {
        if ($added -ge $needed) { break }
        if (-not $usedTestHashes.ContainsKey($row.content_hash)) {
            $selected.Add($row); $usedTestHashes[$row.content_hash] = $true; $added++
        }
    }
    if ($added -ne $needed) { throw "选项候选不足：标签=$label，需要=$needed，实际=$added" }
    if ($label) { $addedOptionPositive = $added } else { $addedOptionNegative = $added }
}

# 先使用题型专项中尚未进入训练、验证、旧测试的真实样本；同一题面只选一个标签。
$mismatchTargetPositive = 41
$mismatchTargetNegative = 38
$mismatchSelected = New-Object System.Collections.Generic.List[object]
$mismatchSourceRows = @(Read-Rows $mismatchSourcePath '题目与题型不一致' '题型专项未使用样本')
foreach ($label in @($true, $false)) {
    $target = if ($label) { $mismatchTargetPositive } else { $mismatchTargetNegative }
    foreach ($row in @($mismatchSourceRows | Where-Object { $_.has_error -eq $label -and -not $_.has_generation_trace } | Sort-Object rank)) {
        if (@($mismatchSelected | Where-Object { $_.has_error -eq $label }).Count -ge $target) { break }
        if ($trainHashes.ContainsKey($row.content_hash) -or $valHashes.ContainsKey($row.content_hash) -or $oldTestHashes.ContainsKey($row.content_hash) -or $usedTestHashes.ContainsKey($row.content_hash)) { continue }
        $mismatchSelected.Add($row); $usedTestHashes[$row.content_hash] = $true
    }
}

# 专项未使用题不足的部分，从未使用的正常选择题构造；正负使用不同题面。
$mismatchPositiveNeeded = $mismatchTargetPositive - @($mismatchSelected | Where-Object { $_.has_error }).Count
$mismatchNegativeNeeded = $mismatchTargetNegative - @($mismatchSelected | Where-Object { -not $_.has_error }).Count
$optionCandidatesList = New-Object System.Collections.Generic.List[object]
foreach ($sourcePath in $mismatchBaseSourcePaths) {
    foreach ($row in @(Read-Rows $sourcePath $null ('未使用选择题候选：' + [System.IO.Path]::GetFileName($sourcePath)))) {
        if ($row.reference -notmatch '(?m)【题型或其它信息】[^\r\n]*(选择|单选)[^\r\n]*\s*$') { continue }
        if ($trainHashes.ContainsKey($row.content_hash) -or $valHashes.ContainsKey($row.content_hash) -or $oldTestHashes.ContainsKey($row.content_hash) -or $usedTestHashes.ContainsKey($row.content_hash)) { continue }
        $optionCandidatesList.Add($row)
    }
}
$optionCandidates = @($optionCandidatesList | Sort-Object rank)

$addedMismatchPositive = 0
foreach ($baseRow in $optionCandidates) {
    if ($addedMismatchPositive -ge $mismatchPositiveNeeded) { break }
    if (-not $usedTestHashes.ContainsKey($baseRow.content_hash)) {
        $newRow = New-MismatchRowFromOption $baseRow $true
        $mismatchSelected.Add($newRow); $usedTestHashes[$baseRow.content_hash] = $true; $addedMismatchPositive++
    }
}
$addedMismatchNegative = 0
foreach ($baseRow in $optionCandidates) {
    if ($addedMismatchNegative -ge $mismatchNegativeNeeded) { break }
    if (-not $usedTestHashes.ContainsKey($baseRow.content_hash)) {
        $newRow = New-MismatchRowFromOption $baseRow $false
        $mismatchSelected.Add($newRow); $usedTestHashes[$baseRow.content_hash] = $true; $addedMismatchNegative++
    }
}
if ($addedMismatchPositive -ne $mismatchPositiveNeeded -or $addedMismatchNegative -ne $mismatchNegativeNeeded) {
    throw "题型不一致补充候选不足：尚需/实际正=$mismatchPositiveNeeded/$addedMismatchPositive，负=$mismatchNegativeNeeded/$addedMismatchNegative"
}
foreach ($row in @($mismatchSelected | ForEach-Object { $_ })) { $selected.Add($row) }

$allSelected = @($selected | ForEach-Object { $_ })
$statsBeforeWrite = @{}
foreach ($task in @('错别字','选项结构错误','题目与题型不一致')) {
    $rows = @($allSelected | Where-Object { $_.task_type -eq $task })
    $statsBeforeWrite[$task] = [ordered]@{ total=$rows.Count; positive=@($rows | Where-Object { $_.has_error }).Count; negative=@($rows | Where-Object { -not $_.has_error }).Count }
}
if ($statsBeforeWrite['错别字'].total -ne 77 -or $statsBeforeWrite['错别字'].positive -ne 38 -or $statsBeforeWrite['错别字'].negative -ne 39) { throw '错别字配额异常' }
if ($statsBeforeWrite['选项结构错误'].total -ne 78 -or $statsBeforeWrite['选项结构错误'].positive -ne 39 -or $statsBeforeWrite['选项结构错误'].negative -ne 39) { throw '选项配额异常' }
if ($statsBeforeWrite['题目与题型不一致'].total -ne 79 -or $statsBeforeWrite['题目与题型不一致'].positive -ne 41 -or $statsBeforeWrite['题目与题型不一致'].negative -ne 38) { throw '题型不一致配额异常' }
if ($allSelected.Count -ne 234 -or $usedTestHashes.Count -ne 234) { throw "测试集总量或唯一题面异常：$($allSelected.Count)/$($usedTestHashes.Count)" }

$allSelected = @($allSelected | Sort-Object @{ Expression = { Get-Sha256 "$Seed|final-test|$($_.task_type)|$($_.source_file)|$($_.source_line)|$($_.has_error)" } })
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
$outputWriter = New-Object System.IO.StreamWriter($outputPath, $false, $utf8NoBom)
$manifestWriter = New-Object System.IO.StreamWriter($manifestPath, $false, $utf8NoBom)
try {
    $index = 0
    foreach ($row in $allSelected) {
        $index++
        Set-CurrentPrompt $row
        $outputWriter.WriteLine(($row.record | ConvertTo-Json -Depth 100 -Compress))
        $manifestWriter.WriteLine(([ordered]@{
            sample_id = ('TEST-V1.1-{0:D4}' -f $index)
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
finally { $outputWriter.Dispose(); $manifestWriter.Dispose() }

# 写后独立核心检查。
$outputRows = @(Read-Rows $outputPath $null 'test_v1.1输出')
$outputHashes = @($outputRows | Select-Object -ExpandProperty content_hash)
$duplicateGroups = @($outputHashes | Group-Object | Where-Object { $_.Count -gt 1 }).Count
$trainOverlap = @($outputRows | Where-Object { $trainHashes.ContainsKey($_.content_hash) }).Count
$valOverlap = @($outputRows | Where-Object { $valHashes.ContainsKey($_.content_hash) }).Count
$nonV4TypoPositive = @($outputRows | Where-Object { $_.task_type -eq '错别字' -and $_.has_error -and -not (Test-TypoV4Positive $_) }).Count
$audit = [ordered]@{
    passed = ($outputRows.Count -eq 234 -and $duplicateGroups -eq 0 -and $trainOverlap -eq 0 -and $valOverlap -eq 0 -and $nonV4TypoPositive -eq 0)
    total = $outputRows.Count
    positive = @($outputRows | Where-Object { $_.has_error }).Count
    negative = @($outputRows | Where-Object { -not $_.has_error }).Count
    unique_questions = @($outputHashes | Select-Object -Unique).Count
    duplicate_question_groups = $duplicateGroups
    train_question_overlap = $trainOverlap
    val_question_overlap = $valOverlap
    non_v4_typo_positive = $nonV4TypoPositive
    task_stats = $statsBeforeWrite
    replaced_old_typo_positive = $addedTypoPositive
    replaced_old_typo_negative = $addedTypoNegative
    replaced_old_option_positive = $addedOptionPositive
    replaced_old_option_negative = $addedOptionNegative
    mismatch_from_dedicated_source = $mismatchSelected.Count - $addedMismatchPositive - $addedMismatchNegative
    mismatch_synthesized_positive = $addedMismatchPositive
    mismatch_synthesized_negative = $addedMismatchNegative
}
[System.IO.File]::WriteAllText($auditPath, ($audit | ConvertTo-Json -Depth 20), $utf8NoBom)
if (-not $audit.passed) { throw 'test_v1.1写后审计失败' }

$report = @"
# test_v1.1 构建报告

| 错误类型 | 总数 | 正样本 | 负样本 | 占测试集比例 |
|---|---:|---:|---:|---:|
| 错别字 | 77 | 38 | 39 | 32.91% |
| 选项结构错误 | 78 | 39 | 39 | 33.33% |
| 题目与题型不一致 | 79 | 41 | 38 | 33.76% |
| 合计 | 234 | 118 | 116 | 100.00% |

## 构建结果

- 将旧 ``test_v3`` 的79条语义不清替换为79条题目与题型不一致，保持原类别数量及41正/38负不变。
- 保留78条选项结构错误测试题，并统一使用当前提示词与 ``error_type=选项错误``。
- 旧错别字测试中不符合v4边界或与训练/验证存在全局题面复用的样本已替换：正 $addedTypoPositive 条、负 $addedTypoNegative 条；最终77条仍为38正/39负，全部正样本符合v4边界。
- 旧选项测试中与训练/验证存在全局题面复用的样本已替换：正 $addedOptionPositive 条、负 $addedOptionNegative 条；最终仍为39正/39负。
- 与 ``train_v1.1`` 题面重合：0；与 ``val_1.1`` 题面重合：0。
- 测试集234条题面全部唯一；不存在同一道题的正负版本，也不存在跨类型复用。
- 题型专项未使用真实样本：$($mismatchSelected.Count - $addedMismatchPositive - $addedMismatchNegative) 条；从未使用正常选择题构建清晰题型标注样本：正 $addedMismatchPositive 条、负 $addedMismatchNegative 条。
- 固定选择种子：``$Seed``。
"@
[System.IO.File]::WriteAllText($reportPath, $report, $utf8NoBom)

[ordered]@{ output=$outputPath; manifest=$manifestPath; report=$reportPath; audit=$auditPath; audit_result=$audit } | ConvertTo-Json -Depth 20 -Compress
