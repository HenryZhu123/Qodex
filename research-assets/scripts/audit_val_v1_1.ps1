param([string]$WorkspaceRoot = (Split-Path -Parent $PSScriptRoot))

$ErrorActionPreference = 'Stop'
$valPath = Join-Path $WorkspaceRoot '验证集\val_1.1.jsonl'
$trainPath = Join-Path $WorkspaceRoot '训练集-微调版提示词\train_v1.1\train_v1.1.jsonl'
$testPath = Join-Path $WorkspaceRoot '训练集-微调版提示词\train_v1\test_v3.jsonl'
$auditPath = Join-Path $WorkspaceRoot '验证集\val_1.1_audit.json'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

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

function Get-Sha256([string]$Text) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return -join ($sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Text)) | ForEach-Object { $_.ToString('x2') }) }
    finally { $sha.Dispose() }
}
function Normalize([string]$Text) {
    return (($Text.Normalize([System.Text.NormalizationForm]::FormKC) -replace '\s+', ' ').Trim())
}
function Get-Task($Record) {
    $system = $Record.messages | Where-Object role -eq 'system' | Select-Object -First 1
    foreach ($task in $taskPatterns.Keys) {
        if ($system.content -match "(?m)^# 任务：$([regex]::Escape($task))\s*$") { return $task }
    }
    return $null
}
function Get-Hashes([string]$Path) {
    $hashes = @{}
    foreach ($line in [System.IO.File]::ReadLines($Path, [System.Text.Encoding]::UTF8)) {
        $record = $line | ConvertFrom-Json
        $user = $record.messages | Where-Object role -eq 'user' | Select-Object -First 1
        $payload = (($user.content -replace '^\[INPUT_PAYLOAD\]\s*', '') | ConvertFrom-Json)
        $hashes[(Get-Sha256 (Normalize ([string]$payload.detection_content)))] = $true
    }
    return $hashes
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

$trainHashes = Get-Hashes $trainPath
$testHashes = Get-Hashes $testPath
$rows = New-Object System.Collections.Generic.List[object]
$invalidJson = 0
$invalidSchema = 0
$promptMismatch = 0
$invalidTypoPositive = 0
$trainOverlap = 0
$testOverlap = 0
$lineNumber = 0

foreach ($line in [System.IO.File]::ReadLines($valPath, [System.Text.Encoding]::UTF8)) {
    $lineNumber++
    try {
        $record = $line | ConvertFrom-Json
        $task = Get-Task $record
        $system = $record.messages | Where-Object role -eq 'system' | Select-Object -First 1
        $user = $record.messages | Where-Object role -eq 'user' | Select-Object -First 1
        $assistant = $record.messages | Where-Object role -eq 'assistant' | Select-Object -Last 1
        $payload = (($user.content -replace '^\[INPUT_PAYLOAD\]\s*', '') | ConvertFrom-Json)
        $answer = $assistant.content | ConvertFrom-Json
    }
    catch {
        $invalidJson++
        continue
    }
    if (-not $task -or $null -eq $payload.reference -or $null -eq $payload.detection_content -or $null -eq $answer.has_error) {
        $invalidSchema++
        continue
    }
    if ([int]$answer.total_errors -ne @($answer.errors).Count) { $invalidSchema++ }
    if ((-not [bool]$answer.has_error) -and ([int]$answer.total_errors -ne 0 -or @($answer.errors).Count -ne 0)) { $invalidSchema++ }
    foreach ($errorItem in @($answer.errors)) {
        $expectedType = if ($task -eq '选项结构错误') { '选项错误' } else { $task }
        if ([string]$errorItem.error_type -ne $expectedType) { $invalidSchema++ }
    }

    $taskCardMatch = [regex]::Match($system.content, $taskPatterns[$task])
    $expectedTaskCard = [System.IO.File]::ReadAllText($promptPaths[$task], [System.Text.Encoding]::UTF8).TrimEnd()
    if (-not $taskCardMatch.Success -or $taskCardMatch.Value.TrimEnd() -ne $expectedTaskCard) { $promptMismatch++ }

    $normalized = Normalize ([string]$payload.detection_content)
    $hash = Get-Sha256 $normalized
    if ($trainHashes.ContainsKey($hash)) { $trainOverlap++ }
    if ($testHashes.ContainsKey($hash)) { $testOverlap++ }
    if ($task -eq '错别字' -and [bool]$answer.has_error -and -not (Test-V4Positive $answer)) { $invalidTypoPositive++ }
    $rows.Add([pscustomobject]@{
        line = $lineNumber
        task = $task
        has_error = [bool]$answer.has_error
        hash = $hash
        reference = [string]$payload.reference
        detection = [string]$payload.detection_content
    })
}

$taskStats = [ordered]@{}
foreach ($task in @('错别字', '选项结构错误', '题目与题型不一致')) {
    $taskRows = @($rows | Where-Object task -eq $task)
    $taskStats[$task] = [ordered]@{
        total = $taskRows.Count
        positive = @($taskRows | Where-Object has_error).Count
        negative = @($taskRows | Where-Object { -not $_.has_error }).Count
        unique_questions = @($taskRows | Select-Object -ExpandProperty hash -Unique).Count
    }
}

$allGroups = @($rows | Group-Object hash)
$crossTaskDuplicateGroups = @($allGroups | Where-Object { @($_.Group | Select-Object -ExpandProperty task -Unique).Count -gt 1 }).Count
$mismatchGroups = @($rows | Where-Object task -eq '题目与题型不一致' | Group-Object hash)
$validMismatchPairs = 0
$invalidMismatchPairs = 0
foreach ($group in $mismatchGroups) {
    $labels = @($group.Group | Select-Object -ExpandProperty has_error | Sort-Object -Unique)
    $positive = @($group.Group | Where-Object has_error)
    $negative = @($group.Group | Where-Object { -not $_.has_error })
    $positiveTypeOk = ($positive.Count -eq 1 -and $positive[0].reference -match '(?m)【题型或其它信息】填空题\s*$')
    $negativeTypeOk = ($negative.Count -eq 1 -and $negative[0].reference -match '(?m)【题型或其它信息】选择题\s*$')
    if ($group.Count -eq 2 -and $labels.Count -eq 2 -and $positiveTypeOk -and $negativeTypeOk) { $validMismatchPairs++ }
    else { $invalidMismatchPairs++ }
}

$audit = [ordered]@{
    passed = ($rows.Count -eq 300 -and $invalidJson -eq 0 -and $invalidSchema -eq 0 -and $promptMismatch -eq 0 -and $invalidTypoPositive -eq 0 -and $trainOverlap -eq 0 -and $testOverlap -eq 0 -and $crossTaskDuplicateGroups -eq 0 -and $validMismatchPairs -eq 45 -and $invalidMismatchPairs -eq 0)
    total = $rows.Count
    positive = @($rows | Where-Object has_error).Count
    negative = @($rows | Where-Object { -not $_.has_error }).Count
    unique_questions = @($rows | Select-Object -ExpandProperty hash -Unique).Count
    invalid_json = $invalidJson
    invalid_schema = $invalidSchema
    prompt_mismatch = $promptMismatch
    invalid_typo_v4_positive = $invalidTypoPositive
    train_question_overlap = $trainOverlap
    old_test_question_overlap = $testOverlap
    cross_task_duplicate_groups = $crossTaskDuplicateGroups
    mismatch_valid_pair_groups = $validMismatchPairs
    mismatch_invalid_pair_groups = $invalidMismatchPairs
    task_stats = $taskStats
}
[System.IO.File]::WriteAllText($auditPath, ($audit | ConvertTo-Json -Depth 20), $utf8NoBom)
$audit | ConvertTo-Json -Depth 20 -Compress
if (-not $audit.passed) { exit 1 }
