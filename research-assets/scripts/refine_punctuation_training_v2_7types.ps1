param(
    [string]$OriginalTraining = 'C:\hyt-agent\训练集-微调版提示词\标点符号错误_训练集.jsonl',
    [string]$CurrentV2 = 'C:\hyt-agent\训练集-微调版提示词\标点符号错误_训练集_v2.jsonl',
    [string]$SourceWorkbook = 'C:\hyt-agent\数据集\完整数据集标点符号.xlsx'
)

$ErrorActionPreference = 'Stop'
$outputDirectory = Split-Path -Parent $CurrentV2
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)

function Get-Payload($record) {
    $content = [string]$record.messages[1].content
    $start = $content.IndexOf('{')
    if ($start -lt 0) { throw 'Missing input payload.' }
    return $content.Substring($start) | ConvertFrom-Json
}

function Replace-First([string]$text, [string]$find, [string]$replace) {
    $position = $text.IndexOf($find, [System.StringComparison]::Ordinal)
    if ($position -lt 0) { throw "Fragment not found: $find" }
    return $text.Substring(0, $position) + $replace + $text.Substring($position + $find.Length)
}

function New-TrainingLine([string]$systemPrompt, [string]$reference, [string]$errorText, [string]$errorFragment, [string]$correctFragment, [string]$reason) {
    $answer = [ordered]@{
        reason = $reason
        has_error = $true
        total_errors = 1
        errors = @([ordered]@{
            error_type = '标点符号错误'
            position = ('题干中“{0}”所在位置' -f $errorFragment)
            original_text = $errorFragment
            anchor_text = $errorText
            correction = $correctFragment
            description = $reason
            suggestion = if ($correctFragment -eq '') { ('删除题干中的“{0}”。' -f $errorFragment) } else { ('将“{0}”改为“{1}”。' -f $errorFragment, $correctFragment) }
        })
    }
    $payload = [ordered]@{ reference = $reference; detection_content = $errorText }
    $record = [ordered]@{
        messages = @(
            [ordered]@{ role = 'system'; content = $systemPrompt }
            [ordered]@{ role = 'user'; content = "[INPUT_PAYLOAD]`n$($payload | ConvertTo-Json -Compress -Depth 8)" }
            [ordered]@{ role = 'assistant'; content = ($answer | ConvertTo-Json -Compress -Depth 8) }
        )
    }
    return $record | ConvertTo-Json -Compress -Depth 12
}

function Get-UniqueContext([string]$correctText, [string]$errorText, [int]$correctPosition, [int]$correctLength, [int]$errorLength) {
    $left = [Math]::Min(8, $correctPosition)
    $right = [Math]::Min(8, $correctText.Length - $correctPosition - $correctLength)
    $start = $correctPosition - $left
    do {
        $correctFragment = $correctText.Substring($start, $left + $correctLength + $right)
        $errorFragment = $errorText.Substring($start, $left + $errorLength + $right)
        $count = ([regex]::Matches($errorText, [regex]::Escape($errorFragment))).Count
        if ($count -eq 1) { break }
        if ($start -gt 0) { $start--; $left++ }
        elseif (($correctPosition + $correctLength + $right) -lt $correctText.Length) { $right++ }
        else { break }
    } while ($true)
    return [pscustomobject]@{ Error = $errorFragment; Correct = $correctFragment }
}

$originalHashBefore = (Get-FileHash -Algorithm SHA256 -LiteralPath $OriginalTraining).Hash
$originalLines = [System.IO.File]::ReadAllLines($OriginalTraining, $utf8NoBom)
$originalRecords = @($originalLines | ForEach-Object { $_ | ConvertFrom-Json })
$currentLines = [System.IO.File]::ReadAllLines($CurrentV2, $utf8NoBom)
$currentRecords = @($currentLines | ForEach-Object { $_ | ConvertFrom-Json })
$newLines = [string[]]$currentLines.Clone()
$systemPrompt = [string]$originalRecords[0].messages[0].content

$readerScript = Get-Content -LiteralPath 'C:\hyt-agent\scripts\restore_punctuation_126.ps1' -Raw -Encoding UTF8
Invoke-Expression $readerScript.Substring(0, $readerScript.IndexOf('$decisions ='))
$sourceRows = @(Read-XlsxRows $SourceWorkbook)
$outputDirectory = Split-Path -Parent $CurrentV2

$oldConversionPath = Join-Path $outputDirectory '标点符号错误_训练集_v2_均衡改造清单.jsonl'
$oldConversion = @([System.IO.File]::ReadAllLines($oldConversionPath, $utf8NoBom) | ForEach-Object { $_ | ConvertFrom-Json })
$recoveryIndexPath = Join-Path $outputDirectory '标点符号错误_训练集_v2_保留恢复题清单.jsonl'
$recoveryIndex = @([System.IO.File]::ReadAllLines($recoveryIndexPath, $utf8NoBom) | ForEach-Object { $_ | ConvertFrom-Json })
$recoveredManifestPath = 'C:\hyt-agent\outputs\punctuation_restore_126_20260826\punctuation_recovered_126.jsonl'
$recoveredManifest = @([System.IO.File]::ReadAllLines($recoveredManifestPath, $utf8NoBom) | ForEach-Object { $_ | ConvertFrom-Json })
$recoveredById = @{}
foreach ($row in $recoveredManifest) { $recoveredById[[string]$row.recovery_id] = $row }

$oldConversionByLine = @{}
foreach ($row in $oldConversion) { $oldConversionByLine[[int]$row.training_line] = $row }
$recoveryByLine = @{}
foreach ($row in $recoveryIndex) { $recoveryByLine[[int]$row.training_line] = $row }

# Build a complete positive-row subtype index for the current 11-type v2.
$typeByLine = @{}
foreach ($row in $sourceRows) {
    if ($row.Values.is_real_error -eq '1') { $typeByLine[[int]$row.ExcelRow - 1] = [string]$row.Values.error_detailed_type }
}
foreach ($row in $recoveryIndex) { $typeByLine[[int]$row.training_line] = [string]$row.error_subtype }
foreach ($row in $oldConversion) { $typeByLine[[int]$row.training_line] = [string]$row.error_subtype }

$quotePositionLines = @($typeByLine.Keys | Where-Object { $typeByLine[$_] -eq '引号内外标点位置' } | Sort-Object)
if ($quotePositionLines.Count -ne 118) { throw "Expected 118 quote-position rows, got $($quotePositionLines.Count)." }

# Only recovered rows where the correct and erroneous forms contain the same
# number of quote marks are retained as clean single-error quote-position items.
$validRecoveredQuoteLines = [System.Collections.Generic.List[int]]::new()
$invalidQuoteLines = [System.Collections.Generic.List[int]]::new()
foreach ($line in $quotePositionLines) {
    if ($recoveryByLine.ContainsKey([int]$line)) {
        $manifestRow = $recoveredById[[string]$recoveryByLine[[int]$line].recovery_id]
        $correctQuoteCount = ([regex]::Matches([string]$manifestRow.original_question, '[“”]')).Count
        $errorQuoteCount = ([regex]::Matches([string]$manifestRow.error_question, '[“”]')).Count
        if ($correctQuoteCount -eq $errorQuoteCount) { $validRecoveredQuoteLines.Add([int]$line); continue }
    }
    $invalidQuoteLines.Add([int]$line)
}
if ($validRecoveredQuoteLines.Count -ne 15 -or $invalidQuoteLines.Count -ne 103) {
    throw 'Unexpected clean/invalid quote-position split.'
}

# Collect real questions that already use a legitimate paired quote followed by
# punctuation. The only mutation is moving that existing punctuation inside.
$quotePattern = '“(?<term>[^”。？！；，]{1,40})”(?<punct>[，。？！])'
$quoteSources = [System.Collections.Generic.List[object]]::new()
for ($index = 0; $index -lt $sourceRows.Count; $index++) {
    $text = [string]$sourceRows[$index].Values.content
    if ($text -notmatch $quotePattern) { continue }
    $reference = [string](Get-Payload $originalRecords[$index]).reference
    $quoteSources.Add([pscustomobject]@{ Key = "main:$($sourceRows[$index].Values.id)"; Text = $text; Reference = $reference; Source = $sourceRows[$index].Values.file_name })
}

$rawFiles = Get-ChildItem -LiteralPath 'C:\hyt-agent\外部数据源\研招真题' -Recurse -File -Filter 'detection_raw_results.xlsx'
foreach ($file in $rawFiles) {
    foreach ($row in @(Read-XlsxRows $file.FullName)) {
        $prompt = [string]$row.Values.prompt
        $userPosition = $prompt.LastIndexOf('[USER]')
        if ($userPosition -lt 0) { continue }
        try { $payload = $prompt.Substring($userPosition + 6).Trim() | ConvertFrom-Json } catch { continue }
        $text = [string]$payload.detection_content
        if ($text -notmatch $quotePattern) { continue }
        $reference = "【学科】外部真实题源`n【试卷标题】# $($file.Directory.Name)`n【题型或其它信息】$([string]$payload.reference)"
        $quoteSources.Add([pscustomobject]@{ Key = "external:$($file.FullName):$($row.ExcelRow)"; Text = $text; Reference = $reference; Source = $file.FullName })
    }
}
$uniqueQuoteSources = @($quoteSources | Sort-Object { $_.Text.Length }, Key | Group-Object Text | ForEach-Object { $_.Group[0] })
if ($uniqueQuoteSources.Count -lt 25) { throw "Only $($uniqueQuoteSources.Count) clean quote sources found." }
$selectedQuoteSources = @($uniqueQuoteSources | Select-Object -First 25)

$changeLog = [System.Collections.Generic.List[object]]::new()
$newQuoteHostLines = @($invalidQuoteLines | Select-Object -First 25)
for ($slot = 0; $slot -lt 25; $slot++) {
    $line = [int]$newQuoteHostLines[$slot]
    $source = $selectedQuoteSources[$slot]
    $correctText = [string]$source.Text
    $match = [regex]::Match($correctText, $quotePattern)
    $term = $match.Groups['term'].Value
    $punct = $match.Groups['punct'].Value
    $correctFragment = $match.Value
    $errorFragment = '“' + $term + $punct + '”'
    $errorText = $correctText.Substring(0, $match.Index) + $errorFragment + $correctText.Substring($match.Index + $match.Length)
    $reason = ('“{0}”是原题中合理标示的词语，后面的“{1}”不属于引号内容，应置于后引号外。' -f $term, $punct)
    $newLines[$line - 1] = New-TrainingLine $systemPrompt ([string]$source.Reference) $errorText $errorFragment $correctFragment $reason
    $typeByLine[$line] = '引号内外标点位置'
    $changeLog.Add([pscustomobject]@{ training_line = $line; action = 'clean_quote_position_replacement'; error_subtype = '引号内外标点位置'; source = $source.Source; correct_content = $correctText; detection_content = $errorText; error_fragment = $errorFragment; correction_fragment = $correctFragment; reason = $reason })
}

# The remaining 78 invalid quote-position rows plus the 18 rows in categories
# after item 7 are converted into four retained categories, 24 rows each.
$redistributionLines = [System.Collections.Generic.List[int]]::new()
foreach ($line in ($invalidQuoteLines | Select-Object -Skip 25)) { $redistributionLines.Add([int]$line) }
foreach ($line in ($typeByLine.Keys | Where-Object { $typeByLine[$_] -in @('标点冗余或缺失','选项与编号标点误用','间隔号误用','停顿符号误用') } | Sort-Object)) {
    if (-not $redistributionLines.Contains([int]$line)) { $redistributionLines.Add([int]$line) }
}
if ($redistributionLines.Count -ne 96) { throw "Expected 96 redistribution rows, got $($redistributionLines.Count)." }

$correctByLine = @{}
foreach ($line in $redistributionLines) {
    if ($recoveryByLine.ContainsKey($line)) {
        $correctByLine[$line] = [string]$recoveredById[[string]$recoveryByLine[$line].recovery_id].original_question
    } elseif ($oldConversionByLine.ContainsKey($line)) {
        $correctByLine[$line] = [string]$oldConversionByLine[$line].correct_content
    } else {
        $correctByLine[$line] = [string]$sourceRows[$line - 1].Values.content
    }
}

$available = [System.Collections.Generic.HashSet[int]]::new()
foreach ($line in $redistributionLines) { $null = $available.Add([int]$line) }

function Commit-ConvertedLine([int]$line, [string]$subtype, [string]$correctText, [string]$errorText, [string]$errorFragment, [string]$correctFragment, [string]$reason) {
    if (-not $available.Remove($line)) { throw "Line $line is unavailable." }
    $reference = [string](Get-Payload $currentRecords[$line - 1]).reference
    $newLines[$line - 1] = New-TrainingLine $systemPrompt $reference $errorText $errorFragment $correctFragment $reason
    $typeByLine[$line] = $subtype
    $changeLog.Add([pscustomobject]@{ training_line = $line; action = 'redistributed'; error_subtype = $subtype; source = 'existing_question'; correct_content = $correctText; detection_content = $errorText; error_fragment = $errorFragment; correction_fragment = $correctFragment; reason = $reason })
}

# Add 24 connector-line errors.
$dashCandidates = [System.Collections.Generic.List[object]]::new()
foreach ($line in ($available | Sort-Object)) {
    $text = [string]$correctByLine[$line]
    $find = $null
    if ($text.Contains('以及')) { $find = '以及' }
    elseif ($text.Contains('与')) { $find = '与' }
    elseif ($text.Contains('和') -and $text -notmatch '共和国|和平|和谐|饱和|调和|总和|之和|和解|和弦|和声|亲和|中和|缓和|温和') { $find = '和' }
    elseif ($text.Contains('及其')) { $find = '及' }
    if ($null -ne $find) { $dashCandidates.Add([pscustomobject]@{ Line = $line; Find = $find }) }
    if ($dashCandidates.Count -eq 24) { break }
}
if ($dashCandidates.Count -ne 24) { throw "Only $($dashCandidates.Count) dash candidates found." }
foreach ($candidate in $dashCandidates) {
    $line = [int]$candidate.Line
    $find = [string]$candidate.Find
    $correctText = [string]$correctByLine[$line]
    $position = $correctText.IndexOf($find, [System.StringComparison]::Ordinal)
    $errorText = Replace-First $correctText $find '-'
    $context = Get-UniqueContext $correctText $errorText $position $find.Length 1
    Commit-ConvertedLine $line '破折号、连接号误用' $correctText $errorText $context.Error $context.Correct ('并列成分之间的连词“{0}”误写为连接号。' -f $find)
}

# Add 24 unnecessary-quote errors around ordinary task wording.
$taskTokens = @('请简述','请说明','请分析','请论述','试论述','试分析','试说明','什么是','为什么','简述','论述','说明','分析','比较','指出','计算','证明','列举','解释','阐述','试述','谈谈','如何','何为','何谓','哪些','有何')
$quoteAbuseCandidates = [System.Collections.Generic.List[object]]::new()
foreach ($line in ($available | Sort-Object)) {
    $text = [string]$correctByLine[$line]
    foreach ($token in $taskTokens) {
        $position = $text.IndexOf($token, [System.StringComparison]::Ordinal)
        if ($position -lt 0) { continue }
        $quoteAbuseCandidates.Add([pscustomobject]@{ Line = $line; Find = $token })
        break
    }
    if ($quoteAbuseCandidates.Count -eq 24) { break }
}
if ($quoteAbuseCandidates.Count -ne 24) { throw "Only $($quoteAbuseCandidates.Count) quote-abuse candidates found." }
foreach ($candidate in $quoteAbuseCandidates) {
    $line = [int]$candidate.Line
    $find = [string]$candidate.Find
    $correctText = [string]$correctByLine[$line]
    $errorFragment = '“' + $find + '”'
    $errorText = Replace-First $correctText $find $errorFragment
    Commit-ConvertedLine $line '引号滥用或缺失' $correctText $errorText $errorFragment $find ('普通题干用语“{0}”无需使用引号。' -f $find)
}

# Add 24 sentence-final punctuation errors.
$sentenceCandidates = @($available | Sort-Object | Select-Object -First 24)
foreach ($line in $sentenceCandidates) {
    $correctText = [string]$correctByLine[$line]
    $match = [regex]::Match($correctText, '(?<punct>[。？！])(?<space>\s*)$')
    if ($match.Success) {
        $position = $match.Index
        $errorText = $correctText.Substring(0, $position) + '，' + $match.Groups['space'].Value
        $context = Get-UniqueContext $correctText $errorText $position 1 1
        $errorFragment = $context.Error
        $correctFragment = $context.Correct
    } else {
        $trimmed = $correctText.TrimEnd()
        $errorText = $trimmed + '，' + $correctText.Substring($trimmed.Length)
        $errorFragment = '，'
        $correctFragment = ''
    }
    Commit-ConvertedLine $line '句末点号误用' $correctText $errorText $errorFragment $correctFragment '完整题干末尾误用逗号，不能正确收束句子。'
}

# The final 24 rows become pseudo-ellipsis errors.
$ellipsisCandidates = @($available | Sort-Object)
if ($ellipsisCandidates.Count -ne 24) { throw "Expected 24 ellipsis candidates, got $($ellipsisCandidates.Count)." }
foreach ($line in $ellipsisCandidates) {
    $correctText = [string]$correctByLine[$line]
    $match = [regex]::Match($correctText, '(?<punct>[。？！])(?<space>\s*)$')
    if ($match.Success) {
        $errorText = $correctText.Substring(0, $match.Index) + '。。。' + $match.Groups['space'].Value
        $correctFragment = $match.Groups['punct'].Value
    } else {
        $trimmed = $correctText.TrimEnd()
        $errorText = $trimmed + '。。。' + $correctText.Substring($trimmed.Length)
        $correctFragment = ''
    }
    Commit-ConvertedLine $line '省略号误用' $correctText $errorText '。。。' $correctFragment '题末误用连续三个句号代替规范的句末形式。'
}

if ($available.Count -ne 0) { throw 'Redistribution did not consume every target row.' }

$backupPath = Join-Path $outputDirectory '标点符号错误_训练集_v2_11类均衡版备份.jsonl'
if (-not (Test-Path -LiteralPath $backupPath)) { Copy-Item -LiteralPath $CurrentV2 -Destination $backupPath }
[System.IO.File]::WriteAllLines($CurrentV2, $newLines, $utf8NoBom)

# Validate the resulting training file and derive the distribution from the
# per-line subtype index rather than trusting hard-coded totals.
$outputRecords = @([System.IO.File]::ReadAllLines($CurrentV2, $utf8NoBom) | ForEach-Object { $_ | ConvertFrom-Json })
$positive = 0; $negative = 0; $invalidAnswers = 0; $wrongSystem = 0
$detections = [System.Collections.Generic.List[string]]::new()
foreach ($record in $outputRecords) {
    if ([string]$record.messages[0].content -ne $systemPrompt) { $wrongSystem++ }
    try { $answer = $record.messages[2].content | ConvertFrom-Json } catch { $invalidAnswers++; continue }
    if ($answer.has_error) { $positive++ } else { $negative++ }
    if ($answer.total_errors -ne $answer.errors.Count) { $invalidAnswers++ }
    $detections.Add([string](Get-Payload $record).detection_content)
}

$distribution = [ordered]@{}
foreach ($group in ($typeByLine.GetEnumerator() | Group-Object Value | Sort-Object Count -Descending)) { $distribution[[string]$group.Name] = $group.Count }
$targetDistribution = [ordered]@{
    '引号滥用或缺失' = 142
    '省略号误用' = 142
    '句末点号误用' = 127
    '破折号、连接号误用' = 98
    '引号内外标点位置' = 40
    '冒号、分号误用' = 16
    '引号、括号、书名号等配对错误' = 15
}
$distributionMismatch = @($targetDistribution.Keys | Where-Object { -not $distribution.Contains($_) -or [int]$distribution[$_] -ne [int]$targetDistribution[$_] }).Count -gt 0 -or $distribution.Count -ne $targetDistribution.Count
if ($distributionMismatch) { throw "Distribution mismatch: $($distribution | ConvertTo-Json -Compress)" }

$badRoundTrip = [System.Collections.Generic.List[int]]::new()
foreach ($row in $changeLog) {
    $text = [string]$row.detection_content
    $find = [string]$row.error_fragment
    $position = $text.IndexOf($find, [System.StringComparison]::Ordinal)
    if ($position -lt 0) { $badRoundTrip.Add([int]$row.training_line); continue }
    $fixed = $text.Substring(0, $position) + [string]$row.correction_fragment + $text.Substring($position + $find.Length)
    if ($fixed -ne [string]$row.correct_content) { $badRoundTrip.Add([int]$row.training_line) }
}

$changeLogPath = Join-Path $outputDirectory '标点符号错误_训练集_v2_七类改造清单.jsonl'
[System.IO.File]::WriteAllLines($changeLogPath, @($changeLog | ForEach-Object { $_ | ConvertTo-Json -Compress -Depth 8 }), $utf8NoBom)
$typeIndexPath = Join-Path $outputDirectory '标点符号错误_训练集_v2_错误类型索引.jsonl'
$typeIndexLines = @($typeByLine.GetEnumerator() | Sort-Object Name | ForEach-Object { ([ordered]@{ training_line = [int]$_.Name; error_subtype = [string]$_.Value } | ConvertTo-Json -Compress) })
[System.IO.File]::WriteAllLines($typeIndexPath, $typeIndexLines, $utf8NoBom)

$originalHashAfter = (Get-FileHash -Algorithm SHA256 -LiteralPath $OriginalTraining).Hash
$verification = [ordered]@{
    generated_at = (Get-Date).ToString('s')
    original_unchanged = ($originalHashBefore -eq $originalHashAfter)
    original_sha256 = $originalHashAfter
    output_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $CurrentV2).Hash
    total_records = $outputRecords.Count
    positive_records = $positive
    negative_records = $negative
    clean_quote_position_records = 40
    retained_clean_recovered_quote_position_records = $validRecoveredQuoteLines.Count
    new_clean_quote_position_records = $selectedQuoteSources.Count
    removed_post_item_7_records = 18
    redistributed_records = 96
    invalid_answers = $invalidAnswers
    wrong_system_prompt = $wrongSystem
    duplicate_detection_groups = @($detections | Group-Object | Where-Object Count -gt 1).Count
    failed_round_trip_records = $badRoundTrip.Count
    distribution = $distribution
}
$verificationPath = Join-Path $outputDirectory '标点符号错误_训练集_v2_七类校验报告.json'
$verification | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $verificationPath -Encoding UTF8

if (-not $verification.original_unchanged -or $outputRecords.Count -ne 1061 -or $positive -ne 580 -or $negative -ne 481 -or $invalidAnswers -ne 0 -or $wrongSystem -ne 0 -or $badRoundTrip.Count -ne 0) {
    throw 'Final validation failed.'
}
$verification | ConvertTo-Json -Depth 8
