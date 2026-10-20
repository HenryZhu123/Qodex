param(
    [string]$ExcelPath = "C:\hyt-agent\测试集\test_v1.1_测试集.xlsx",
    [string]$JsonlPath = "C:\hyt-agent\测试集\test_v1.1.jsonl"
)

$ErrorActionPreference = "Stop"
$excel = $null
$book = $null
$sheet = $null
$used = $null

try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $book = $excel.Workbooks.Open($ExcelPath, 0, $true)
    $sheet = $book.Worksheets.Item(1)
    $used = $sheet.UsedRange
    $data = $used.Value2
    $rowCount = $used.Rows.Count
    $columnCount = $used.Columns.Count
    $sheetName = $sheet.Name
    $autoFilter = [bool]$sheet.AutoFilterMode
    $freezePanes = [bool]$excel.ActiveWindow.FreezePanes
} finally {
    if ($book) { $book.Close($false) }
    if ($excel) { $excel.Quit() }
    foreach ($item in @($used, $sheet, $book, $excel)) {
        if ($item) { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($item) }
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

$expectedHeaders = @(
    "id", "title", "error_content", "error_type",
    "correction", "error_cnt", "is_real_error", "gold_reason"
)
$headers = for ($column = 1; $column -le $columnCount; $column++) {
    [string]$data[1, $column]
}

$issues = [Collections.Generic.List[string]]::new()
if (($headers -join "|") -ne ($expectedHeaders -join "|")) {
    $issues.Add("表头不符：$($headers -join ',')")
}

$lines = @(Get-Content -LiteralPath $JsonlPath -Encoding UTF8 | Where-Object {
    -not [string]::IsNullOrWhiteSpace($_)
})
if (($rowCount - 1) -ne $lines.Count) {
    $issues.Add("行数不符：Excel=$($rowCount - 1)，JSONL=$($lines.Count)")
}

$counts = @{}
for ($index = 0; $index -lt $lines.Count; $index++) {
    $sample = $lines[$index] | ConvertFrom-Json
    $systemText = [string](($sample.messages | Where-Object role -eq "system" | Select-Object -First 1).content)
    $userText = [string](($sample.messages | Where-Object role -eq "user" | Select-Object -First 1).content)
    $assistantText = [string](($sample.messages | Where-Object role -eq "assistant" | Select-Object -First 1).content)
    $payload = ($userText -replace '^\s*\[INPUT_PAYLOAD\]\s*', '') | ConvertFrom-Json
    $gold = $assistantText | ConvertFrom-Json

    $taskMatch = [regex]::Match($systemText, '(?m)^# 任务：([^\r\n]+)')
    $errorType = $taskMatch.Groups[1].Value.Trim()
    if ($errorType -eq "选项结构错误") { $errorType = "选项错误" }

    $polarity = if ([bool]$gold.has_error) { "正" } else { "负" }
    $countKey = "$errorType-$polarity"
    $counts[$countKey] = 1 + [int]$counts[$countKey]

    $row = $index + 2
    if ([int]$data[$row, 1] -ne ($index + 1)) { $issues.Add("第$($index + 1)条：id") }
    if ([string]$data[$row, 2] -cne [string]$payload.reference) { $issues.Add("第$($index + 1)条：title") }
    if ([string]$data[$row, 3] -cne [string]$payload.detection_content) { $issues.Add("第$($index + 1)条：error_content") }
    if ([string]$data[$row, 4] -cne $errorType) { $issues.Add("第$($index + 1)条：error_type") }

    $expectedErrorCount = if ([bool]$gold.has_error) { [int]$gold.total_errors } else { 0 }
    $expectedRealError = if ([bool]$gold.has_error) { 1 } else { 0 }
    if ([int]$data[$row, 6] -ne $expectedErrorCount) { $issues.Add("第$($index + 1)条：error_cnt") }
    if ([int]$data[$row, 7] -ne $expectedRealError) { $issues.Add("第$($index + 1)条：is_real_error") }
    if ([string]$data[$row, 8] -cne [string]$gold.reason) { $issues.Add("第$($index + 1)条：gold_reason") }

    $actualCorrection = [string]$data[$row, 5]
    if ([bool]$gold.has_error) {
        try {
            $actualCanonical = ($actualCorrection | ConvertFrom-Json) | ConvertTo-Json -Compress -Depth 20
            $goldCanonical = @($gold.errors) | ConvertTo-Json -Compress -Depth 20
            if ($actualCanonical -cne $goldCanonical) {
                $issues.Add("第$($index + 1)条：correction内容")
            }
        } catch {
            $issues.Add("第$($index + 1)条：correction JSON非法")
        }
    } elseif (-not [string]::IsNullOrWhiteSpace($actualCorrection)) {
        $issues.Add("第$($index + 1)条：负样本correction非空")
    }

    if ($issues.Count -ge 30) { break }
}

[pscustomobject]@{
    Sheet = $sheetName
    Rows = $rowCount - 1
    Columns = $columnCount
    Headers = $headers -join ","
    AutoFilter = $autoFilter
    FreezePanes = $freezePanes
    IssueCount = $issues.Count
    Issues = $issues -join "；"
    Distribution = ($counts.GetEnumerator() | Sort-Object Name | ForEach-Object {
        "$($_.Name)=$($_.Value)"
    }) -join "，"
}
