param(
    [string]$WorkspaceRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem

$workbookPath = Join-Path $WorkspaceRoot '数据集\错别字_测试集4-加入真实错误_v3.xlsx'
$trainPath = Join-Path $WorkspaceRoot '训练集-微调版提示词\train_v1.1\train_v1.1.jsonl'
$manifestPath = Join-Path $WorkspaceRoot '训练集-微调版提示词\train_v1.1\train_v1.1_manifest.jsonl'
$outputDir = Join-Path $WorkspaceRoot '训练集-微调版提示词\train_v1.1'
$auditPath = Join-Path $outputDir '错别字边界复核报告.json'
$suspiciousPath = Join-Path $outputDir '错别字边界待替换样本.jsonl'
$utf8NoBom = New-Object Text.UTF8Encoding($false)

function Get-Sha256([string]$Text) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return -join ($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)) | ForEach-Object { $_.ToString('x2') }) }
    finally { $sha.Dispose() }
}

function Get-NormalizedContent([string]$Text) {
    return (($Text.Normalize([Text.NormalizationForm]::FormKC) -replace '\s+', ' ').Trim())
}

function Read-FirstWorksheet([string]$Path) {
    $zip = [IO.Compression.ZipFile]::OpenRead($Path)
    function Read-ZipEntry([IO.Compression.ZipArchive]$Archive, [string]$Name) {
        $entry = $Archive.GetEntry($Name)
        if ($null -eq $entry) { return $null }
        $reader = New-Object IO.StreamReader($entry.Open(), [Text.Encoding]::UTF8)
        try { return $reader.ReadToEnd() }
        finally { $reader.Dispose() }
    }

    try {
        $sharedStrings = @()
        $sharedXml = Read-ZipEntry $zip 'xl/sharedStrings.xml'
        if ($sharedXml) {
            $sharedDoc = New-Object Xml.XmlDocument
            $sharedDoc.LoadXml($sharedXml)
            $sharedNs = New-Object Xml.XmlNamespaceManager($sharedDoc.NameTable)
            $sharedNs.AddNamespace('a', 'http://schemas.openxmlformats.org/spreadsheetml/2006/main')
            foreach ($item in $sharedDoc.SelectNodes('//a:si', $sharedNs)) {
                $sharedStrings += (($item.SelectNodes('.//a:t', $sharedNs) | ForEach-Object { $_.InnerText }) -join '')
            }
        }

        $sheetDoc = New-Object Xml.XmlDocument
        $sheetDoc.LoadXml((Read-ZipEntry $zip 'xl/worksheets/sheet1.xml'))
        $sheetNs = New-Object Xml.XmlNamespaceManager($sheetDoc.NameTable)
        $sheetNs.AddNamespace('a', 'http://schemas.openxmlformats.org/spreadsheetml/2006/main')
        $headers = @{}
        $records = @()

        foreach ($row in $sheetDoc.SelectNodes('//a:sheetData/a:row', $sheetNs)) {
            $cells = @{}
            foreach ($cell in $row.SelectNodes('./a:c', $sheetNs)) {
                $column = ([regex]::Match($cell.r, '^[A-Z]+')).Value
                $value = ''
                if ($cell.t -eq 'inlineStr') {
                    $value = (($cell.SelectNodes('.//a:t', $sheetNs) | ForEach-Object { $_.InnerText }) -join '')
                }
                else {
                    $valueNode = $cell.SelectSingleNode('./a:v', $sheetNs)
                    if ($valueNode) {
                        $value = $valueNode.InnerText
                        if ($cell.t -eq 's') { $value = $sharedStrings[[int]$value] }
                    }
                }
                $cells[$column] = $value
            }

            if ($row.r -eq '1') {
                $headers = $cells
            }
            else {
                $record = [ordered]@{}
                foreach ($column in $headers.Keys) { $record[$headers[$column]] = $cells[$column] }
                $records += [pscustomobject]$record
            }
        }
        return $records
    }
    finally {
        $zip.Dispose()
    }
}

$workbookRows = @(Read-FirstWorksheet $workbookPath)
$workbookCorrectHashes = @{}
$workbookErrorHashes = @{}
$workbookErrorDetails = @{}
$workbookDetailedTypes = @{}
foreach ($row in $workbookRows) {
    $correctHash = Get-Sha256 (Get-NormalizedContent ([string]$row.content))
    $workbookCorrectHashes[$correctHash] = $true
    if ([int]$row.error_cnt -gt 0) {
        $errorHash = Get-Sha256 (Get-NormalizedContent ([string]$row.error_content))
        $workbookErrorHashes[$errorHash] = $true
        $detail = [string]$row.error_detailed_type
        $workbookErrorDetails[$errorHash] = $detail
        if (-not $workbookDetailedTypes.ContainsKey($detail)) { $workbookDetailedTypes[$detail] = 0 }
        $workbookDetailedTypes[$detail]++
    }
}

$trainLines = @([IO.File]::ReadAllLines($trainPath, [Text.Encoding]::UTF8))
$manifestLines = @([IO.File]::ReadAllLines($manifestPath, [Text.Encoding]::UTF8))
if ($trainLines.Count -ne $manifestLines.Count) { throw '训练文件与 manifest 行数不一致' }

$typoTotal = 0
$positive = 0
$negative = 0
$strictPositive = 0
$disallowedPositive = @()
$negativeMatchingWorkbookError = @()
$positiveMatchingWorkbookCorrectOnly = @()
$positiveInWorkbook = 0
$negativeInWorkbook = 0
$matchedWorkbookDetailedTypes = @{}
$nonV4WorkbookTypePositive = @()

for ($index = 0; $index -lt $trainLines.Count; $index++) {
    $record = $trainLines[$index] | ConvertFrom-Json
    $manifest = $manifestLines[$index] | ConvertFrom-Json
    $systemMessage = $record.messages | Where-Object { $_.role -eq 'system' } | Select-Object -First 1
    if ($systemMessage.content -notmatch '(?m)^# 任务：错别字\s*$') { continue }
    $typoTotal++
    $userMessage = $record.messages | Where-Object { $_.role -eq 'user' } | Select-Object -First 1
    $assistantMessage = $record.messages | Where-Object { $_.role -eq 'assistant' } | Select-Object -Last 1
    $payload = (($userMessage.content -replace '^\[INPUT_PAYLOAD\]\s*', '') | ConvertFrom-Json)
    $answer = $assistantMessage.content | ConvertFrom-Json
    $contentHash = Get-Sha256 (Get-NormalizedContent ([string]$payload.detection_content))

    if ($answer.has_error) {
        $positive++
        $isStrict = $true
        $violations = @()
        foreach ($errorItem in $answer.errors) {
            $original = [string]$errorItem.original_text
            $correction = [string]$errorItem.correction
            if ($original -notmatch '^[\u3400-\u9fff]+$' -or $correction -notmatch '^[\u3400-\u9fff]+$') {
                $isStrict = $false
                $violations += '包含非汉字或英文/符号修改'
                continue
            }
            if ($original.Length -ne $correction.Length) {
                $isStrict = $false
                $violations += '多字、漏字或增删字'
                continue
            }
            $differenceCount = 0
            for ($charIndex = 0; $charIndex -lt $original.Length; $charIndex++) {
                if ($original[$charIndex] -ne $correction[$charIndex]) { $differenceCount++ }
            }
            if ($differenceCount -ne 1) {
                $isStrict = $false
                $violations += '倒字或多字符同时变化'
            }
        }
        if ($isStrict) { $strictPositive++ }
        else {
            $disallowedPositive += [ordered]@{
                merged_line = $index + 1
                sample_id = $manifest.sample_id
                violations = @($violations | Select-Object -Unique)
                source_file = $manifest.source_file
                source_line = $manifest.source_line
            }
        }

        if ($workbookErrorHashes.ContainsKey($contentHash)) {
            $positiveInWorkbook++
            $matchedDetail = [string]$workbookErrorDetails[$contentHash]
            if (-not $matchedWorkbookDetailedTypes.ContainsKey($matchedDetail)) { $matchedWorkbookDetailedTypes[$matchedDetail] = 0 }
            $matchedWorkbookDetailedTypes[$matchedDetail]++
            if ($matchedDetail -notmatch '音近|形近|同音') {
                $nonV4WorkbookTypePositive += [ordered]@{
                    merged_line = $index + 1
                    sample_id = $manifest.sample_id
                    workbook_detailed_type = $matchedDetail
                    source_file = $manifest.source_file
                    source_line = $manifest.source_line
                }
            }
        }
        if ($workbookCorrectHashes.ContainsKey($contentHash) -and -not $workbookErrorHashes.ContainsKey($contentHash)) {
            $positiveMatchingWorkbookCorrectOnly += [ordered]@{
                merged_line = $index + 1
                sample_id = $manifest.sample_id
                source_file = $manifest.source_file
                source_line = $manifest.source_line
            }
        }
    }
    else {
        $negative++
        if ($workbookCorrectHashes.ContainsKey($contentHash)) { $negativeInWorkbook++ }
        if ($workbookErrorHashes.ContainsKey($contentHash)) {
            $negativeMatchingWorkbookError += [ordered]@{
                merged_line = $index + 1
                sample_id = $manifest.sample_id
                source_file = $manifest.source_file
                source_line = $manifest.source_line
            }
        }
    }
}

$suspicious = @($disallowedPositive) + @($negativeMatchingWorkbookError) + @($positiveMatchingWorkbookCorrectOnly) + @($nonV4WorkbookTypePositive)
$writer = New-Object IO.StreamWriter($suspiciousPath, $false, $utf8NoBom)
try { foreach ($item in $suspicious) { $writer.WriteLine(($item | ConvertTo-Json -Compress)) } }
finally { $writer.Dispose() }

$report = [ordered]@{
    workbook = $workbookPath
    workbook_total = $workbookRows.Count
    workbook_positive = @($workbookRows | Where-Object { [int]$_.error_cnt -gt 0 }).Count
    workbook_negative = @($workbookRows | Where-Object { [int]$_.error_cnt -eq 0 }).Count
    workbook_positive_detailed_types = $workbookDetailedTypes
    train = $trainPath
    train_typo_total = $typoTotal
    train_positive = $positive
    train_negative = $negative
    strict_v4_positive = $strictPositive
    disallowed_positive = $disallowedPositive.Count
    negative_matching_workbook_error = $negativeMatchingWorkbookError.Count
    positive_matching_workbook_correct_only = $positiveMatchingWorkbookCorrectOnly.Count
    positive_found_in_workbook_error_set = $positiveInWorkbook
    matched_workbook_positive_detailed_types = $matchedWorkbookDetailedTypes
    non_v4_workbook_type_positive = $nonV4WorkbookTypePositive.Count
    negative_found_in_workbook_correct_set = $negativeInWorkbook
    replacement_required = ($suspicious.Count -gt 0)
    suspicious_file = $suspiciousPath
}
[IO.File]::WriteAllText($auditPath, ($report | ConvertTo-Json -Depth 20), $utf8NoBom)
$report | ConvertTo-Json -Depth 20 -Compress
