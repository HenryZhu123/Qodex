param(
    [string]$InputPath = "C:\hyt-agent\测试集\test_v1.1.jsonl",
    [string]$OutputPath = "C:\hyt-agent\测试集\test_v1.1_测试集.csv"
)

$ErrorActionPreference = "Stop"

function Get-MessageContent {
    param($Messages, [string]$Role)
    $message = $Messages | Where-Object { $_.role -eq $Role } | Select-Object -First 1
    if ($null -eq $message) {
        throw "样本缺少 $Role 消息"
    }
    return [string]$message.content
}

$rows = [System.Collections.Generic.List[object]]::new()
$lineNumber = 0

Get-Content -LiteralPath $InputPath -Encoding UTF8 | ForEach-Object {
    $lineNumber++
    if ([string]::IsNullOrWhiteSpace($_)) { return }

    $sample = $_ | ConvertFrom-Json
    $systemText = Get-MessageContent -Messages $sample.messages -Role "system"
    $userText = Get-MessageContent -Messages $sample.messages -Role "user"
    $goldText = Get-MessageContent -Messages $sample.messages -Role "assistant"

    $taskMatch = [regex]::Match($systemText, '(?m)^# 任务：([^\r\n]+)')
    if (-not $taskMatch.Success) {
        throw "第 $lineNumber 行无法从 system 消息识别任务类型"
    }
    $errorType = $taskMatch.Groups[1].Value.Trim()
    if ($errorType -eq "选项结构错误") { $errorType = "选项错误" }

    $payloadText = $userText -replace '^\s*\[INPUT_PAYLOAD\]\s*', ''
    $payload = $payloadText | ConvertFrom-Json
    $gold = $goldText | ConvertFrom-Json

    $goldErrors = @($gold.errors)
    $hasError = [bool]$gold.has_error
    $errorCount = if ($hasError) { [int]$gold.total_errors } else { 0 }
    $correction = if ($hasError) {
        ConvertTo-Json -InputObject $goldErrors -Compress -Depth 12
    } else {
        ""
    }

    $rows.Add([pscustomobject][ordered]@{
        id = $lineNumber
        title = [string]$payload.reference
        error_content = [string]$payload.detection_content
        error_type = $errorType
        correction = $correction
        error_cnt = $errorCount
        is_real_error = if ($hasError) { 1 } else { 0 }
        gold_reason = [string]$gold.reason
    })
}

$outputDirectory = Split-Path -Parent $OutputPath
if ($outputDirectory -and -not (Test-Path -LiteralPath $outputDirectory)) {
    New-Item -ItemType Directory -Path $outputDirectory | Out-Null
}

$rows | Export-Csv -LiteralPath $OutputPath -NoTypeInformation -Encoding utf8BOM

$summary = $rows | Group-Object error_type | ForEach-Object {
    $positive = @($_.Group | Where-Object { $_.error_cnt -gt 0 }).Count
    [pscustomobject]@{
        error_type = $_.Name
        total = $_.Count
        positive = $positive
        negative = $_.Count - $positive
    }
}

Write-Output "已生成: $OutputPath"
Write-Output "总样本: $($rows.Count)"
$summary | Format-Table -AutoSize
