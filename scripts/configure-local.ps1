param([switch]$SkipKey, [string]$KnowledgeBasePath = '')
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskConfig = Join-Path $taskRoot '.env.local'
$taskLines = if (Test-Path -LiteralPath $taskConfig) { [Collections.Generic.List[string]]::new([IO.File]::ReadAllLines($taskConfig)) } else { [Collections.Generic.List[string]]::new() }
function Set-TaskEnvironmentValue([string]$Name, [string]$Value, [switch]$OnlyIfMissing) {
    $taskPattern = '^\s*' + [Regex]::Escape($Name) + '\s*='
    for ($taskIndex = 0; $taskIndex -lt $taskLines.Count; $taskIndex++) {
        if ($taskLines[$taskIndex] -match $taskPattern) {
            if (-not $OnlyIfMissing) { $taskLines[$taskIndex] = $Name + '=' + $Value }
            return
        }
    }
    $taskLines.Add($Name + '=' + $Value)
}
[ordered]@{
    PI_PROVIDER = 'deepseek'
    PI_MODEL_ID = 'deepseek-flash'
    EXAM_CHECKER_LLM_BASE_URL = 'https://api.deepseek.com'
    EXAM_CHECKER_LLM_MODEL = 'deepseek-flash'
    EXAM_CHECKER_DATABASE_URL = 'postgresql+asyncpg://qodex:qodex-local@127.0.0.1:5433/qodex'
    EXAM_ASSEMBLY_DATABASE_URL = 'postgresql://qodex:qodex-local@127.0.0.1:5433/qodex'
    QUESTION_GENERATION_DATABASE_URL = 'postgresql://qodex:qodex-local@127.0.0.1:5433/qodex'
    EXAM_CHECKER_SERVICE_URL = 'http://127.0.0.1:8091'
    QUESTION_BANK_SERVICE_URL = 'http://127.0.0.1:8091'
    EXAM_ASSEMBLY_SERVICE_URL = 'http://127.0.0.1:8092'
    QUESTION_GENERATION_SERVICE_URL = 'http://127.0.0.1:8093'
}.GetEnumerator() | ForEach-Object { Set-TaskEnvironmentValue $_.Key $_.Value -OnlyIfMissing }
if (-not $KnowledgeBasePath) {
    $taskCandidate = Join-Path (Split-Path -Parent $taskRoot) 'qodex-kb-sqlite-2026.11/books'
    if (Test-Path -LiteralPath $taskCandidate -PathType Container) { $KnowledgeBasePath = $taskCandidate }
    elseif (Test-Path -LiteralPath $taskConfig) {
        $taskExistingKb = [IO.File]::ReadAllLines($taskConfig) | Where-Object { $_.StartsWith('EXAM_CHECKER_KB_DIR=') } | Select-Object -First 1
        if ($taskExistingKb) { $KnowledgeBasePath = $taskExistingKb.Substring('EXAM_CHECKER_KB_DIR='.Length) }
    }
}
if ($KnowledgeBasePath) {
    if (Test-Path -LiteralPath (Join-Path $KnowledgeBasePath 'books') -PathType Container) { $KnowledgeBasePath = Join-Path $KnowledgeBasePath 'books' }
    if (-not (Test-Path -LiteralPath $KnowledgeBasePath -PathType Container)) { throw 'Knowledge base directory does not exist.' }
    Set-TaskEnvironmentValue 'EXAM_CHECKER_KB_DIR' ([IO.Path]::GetFullPath($KnowledgeBasePath))
}
if (-not $SkipKey) {
    $taskSecret = Read-Host 'DeepSeek API Key (hidden; never paste it into chat)' -AsSecureString
    $taskKey = [System.Net.NetworkCredential]::new('', $taskSecret).Password.Trim()
    if (-not $taskKey -or $taskKey -match '[\r\n]') { throw 'A non-empty single-line key is required.' }
    Set-TaskEnvironmentValue 'DEEPSEEK_API_KEY' $taskKey
    Set-TaskEnvironmentValue 'EXAM_CHECKER_LLM_API_KEY' $taskKey
}
[IO.File]::WriteAllLines($taskConfig, $taskLines, [Text.UTF8Encoding]::new($false))
$taskKey = $null
Write-Host 'Local configuration saved in ignored .env.local. No key was printed or sent.'
Write-Host 'Restart the local stack after changing configuration.'
