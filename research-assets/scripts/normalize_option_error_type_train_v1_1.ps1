param([string]$WorkspaceRoot = (Split-Path -Parent $PSScriptRoot))

$ErrorActionPreference = 'Stop'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$paths = @(
    (Join-Path $WorkspaceRoot '训练集-微调版提示词\train_v1_restart\选项结构错误_训练集_450.jsonl'),
    (Join-Path $WorkspaceRoot '训练集-微调版提示词\train_v1.1\train_v1.1.jsonl')
)
$reportPath = Join-Path $WorkspaceRoot '训练集-微调版提示词\train_v1.1\选项错误标签统一报告.json'

function Get-Sha256([string]$Text) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return -join ($sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($Text)) | ForEach-Object { $_.ToString('x2') }) }
    finally { $sha.Dispose() }
}

function Get-DatasetSnapshot([string]$Path) {
    $lineCount = 0
    $taskCount = 0
    $positiveCount = 0
    $negativeCount = 0
    $questionHashes = New-Object System.Collections.Generic.List[string]
    $oldLabelCount = 0
    $currentLabelCount = 0
    foreach ($line in [System.IO.File]::ReadLines($Path, [System.Text.Encoding]::UTF8)) {
        $lineCount++
        $record = $line | ConvertFrom-Json
        $system = $record.messages | Where-Object { $_.role -eq 'system' } | Select-Object -First 1
        if ($system.content -notmatch '(?m)^# 任务：选项结构错误\s*$') { continue }
        $taskCount++
        $user = $record.messages | Where-Object { $_.role -eq 'user' } | Select-Object -First 1
        $assistant = $record.messages | Where-Object { $_.role -eq 'assistant' } | Select-Object -Last 1
        $payload = (($user.content -replace '^\[INPUT_PAYLOAD\]\s*', '') | ConvertFrom-Json)
        $answer = $assistant.content | ConvertFrom-Json
        if ([bool]$answer.has_error) { $positiveCount++ } else { $negativeCount++ }
        foreach ($errorItem in @($answer.errors)) {
            if ([string]$errorItem.error_type -eq '选项结构错误') { $oldLabelCount++ }
            if ([string]$errorItem.error_type -eq '选项错误') { $currentLabelCount++ }
        }
        $normalized = (([string]$payload.detection_content).Normalize([System.Text.NormalizationForm]::FormKC) -replace '\s+', ' ').Trim()
        $questionHashes.Add((Get-Sha256 $normalized))
    }
    return [ordered]@{
        total_lines = $lineCount
        option_samples = $taskCount
        option_positive = $positiveCount
        option_negative = $negativeCount
        old_label_items = $oldLabelCount
        current_label_items = $currentLabelCount
        ordered_question_digest = Get-Sha256 (($questionHashes | ForEach-Object { $_ }) -join "`n")
    }
}

$results = New-Object System.Collections.Generic.List[object]
foreach ($path in $paths) {
    if (-not (Test-Path -LiteralPath $path)) { throw "文件不存在：$path" }
    $before = Get-DatasetSnapshot $path
    $tempPath = "$path.codex-normalize.tmp"
    $writer = New-Object System.IO.StreamWriter($tempPath, $false, $utf8NoBom)
    $changedItems = 0
    $changedSamples = 0
    try {
        foreach ($line in [System.IO.File]::ReadLines($path, [System.Text.Encoding]::UTF8)) {
            $record = $line | ConvertFrom-Json
            $system = $record.messages | Where-Object { $_.role -eq 'system' } | Select-Object -First 1
            $sampleChanged = $false
            if ($system.content -match '(?m)^# 任务：选项结构错误\s*$') {
                $assistant = $record.messages | Where-Object { $_.role -eq 'assistant' } | Select-Object -Last 1
                $answer = $assistant.content | ConvertFrom-Json
                foreach ($errorItem in @($answer.errors)) {
                    if ([string]$errorItem.error_type -eq '选项结构错误') {
                        $errorItem.error_type = '选项错误'
                        $changedItems++
                        $sampleChanged = $true
                    }
                }
                if ($sampleChanged) {
                    $changedSamples++
                    $assistant.content = $answer | ConvertTo-Json -Depth 30 -Compress
                }
            }
            $writer.WriteLine(($record | ConvertTo-Json -Depth 100 -Compress))
        }
    }
    finally { $writer.Dispose() }

    [System.IO.File]::Copy($tempPath, $path, $true)
    Remove-Item -LiteralPath $tempPath -Force
    $after = Get-DatasetSnapshot $path
    if ($after.total_lines -ne $before.total_lines -or
        $after.option_samples -ne $before.option_samples -or
        $after.option_positive -ne $before.option_positive -or
        $after.option_negative -ne $before.option_negative -or
        $after.ordered_question_digest -ne $before.ordered_question_digest) {
        throw "修正后样本结构或题面发生变化：$path"
    }
    if ($after.old_label_items -ne 0) { throw "修正后仍存在旧标签：$path" }
    $results.Add([ordered]@{
        path = $path
        changed_samples = $changedSamples
        changed_error_items = $changedItems
        before = $before
        after = $after
    })
}

$report = [ordered]@{
    completed_at = [DateTime]::Now.ToString('yyyy-MM-dd HH:mm:ss')
    required_error_type = '选项错误'
    files = @($results | ForEach-Object { $_ })
}
[System.IO.File]::WriteAllText($reportPath, ($report | ConvertTo-Json -Depth 20), $utf8NoBom)
$report | ConvertTo-Json -Depth 20 -Compress
