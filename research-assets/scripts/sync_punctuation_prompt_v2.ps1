param(
    [string]$Training = 'C:\hyt-agent\训练集-微调版提示词\标点符号错误_训练集_v2.jsonl',
    [string]$PromptDirectory = 'C:\hyt-agent\提示词-微调版'
)

$ErrorActionPreference = 'Stop'
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$parts = @('共享核心.txt', '标点符号错误.txt', 'JSON约束.txt') | ForEach-Object {
    [System.IO.File]::ReadAllText((Join-Path $PromptDirectory $_), $utf8NoBom).Trim()
}
$systemPrompt = $parts -join "`n"
$records = @([System.IO.File]::ReadAllLines($Training, $utf8NoBom) | ForEach-Object { $_ | ConvertFrom-Json })
$lines = foreach ($record in $records) {
    if ($record.messages.Count -ne 3 -or $record.messages[0].role -ne 'system' -or $record.messages[1].role -ne 'user' -or $record.messages[2].role -ne 'assistant') {
        throw 'Unexpected message structure.'
    }
    $record.messages[0].content = $systemPrompt
    $record | ConvertTo-Json -Compress -Depth 12
}
[System.IO.File]::WriteAllLines($Training, $lines, $utf8NoBom)

$wrong = 0
foreach ($raw in [System.IO.File]::ReadAllLines($Training, $utf8NoBom)) {
    $record = $raw | ConvertFrom-Json
    if ([string]$record.messages[0].content -ne $systemPrompt) { $wrong++ }
}
if ($wrong -ne 0) { throw "$wrong records failed prompt synchronization." }
[pscustomobject]@{
    records = $records.Count
    prompt_chars = $systemPrompt.Length
    wrong_system_prompts = $wrong
    sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $Training).Hash
} | ConvertTo-Json
