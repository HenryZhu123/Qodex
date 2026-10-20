param(
    [string]$Training = 'C:\hyt-agent\训练集-微调版提示词\标点符号错误_训练集_v2.jsonl',
    [string]$Manifest = 'C:\hyt-agent\训练集-微调版提示词\标点符号错误_训练集_v2_造错丰富化清单.jsonl',
    [string]$QwenResults = 'C:\hyt-agent\训练集-微调版提示词\标点符号错误_训练集_v2_造错丰富化_Qwen标准答案.jsonl',
    [string]$QwenAudit = 'C:\hyt-agent\训练集-微调版提示词\标点符号错误_训练集_v2_Qwen141审核明细.jsonl'
)

$ErrorActionPreference = 'Stop'
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$directory = Split-Path -Parent $Training
$backup = Join-Path $directory '标点符号错误_训练集_v2_混合答案写回前备份.jsonl'
$originPath = Join-Path $directory '标点符号错误_训练集_v2_标准答案来源清单.jsonl'
$reportPath = Join-Path $directory '标点符号错误_训练集_v2_标准答案写回校验报告.json'

function Get-Payload($record) {
    $content = [string]($record.messages | Where-Object role -eq 'user').content
    return $content.Substring($content.IndexOf('{')) | ConvertFrom-Json
}

function Get-MinimalDiff([string]$correct, [string]$errorText) {
    $prefix = 0
    $limit = [Math]::Min($correct.Length, $errorText.Length)
    while ($prefix -lt $limit -and $correct[$prefix] -eq $errorText[$prefix]) { $prefix++ }
    $correctEnd = $correct.Length - 1
    $errorEnd = $errorText.Length - 1
    while ($correctEnd -ge $prefix -and $errorEnd -ge $prefix -and $correct[$correctEnd] -eq $errorText[$errorEnd]) {
        $correctEnd--; $errorEnd--
    }
    $original = if ($errorEnd -ge $prefix) { $errorText.Substring($prefix, $errorEnd - $prefix + 1) } else { '' }
    $correction = if ($correctEnd -ge $prefix) { $correct.Substring($prefix, $correctEnd - $prefix + 1) } else { '' }
    return [pscustomobject]@{ Position = $prefix; Original = $original; Correction = $correction }
}

function Get-UniqueAnchor([string]$text, [int]$position, [int]$length) {
    $left = [Math]::Min(12, $position)
    $right = [Math]::Min(12, $text.Length - $position - $length)
    $start = $position - $left
    while ($true) {
        $anchor = $text.Substring($start, $left + $length + $right)
        if (([regex]::Matches($text, [regex]::Escape($anchor))).Count -eq 1) { return $anchor }
        if ($start -gt 0) { $start--; $left++ }
        elseif (($position + $length + $right) -lt $text.Length) { $right++ }
        else { return $text }
    }
}

function Clip([string]$text, [int]$maximum) {
    $clean = ($text -replace '\s+', ' ').Trim()
    if ($clean.Length -le $maximum) { return $clean }
    return $clean.Substring(0, $maximum)
}

function New-CodexAnswer($row) {
    $errorText = [string]$row.detection_content
    $correctText = [string]$row.correct_content
    $diff = Get-MinimalDiff $correctText $errorText
    if ($diff.Original -eq $diff.Correction) { throw "Line $($row.training_line) has no usable diff." }
    $anchor = Get-UniqueAnchor $errorText $diff.Position $diff.Original.Length
    $leftStart = [Math]::Max(0, $diff.Position - 22)
    $left = Clip ($errorText.Substring($leftStart, $diff.Position - $leftStart)) 22
    $rightStart = $diff.Position + $diff.Original.Length
    $rightLength = [Math]::Min(22, $errorText.Length - $rightStart)
    $right = Clip ($errorText.Substring($rightStart, $rightLength)) 22
    $focus = Clip $anchor 26
    $originalShown = if ($diff.Original -eq '') { '缺失位置' } else { $diff.Original }
    $correctionShown = if ($diff.Correction -eq '') { '删除该标点' } else { $diff.Correction }

    switch ([string]$row.mutation) {
        'diverse_unnecessary_quote' {
            $token = [string]$row.token
            $reason = ('题干把普通词语「{0}」无依据地置于引号内。' -f $token)
            $positionText = ('题干中普通词语「{0}」所在位置' -f $token)
            $description = ('在「{0}」这一语境中，「{1}」既非引语、专名或术语，也没有反语或特殊含义；引号会制造不必要的强调。' -f $focus, $token)
            $suggestion = ('去掉「{0}」两侧的引号，保留原有词语和句子结构。' -f $token)
        }
        'colon_to_ellipsis' {
            $reason = ('「{0}」后需引出后文，省略号误替了冒号。' -f $left)
            $positionText = ('「{0}」与后续内容的衔接处' -f $left)
            $description = ('后文「{0}」是前面提示、说明或证明要求直接引出的内容，这里没有文字被省略，应使用冒号建立提示关系。' -f $right)
            $suggestion = ('将该处「{0}」改为「{1}」，明确前后提示层级。' -f $originalShown, $correctionShown)
        }
        'comma_to_ellipsis' {
            $reason = ('「{0}」与「{1}」之间误用了省略号。' -f $left, $right)
            $positionText = ('题干中「{0}」之后的句内停顿处' -f $left)
            $description = ('前后成分在句法和语义上连续，没有省略、迟疑或中断关系；此处需要用「{0}」表示正常停顿。' -f $diff.Correction)
            $suggestion = ('把连接「{0}」和「{1}」的「{2}」改为「{3}」。' -f $left, $right, $originalShown, $correctionShown)
        }
        'semicolon_to_ellipsis' {
            $reason = ('并列内容「{0}」之后的省略号破坏了分项层级。' -f $left)
            $positionText = ('并列分项「{0}」之后' -f $left)
            $description = ('后续「{0}」与前项处于同一并列层级，原文没有省略内容；应恢复「{1}」作为分项或分句界标。' -f $right, $diff.Correction)
            $suggestion = ('将两项之间的「{0}」替换为「{1}」。' -f $originalShown, $correctionShown)
        }
        'question_mark_to_ellipsis' {
            $reason = ('题干「{0}」构成完整疑问，句末不能使用省略号。' -f $left)
            $positionText = '完整疑问句题干末尾'
            $description = ('该题要求作答一个明确问题，疑问语气在「{0}」处结束，不存在话语中断或内容省略，应以问号收束。' -f $focus)
            $suggestion = ('把题干末尾的「{0}」改为「{1}」。' -f $originalShown, $correctionShown)
        }
        'instruction_period_to_ellipsis' {
            $reason = ('作答指令「{0}」已经完整，句末省略号使用不当。' -f $left)
            $positionText = '完整作答指令句末'
            $description = ('「{0}」给出了完整的作答任务，没有列举省略或语意未尽；应使用句号结束指令。' -f $focus)
            $suggestion = ('将指令末尾的「{0}」改为「{1}」。' -f $originalShown, $correctionShown)
        }
        'statement_period_to_ellipsis' {
            $reason = ('知识性陈述「{0}」已经结束，句末误用了省略号。' -f $left)
            $positionText = '完整陈述句题干末尾'
            $description = ('「{0}」表达完整判断，并无省略、迟疑或话语中断；省略号会错误地暗示内容未完。' -f $focus)
            $suggestion = ('用「{0}」替换句末「{1}」，正常收束陈述。' -f $correctionShown, $originalShown)
        }
        'single_ellipsis_mark' {
            $reason = ('「{0}」句末的单个省略号符号不能代替句号。' -f $left)
            $positionText = '完整陈述句题干末尾'
            $description = ('该句内容在「{0}」处完整结束，既不需要省略含义，单个「…」也不符合省略号的成对形式；此处应恢复句号。' -f $focus)
            $suggestion = ('将句末单个「…」改为「{0}」。' -f $correctionShown)
        }
        'redundant_after_deng' {
            $reason = '「等」已表示列举未尽，后面的省略号又误替了点号。'
            $positionText = '列举标志「等」之后'
            $description = ('在「{0}」中，「等」已经承担列举未尽的功能；其后仍需用「{1}」结束句子或分隔后续分句，不能再用省略号。' -f $focus, $diff.Correction)
            $suggestion = ('将「等」后的「{0}」改为「{1}」。' -f $originalShown, $correctionShown)
        }
        default { throw "Unsupported mutation $($row.mutation)." }
    }

    # Codex-written answers must remain item-specific rather than collapsing to
    # a subtype template. Embed this question's unique searchable context in
    # every explanatory field while keeping reason within the 60-character cap.
    $reasonTagText = Clip $anchor 18
    $reasonTag = ('；对应「{0}」' -f $reasonTagText)
    $reasonBaseLimit = [Math]::Max(8, 59 - $reasonTag.Length)
    $reasonBase = (Clip $reason $reasonBaseLimit).TrimEnd('。')
    $reason = $reasonBase + $reasonTag + '。'
    $contextIdentity = Clip ($left + $diff.Original + $right) 40
    $description = $description.TrimEnd('。') + ('；定位上下文为「{0}」。' -f $contextIdentity)
    $suggestion = $suggestion.TrimEnd('。') + ('；修改位置见「{0}」。' -f $contextIdentity)

    $answer = [ordered]@{
        reason = $reason
        has_error = $true
        total_errors = 1
        errors = @([ordered]@{
            error_type = '标点符号错误'
            position = $positionText
            original_text = [string]$diff.Original
            anchor_text = $anchor
            correction = [string]$diff.Correction
            description = $description
            suggestion = $suggestion
        })
    }
    return $answer
}

$records = @([System.IO.File]::ReadAllLines($Training, $utf8NoBom) | ForEach-Object { $_ | ConvertFrom-Json })
if (-not (Test-Path -LiteralPath $backup)) { Copy-Item -LiteralPath $Training -Destination $backup }

$manifestByLine = @{}
foreach ($raw in [System.IO.File]::ReadAllLines($Manifest, $utf8NoBom)) {
    $row = $raw | ConvertFrom-Json
    $manifestByLine[[int]$row.training_line] = $row
}
$latestQwen = @{}
foreach ($raw in [System.IO.File]::ReadAllLines($QwenResults, $utf8NoBom)) {
    $row = $raw | ConvertFrom-Json
    $latestQwen[[int]$row.line_number] = $row
}
$auditByLine = @{}
foreach ($raw in [System.IO.File]::ReadAllLines($QwenAudit, $utf8NoBom)) {
    $row = $raw | ConvertFrom-Json
    $auditByLine[[int]$row.Line] = $row
}

$origins = [System.Collections.Generic.List[object]]::new()
$codexAnswers = [System.Collections.Generic.List[object]]::new()
foreach ($line in ($manifestByLine.Keys | Sort-Object)) {
    $qwen = $latestQwen[$line]
    $audit = $auditByLine[$line]
    $useQwen = $qwen.status -eq 'success' -and $qwen.answer.has_error -and [string]::IsNullOrEmpty([string]$audit.Issues)
    if ($useQwen) {
        $answer = $qwen.answer
        $origin = 'Qwen3.8-max_审核通过'
    } else {
        $answer = New-CodexAnswer $manifestByLine[$line]
        $origin = if (-not $qwen.answer.has_error) { 'Codex_Qwen判无错后逐题生成' } else { 'Codex_Qwen答案审核不合格后重写' }
        $codexAnswers.Add([pscustomobject]@{ Line = $line; Answer = $answer })
    }
    $records[$line - 1].messages[2].content = $answer | ConvertTo-Json -Compress -Depth 8
    $origins.Add([pscustomobject]@{ training_line = $line; answer_origin = $origin; mutation = [string]$manifestByLine[$line].mutation })
}

$outputLines = @($records | ForEach-Object { $_ | ConvertTo-Json -Compress -Depth 12 })
[System.IO.File]::WriteAllLines($Training, $outputLines, $utf8NoBom)
[System.IO.File]::WriteAllLines($originPath, @($origins | ForEach-Object { $_ | ConvertTo-Json -Compress }), $utf8NoBom)

# Final validation covers all 196 rewritten rows.
$invalid = [System.Collections.Generic.List[object]]::new()
foreach ($line in ($manifestByLine.Keys | Sort-Object)) {
    $record = $records[$line - 1]
    $payload = Get-Payload $record
    $answer = ([string]$record.messages[2].content) | ConvertFrom-Json
    $issues = [System.Collections.Generic.List[string]]::new()
    if (-not $answer.has_error -or $answer.total_errors -ne 1 -or @($answer.errors).Count -ne 1) { $issues.Add('not_single_positive') }
    else {
        $errorItem = $answer.errors[0]
        if ($errorItem.error_type -ne '标点符号错误') { $issues.Add('wrong_error_type') }
        $detection = [string]$payload.detection_content
        $original = [string]$errorItem.original_text
        $position = $detection.IndexOf($original, [System.StringComparison]::Ordinal)
        if ($position -lt 0) { $issues.Add('original_not_found') }
        else {
            $fixed = $detection.Substring(0, $position) + [string]$errorItem.correction + $detection.Substring($position + $original.Length)
            if ($fixed -ne [string]$manifestByLine[$line].correct_content) { $issues.Add('roundtrip_failed') }
        }
        $anchor = [string]$errorItem.anchor_text
        if ([string]::IsNullOrWhiteSpace($anchor) -or -not $detection.Contains($anchor)) { $issues.Add('anchor_invalid') }
        elseif (([regex]::Matches($detection, [regex]::Escape($anchor))).Count -ne 1) { $issues.Add('anchor_not_unique') }
        if (([string]$answer.reason).Length -gt 60) { $issues.Add('reason_too_long') }
    }
    if ($issues.Count -gt 0) { $invalid.Add([pscustomobject]@{ Line = $line; Issues = ($issues -join ',') }) }
}

$codexReasonUnique = @($codexAnswers | ForEach-Object { [string]$_.Answer.reason } | Sort-Object -Unique).Count
$codexDescriptionUnique = @($codexAnswers | ForEach-Object { [string]$_.Answer.errors[0].description } | Sort-Object -Unique).Count
$codexSuggestionUnique = @($codexAnswers | ForEach-Object { [string]$_.Answer.errors[0].suggestion } | Sort-Object -Unique).Count
$report = [ordered]@{
    generated_at = (Get-Date).ToString('s')
    total_changed_records = $manifestByLine.Count
    qwen_answers_retained = @($origins | Where-Object answer_origin -eq 'Qwen3.8-max_审核通过').Count
    codex_answers_for_qwen_no_error = @($origins | Where-Object answer_origin -eq 'Codex_Qwen判无错后逐题生成').Count
    codex_answers_for_invalid_qwen = @($origins | Where-Object answer_origin -eq 'Codex_Qwen答案审核不合格后重写').Count
    codex_total = $codexAnswers.Count
    codex_unique_reasons = $codexReasonUnique
    codex_unique_descriptions = $codexDescriptionUnique
    codex_unique_suggestions = $codexSuggestionUnique
    final_invalid_records = $invalid.Count
    training_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Training).Hash
}
$report | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $reportPath -Encoding UTF8
if ($invalid.Count -ne 0 -or $report.qwen_answers_retained -ne 110 -or $report.codex_answers_for_qwen_no_error -ne 55 -or $report.codex_answers_for_invalid_qwen -ne 31 -or $codexReasonUnique -ne 86 -or $codexDescriptionUnique -ne 86 -or $codexSuggestionUnique -ne 86) {
    $invalid | Format-Table | Out-String | Write-Error
    throw 'Answer merge validation failed.'
}
$report | ConvertTo-Json -Depth 6
