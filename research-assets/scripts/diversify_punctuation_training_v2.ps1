param(
    [string]$Training = 'C:\hyt-agent\训练集-微调版提示词\标点符号错误_训练集_v2.jsonl',
    [string]$TypeIndex = 'C:\hyt-agent\训练集-微调版提示词\标点符号错误_训练集_v2_错误类型索引.jsonl'
)

$ErrorActionPreference = 'Stop'
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$directory = Split-Path -Parent $Training
$backup = Join-Path $directory '标点符号错误_训练集_v2_造错丰富化前备份.jsonl'
$manifestPath = Join-Path $directory '标点符号错误_训练集_v2_造错丰富化清单.jsonl'
$reportPath = Join-Path $directory '标点符号错误_训练集_v2_造错丰富化校验报告.json'

function Get-Payload($record) {
    $content = [string]($record.messages | Where-Object role -eq 'user').content
    $start = $content.IndexOf('{')
    if ($start -lt 0) { throw 'Missing input payload.' }
    return $content.Substring($start) | ConvertFrom-Json
}

function Get-Answer($record) {
    return ([string]($record.messages | Where-Object role -eq 'assistant').content) | ConvertFrom-Json
}

function Replace-At([string]$text, [int]$position, [int]$length, [string]$replacement) {
    return $text.Substring(0, $position) + $replacement + $text.Substring($position + $length)
}

function Get-UniqueContext([string]$correctText, [string]$errorText, [int]$position, [int]$correctLength, [int]$errorLength) {
    $left = [Math]::Min(10, $position)
    $right = [Math]::Min(10, $correctText.Length - $position - $correctLength)
    $start = $position - $left
    while ($true) {
        $correctFragment = $correctText.Substring($start, $left + $correctLength + $right)
        $errorFragment = $errorText.Substring($start, $left + $errorLength + $right)
        if (([regex]::Matches($errorText, [regex]::Escape($errorFragment))).Count -eq 1) { break }
        if ($start -gt 0) { $start--; $left++ }
        elseif (($position + $correctLength + $right) -lt $correctText.Length) { $right++ }
        else { break }
    }
    return [pscustomobject]@{ Error = $errorFragment; Correct = $correctFragment }
}

function New-TrainingLine(
    [string]$systemPrompt,
    [string]$reference,
    [string]$errorText,
    [string]$errorFragment,
    [string]$correctFragment,
    [string]$reason,
    [string]$positionDescription
) {
    $answer = [ordered]@{
        reason = $reason
        has_error = $true
        total_errors = 1
        errors = @([ordered]@{
            error_type = '标点符号错误'
            position = $positionDescription
            original_text = $errorFragment
            anchor_text = $errorText
            correction = $correctFragment
            description = $reason
            suggestion = if ($correctFragment -eq '') {
                ('删除“{0}”。' -f $errorFragment)
            } else {
                ('将“{0}”改为“{1}”。' -f $errorFragment, $correctFragment)
            }
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

if (-not (Test-Path -LiteralPath $backup)) {
    Copy-Item -LiteralPath $Training -Destination $backup
}

# Always rebuild from the same pre-diversification snapshot so reruns are deterministic.
$lines = [System.IO.File]::ReadAllLines($backup, $utf8NoBom)
$records = @($lines | ForEach-Object { $_ | ConvertFrom-Json })
$newLines = [string[]]$lines.Clone()
$systemPrompt = [string]$records[0].messages[0].content

$typeByLine = @{}
foreach ($raw in [System.IO.File]::ReadAllLines($TypeIndex, $utf8NoBom)) {
    $row = $raw | ConvertFrom-Json
    $typeByLine[[int]$row.training_line] = [string]$row.error_subtype
}

# Recover the correct baseline for every record from its existing ground truth.
$sources = [System.Collections.Generic.List[object]]::new()
for ($index = 0; $index -lt $records.Count; $index++) {
    $record = $records[$index]
    $payload = Get-Payload $record
    $answer = Get-Answer $record
    $detection = [string]$payload.detection_content
    $correct = $detection
    $recoverable = $true
    if ($answer.has_error) {
        if ($answer.total_errors -ne 1 -or $answer.errors.Count -ne 1) { $recoverable = $false }
        else {
            $errorItem = $answer.errors[0]
            $fragment = [string]$errorItem.original_text
            if ($fragment -eq '') { $recoverable = $false }
            else {
                $position = $detection.IndexOf($fragment, [System.StringComparison]::Ordinal)
                if ($position -lt 0) { $recoverable = $false }
                else { $correct = Replace-At $detection $position $fragment.Length ([string]$errorItem.correction) }
            }
        }
    }
    $sources.Add([pscustomobject]@{
        Line = $index + 1
        Correct = $correct
        Reference = [string]$payload.reference
        IsNegative = -not [bool]$answer.has_error
        Recoverable = $recoverable
    })
}

$manifest = [System.Collections.Generic.List[object]]::new()
$usedSourceLines = [System.Collections.Generic.HashSet[int]]::new()

function Get-SourceCandidates([scriptblock]$predicate) {
    return @($sources |
        Where-Object {
            $_.Recoverable -and
            -not $usedSourceLines.Contains([int]$_.Line) -and
            $_.Correct.Length -ge 8 -and $_.Correct.Length -le 1000 -and
            $_.Correct -match '[\u4e00-\u9fff]' -and
            $_.Correct -notmatch '……|。。。' -and
            (& $predicate $_.Correct)
        } |
        Sort-Object @{ Expression = 'IsNegative'; Descending = $true }, @{ Expression = { $_.Correct.Length }; Ascending = $true }, Line)
}

function Commit-Mutation(
    [int]$hostLine,
    $source,
    [string]$mutation,
    [int]$position,
    [int]$correctLength,
    [string]$replacement,
    [string]$reason,
    [string]$positionDescription
) {
    $correctText = [string]$source.Correct
    $errorText = Replace-At $correctText $position $correctLength $replacement
    $context = Get-UniqueContext $correctText $errorText $position $correctLength $replacement.Length
    $newLines[$hostLine - 1] = New-TrainingLine $systemPrompt ([string]$source.Reference) $errorText $context.Error $context.Correct $reason $positionDescription
    $null = $usedSourceLines.Add([int]$source.Line)
    $manifest.Add([pscustomobject]@{
        training_line = $hostLine
        source_line = [int]$source.Line
        error_subtype = [string]$typeByLine[$hostLine]
        mutation = $mutation
        correct_content = $correctText
        detection_content = $errorText
        error_fragment = $context.Error
        correction_fragment = $context.Correct
        deterministic_reason = $reason
    })
}

$ellipsisTargets = @($typeByLine.Keys | Where-Object {
    $typeByLine[$_] -eq '省略号误用' -and (Get-Answer $records[$_ - 1]).reason -eq '题末误用连续三个句号代替规范的句末形式。'
} | Sort-Object)
if ($ellipsisTargets.Count -ne 141) { throw "Expected 141 repeated ellipsis rows, got $($ellipsisTargets.Count)." }
$ellipsisCursor = 0

function Add-MutationBatch([string]$name, [int]$count, [scriptblock]$predicate, [scriptblock]$locator, [string]$replacement, [string]$reason, [string]$positionDescription) {
    $candidates = @(Get-SourceCandidates $predicate | Select-Object -First $count)
    if ($candidates.Count -ne $count) { throw "Mutation $name requires $count candidates, found $($candidates.Count)." }
    foreach ($source in $candidates) {
        $location = & $locator ([string]$source.Correct)
        if ($null -eq $location -or [int]$location.Position -lt 0) { throw "Mutation $name locator failed on source line $($source.Line)." }
        $hostLineNumber = [int]$ellipsisTargets[$script:ellipsisCursor++]
        Commit-Mutation $hostLineNumber $source $name ([int]$location.Position) ([int]$location.Length) $replacement $reason $positionDescription
    }
}

# Scarce patterns are allocated first. Counts sum to 141.
$dengCandidates = [System.Collections.Generic.List[object]]::new()
foreach ($source in ($sources | Where-Object {
    $_.Recoverable -and $_.Correct.Length -ge 8 -and $_.Correct.Length -le 1000 -and
    $_.Correct -match '[\u4e00-\u9fff]' -and $_.Correct -notmatch '……|。。。'
} | Sort-Object @{ Expression = 'IsNegative'; Descending = $true }, @{ Expression = { $_.Correct.Length }; Ascending = $true }, Line)) {
    foreach ($match in @([regex]::Matches([string]$source.Correct, '等(?=[，。；])'))) {
        $prefixStart = [Math]::Max(0, $match.Index - 120)
        $prefix = ([string]$source.Correct).Substring($prefixStart, $match.Index - $prefixStart)
        if ($prefix.EndsWith('等') -or $prefix.Contains('、')) {
            $dengCandidates.Add([pscustomobject]@{ Source = $source; Position = $match.Index + 1; Replacement = '……' })
        }
    }
}
$dengCandidates = @($dengCandidates | Select-Object -First 10)
if ($dengCandidates.Count -ne 10) { throw "Mutation redundant_after_deng requires 10 source positions, found $($dengCandidates.Count)." }
# Two additional surface variants use a single ellipsis glyph on the first two
# baselines. They are different erroneous texts and do not create duplicates.
$dengCandidates += @($dengCandidates | Select-Object -First 2 | ForEach-Object {
    [pscustomobject]@{ Source = $_.Source; Position = $_.Position; Replacement = '…' }
})
foreach ($candidate in $dengCandidates) {
    $hostLineNumber = [int]$ellipsisTargets[$script:ellipsisCursor++]
    Commit-Mutation $hostLineNumber $candidate.Source 'redundant_after_deng' ([int]$candidate.Position) 1 ([string]$candidate.Replacement) '“等”已经表示列举未尽，后面的省略号又误替了句末或分句点号。' '题干中“等”后的省略号所在位置'
}

Add-MutationBatch 'colon_to_ellipsis' 18 {
    param($text) $text -match '：'
} {
    param($text) $m = [regex]::Match($text, '：'); [pscustomobject]@{ Position = $m.Index; Length = 1 }
} '……' '提示语后应使用冒号引出后文，不能使用表示内容省略的省略号。' '题干中提示语后的省略号所在位置'

Add-MutationBatch 'semicolon_to_ellipsis' 13 {
    param($text) $text -match '；'
} {
    param($text) $m = [regex]::Match($text, '；'); [pscustomobject]@{ Position = $m.Index; Length = 1 }
} '……' '并列分句之间需要分号表示层次，省略号不能替代分号。' '题干中并列分句之间的省略号所在位置'

Add-MutationBatch 'question_mark_to_ellipsis' 24 {
    param($text) $text -match '？\s*$'
} {
    param($text) $m = [regex]::Match($text, '？(?=\s*$)'); [pscustomobject]@{ Position = $m.Index; Length = 1 }
} '……' '题干是完整疑问句，句末应使用问号，不能用省略号代替。' '疑问句题干末尾'

$commandPattern = '^(请|试|简述|说明|分析|计算|证明|比较|论述|指出|列举|解释|阐述|概括|回答|讨论|设计|求解|推导|评价)'
Add-MutationBatch 'instruction_period_to_ellipsis' 20 {
    param($text) $text -match $commandPattern -and $text -match '。\s*$'
} {
    param($text) $m = [regex]::Match($text, '。(?=\s*$)'); [pscustomobject]@{ Position = $m.Index; Length = 1 }
} '……' '作答指令已经完整结束，句末应使用句号，不能误用表示语意未尽的省略号。' '作答指令句末'

Add-MutationBatch 'comma_to_ellipsis' 16 {
    param($text) $text -match '，' -and $text -notmatch '[“”]'
} {
    param($text) $m = [regex]::Match($text, '，'); [pscustomobject]@{ Position = $m.Index; Length = 1 }
} '……' '句内成分之间应使用逗号停顿，省略号会错误地表示内容省略或语意中断。' '题干句内停顿处'

Add-MutationBatch 'statement_period_to_ellipsis' 26 {
    param($text) $text -notmatch $commandPattern -and $text -match '。\s*$'
} {
    param($text) $m = [regex]::Match($text, '。(?=\s*$)'); [pscustomobject]@{ Position = $m.Index; Length = 1 }
} '……' '陈述内容已经完整结束，句末应使用句号，不能误用省略号。' '陈述句题干末尾'

Add-MutationBatch 'single_ellipsis_mark' 12 {
    param($text) $text -match '。\s*$'
} {
    param($text) $m = [regex]::Match($text, '。(?=\s*$)'); [pscustomobject]@{ Position = $m.Index; Length = 1 }
} '…' '完整陈述句末误用单个省略号符号，既不表示内容省略，也不能代替句号。' '完整陈述句句末'

if ($ellipsisCursor -ne 141) { throw "Only $ellipsisCursor ellipsis rows were rebuilt." }

# Replace the 55 rows that all quoted “简述” with diverse ordinary words.
$quoteTargets = @($typeByLine.Keys | Where-Object {
    if ($typeByLine[$_] -ne '引号滥用或缺失') { return $false }
    $answer = Get-Answer $records[$_ - 1]
    return $answer.has_error -and $answer.errors.Count -eq 1 -and [string]$answer.errors[0].correction -eq '简述'
} | Sort-Object)
if ($quoteTargets.Count -ne 55) { throw "Expected 55 repeated 简述 rows, got $($quoteTargets.Count)." }

$tokens = @(
    '概括','指出','列举','解释','阐述','判断','回答','讨论','设计','求解','推导','评价',
    '认识','理解','原因','特点','作用','方法','条件','关系','过程','影响','区别','意义',
    '内容','要求','依据','结合','根据','分别','主要','下列','正确','错误','是否'
)
$existingTokenCounts = @{}
foreach ($line in ($typeByLine.Keys | Where-Object { $typeByLine[$_] -eq '引号滥用或缺失' })) {
    if ($quoteTargets -contains [int]$line) { continue }
    $correction = [string](Get-Answer $records[$line - 1]).errors[0].correction
    if (-not $existingTokenCounts.ContainsKey($correction)) { $existingTokenCounts[$correction] = 0 }
    $existingTokenCounts[$correction]++
}
$newTokenCounts = @{}
$quoteSelections = [System.Collections.Generic.List[object]]::new()
for ($round = 1; $round -le 4 -and $quoteSelections.Count -lt 55; $round++) {
    foreach ($token in $tokens) {
        if ($quoteSelections.Count -ge 55) { break }
        $existing = if ($existingTokenCounts.ContainsKey($token)) { [int]$existingTokenCounts[$token] } else { 0 }
        $added = if ($newTokenCounts.ContainsKey($token)) { [int]$newTokenCounts[$token] } else { 0 }
        if ($added -ge 3 -or ($existing + $added) -ge 6) { continue }
        $candidate = @(Get-SourceCandidates {
            param($text)
            if ($text -match '[“”]' -or -not $text.Contains($token)) { return $false }
            $position = $text.IndexOf($token, [System.StringComparison]::Ordinal)
            if ($position -lt 0) { return $false }
            # Avoid quoted, titled, formula-heavy and blank-adjacent uses.
            return $text -notmatch '\$|《|》|_{3,}'
        } | Select-Object -First 1)
        if ($candidate.Count -eq 0) { continue }
        $source = $candidate[0]
        $quoteSelections.Add([pscustomobject]@{ Source = $source; Token = $token })
        $null = $usedSourceLines.Add([int]$source.Line)
        $newTokenCounts[$token] = $added + 1
    }
}
if ($quoteSelections.Count -ne 55) { throw "Only $($quoteSelections.Count) diverse quote candidates found." }

for ($slot = 0; $slot -lt $quoteSelections.Count; $slot++) {
    $selection = $quoteSelections[$slot]
    $source = $selection.Source
    $token = [string]$selection.Token
    $correctText = [string]$source.Correct
    $position = $correctText.IndexOf($token, [System.StringComparison]::Ordinal)
    $replacement = '“' + $token + '”'
    $errorText = Replace-At $correctText $position $token.Length $replacement
    $context = Get-UniqueContext $correctText $errorText $position $token.Length $replacement.Length
    $hostLineNumber = [int]$quoteTargets[$slot]
    $reason = ('题干中的“{0}”是普通表述，不是引语、专名或需要特殊标示的词语，不应使用引号。' -f $token)
    $newLines[$hostLineNumber - 1] = New-TrainingLine $systemPrompt ([string]$source.Reference) $errorText $context.Error $context.Correct $reason ('题干中普通词语“{0}”所在位置' -f $token)
    $manifest.Add([pscustomobject]@{
        training_line = $hostLineNumber
        source_line = [int]$source.Line
        error_subtype = '引号滥用或缺失'
        mutation = 'diverse_unnecessary_quote'
        token = $token
        correct_content = $correctText
        detection_content = $errorText
        error_fragment = $context.Error
        correction_fragment = $context.Correct
        deterministic_reason = $reason
    })
}

[System.IO.File]::WriteAllLines($Training, $newLines, $utf8NoBom)
[System.IO.File]::WriteAllLines($manifestPath, @($manifest | ForEach-Object { $_ | ConvertTo-Json -Compress -Depth 8 }), $utf8NoBom)

# Structural, round-trip and diversity validation.
$outputRecords = @([System.IO.File]::ReadAllLines($Training, $utf8NoBom) | ForEach-Object { $_ | ConvertFrom-Json })
$invalid = 0
$failedRoundTrip = [System.Collections.Generic.List[int]]::new()
$detections = [System.Collections.Generic.List[string]]::new()
$positive = 0; $negative = 0
for ($index = 0; $index -lt $outputRecords.Count; $index++) {
    $record = $outputRecords[$index]
    try { $answer = Get-Answer $record } catch { $invalid++; continue }
    if ($answer.has_error) { $positive++ } else { $negative++ }
    if ([int]$answer.total_errors -ne @($answer.errors).Count) { $invalid++ }
    $detections.Add([string](Get-Payload $record).detection_content)
}
foreach ($row in $manifest) {
    $errorText = [string]$row.detection_content
    $fragment = [string]$row.error_fragment
    $position = $errorText.IndexOf($fragment, [System.StringComparison]::Ordinal)
    if ($position -lt 0) { $failedRoundTrip.Add([int]$row.training_line); continue }
    $fixed = Replace-At $errorText $position $fragment.Length ([string]$row.correction_fragment)
    if ($fixed -ne [string]$row.correct_content) { $failedRoundTrip.Add([int]$row.training_line) }
}

$finalQuoteCorrections = foreach ($line in ($typeByLine.Keys | Where-Object { $typeByLine[$_] -eq '引号滥用或缺失' })) {
    [string](Get-Answer $outputRecords[$line - 1]).errors[0].correction
}
$report = [ordered]@{
    generated_at = (Get-Date).ToString('s')
    training_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Training).Hash
    total_records = $outputRecords.Count
    positive_records = $positive
    negative_records = $negative
    changed_records = $manifest.Count
    changed_ellipsis_records = @($manifest | Where-Object error_subtype -eq '省略号误用').Count
    changed_quote_records = @($manifest | Where-Object error_subtype -eq '引号滥用或缺失').Count
    remaining_triple_period_records = @($outputRecords | Where-Object { (Get-Payload $_).detection_content -match '。。。' }).Count
    remaining_quote_correction_简述 = @($finalQuoteCorrections | Where-Object { $_ -eq '简述' }).Count
    quote_correction_top_counts = @($finalQuoteCorrections | Group-Object | Sort-Object Count -Descending | Select-Object -First 15 @{n='token';e={$_.Name}}, Count)
    ellipsis_mutation_counts = @($manifest | Where-Object error_subtype -eq '省略号误用' | Group-Object mutation | Sort-Object Name | Select-Object @{n='mutation';e={$_.Name}}, Count)
    invalid_answers = $invalid
    failed_round_trip_records = $failedRoundTrip.Count
    duplicate_detection_groups = @($detections | Group-Object | Where-Object Count -gt 1).Count
}
$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportPath -Encoding UTF8

if ($outputRecords.Count -ne 1061 -or $positive -ne 580 -or $negative -ne 481 -or $manifest.Count -ne 196 -or $invalid -ne 0 -or $failedRoundTrip.Count -ne 0 -or $report.remaining_triple_period_records -ne 1 -or $report.remaining_quote_correction_简述 -ne 0 -or $report.duplicate_detection_groups -ne 0) {
    throw 'Diversification validation failed.'
}

$report | ConvertTo-Json -Depth 8
