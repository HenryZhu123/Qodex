param(
    [string]$Python = "",
    [string]$Model = "",
    [ValidateSet("", "talkweb", "deepseek")]
    [string]$Provider = "",
    [int]$Port = 8091,
    [switch]$RefreshApiKey,
    [switch]$PreferEmbeddedPdfText,
    [switch]$CheckOnly
)
$ErrorActionPreference = "Stop"
$serviceRoot = Join-Path $PSScriptRoot "pi-coding-agent/services/exam-checker"
if (-not $Python) {
    $localPython = Join-Path $PSScriptRoot ".venv/Scripts/python.exe"
    $teamPython = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) "hku-agent-exam-checker/services/exam-checker/.venv/Scripts/python.exe"
    if (Test-Path -LiteralPath $localPython) { $Python = $localPython }
    elseif (Test-Path -LiteralPath $teamPython) { $Python = $teamPython }
    else { throw "Python environment missing. Specify -Python with the exam-checker Python executable." }
}
$previousBase = $env:EXAM_CHECKER_LLM_BASE_URL
if (-not $Provider) {
    if ($previousBase -match '^https://api\.deepseek\.com(?:/|$)') { $Provider = "deepseek" }
    else { $Provider = "talkweb" }
}
if ($Provider -eq "deepseek") {
    # Provider credentials must never be sent to the old company gateway.
    $selectedBase = "https://api.deepseek.com"
    $providerKeyName = "DEEPSEEK_API_KEY"
    $defaultModel = "deepseek-flash"
    $keyPrompt = "Personal DeepSeek API Key (hidden input)"
} else {
    $selectedBase = $previousBase
    if (-not $selectedBase -or $selectedBase -match '^https://api\.deepseek\.com(?:/|$)') {
        $selectedBase = "https://llm.talkweb.com.cn/v1"
    }
    $providerKeyName = "TALKWEB_API_KEY"
    $defaultModel = "gpu-deepseek-flash"
    $keyPrompt = "Company gateway API Key (hidden input)"
}
$providerChanged = if ($previousBase) { $previousBase.TrimEnd('/') -ne $selectedBase.TrimEnd('/') } else { $Provider -eq "deepseek" }
$providerKey = [Environment]::GetEnvironmentVariable($providerKeyName, 'Process')
if ($RefreshApiKey -or $providerKey -or $providerChanged -or -not $env:EXAM_CHECKER_LLM_API_KEY) {
    if (-not $RefreshApiKey -and $providerKey) { $env:EXAM_CHECKER_LLM_API_KEY = $providerKey.Trim() }
    else {
        $secret = Read-Host $keyPrompt -AsSecureString
        $env:EXAM_CHECKER_LLM_API_KEY = ([Net.NetworkCredential]::new('', $secret)).Password.Trim()
    }
}
if (-not $env:EXAM_CHECKER_LLM_API_KEY) { throw "API Key is required." }
$env:EXAM_CHECKER_LLM_API_KEY = $env:EXAM_CHECKER_LLM_API_KEY.Trim()
$env:EXAM_CHECKER_LLM_BASE_URL = $selectedBase.Trim().TrimEnd('/')
if (-not $Model -and -not $providerChanged) { $Model = $env:EXAM_CHECKER_LLM_MODEL }
if (-not $Model) { $Model = $defaultModel }
Write-Host "API provider: $Provider"
Write-Host "Checking current gateway model IDs..."
$modelListUrl = $env:EXAM_CHECKER_LLM_BASE_URL.Trim().TrimEnd('/') + '/models'
# Windows PowerShell 5 may otherwise negotiate an obsolete TLS version.
$previousSecurityProtocol = [Net.ServicePointManager]::SecurityProtocol
try {
    [Net.ServicePointManager]::SecurityProtocol = $previousSecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $catalog = Invoke-RestMethod -Uri $modelListUrl `
        -Headers @{ Authorization = "Bearer $env:EXAM_CHECKER_LLM_API_KEY" } -TimeoutSec 30
} catch {
    $failure = $_.Exception
    $httpStatus = $null
    $response = $failure.Response
    if (-not $response -and $failure.InnerException) { $response = $failure.InnerException.Response }
    if ($response -and $null -ne $response.StatusCode) { $httpStatus = [int]$response.StatusCode }
    if ($httpStatus -eq 401) {
        throw "Gateway check failed: HTTP 401 (API key not accepted). Retry with -RefreshApiKey. No PDF request was sent."
    }
    if ($httpStatus -eq 403) {
        throw "Gateway check failed: HTTP 403 (access denied; check key permissions or gateway network policy). No PDF request was sent."
    }
    if ($httpStatus) {
        throw "Gateway check failed: HTTP $httpStatus from the model-list endpoint. No PDF request was sent."
    }
    # Only emit exception categories and WebExceptionStatus, never raw response bodies,
    # headers or messages which might contain credentials.
    $categories = @()
    $current = $failure
    for ($depth = 0; $current -and $depth -lt 5; $depth++) {
        $category = $current.GetType().Name
        if ($current -is [Net.WebException]) { $category += ':' + $current.Status.ToString() }
        if ($current -is [Net.Sockets.SocketException]) { $category += ':' + $current.SocketErrorCode.ToString() }
        $categories += $category
        $current = $current.InnerException
    }
    throw ("Gateway check failed before an HTTP response: " + ($categories -join ' -> ') + ". Check DNS, TLS and VPN/proxy routing. No PDF request was sent.")
} finally {
    [Net.ServicePointManager]::SecurityProtocol = $previousSecurityProtocol
}
if (-not $catalog.data -or -not $catalog.data.id) { throw "Gateway returned no valid model list. No PDF request was sent." }
$modelIds = @($catalog.data.id)
if ($Model -notin $modelIds) {
    Write-Host "Requested model is not currently listed. Current IDs:"
    $modelIds | Sort-Object | ForEach-Object { Write-Host $_ }
    throw "Run this script again with -Model followed by a listed chat model ID. No parsing request was sent."
}
$env:EXAM_CHECKER_LLM_MODEL = $Model
[Environment]::SetEnvironmentVariable($providerKeyName, $env:EXAM_CHECKER_LLM_API_KEY, 'Process')
if ($Provider -eq "deepseek" -or $providerChanged) {
    # Switch extraction, specialist review and metadata/revision together; no stale company role overrides.
    foreach ($role in @('EXAM_CHECKER_REVIEW_LLM', 'EXAM_CHECKER_WORKFLOW_LLM')) {
        [Environment]::SetEnvironmentVariable($role + '_BASE_URL', $env:EXAM_CHECKER_LLM_BASE_URL, 'Process')
        [Environment]::SetEnvironmentVariable($role + '_API_KEY', $env:EXAM_CHECKER_LLM_API_KEY, 'Process')
        [Environment]::SetEnvironmentVariable($role + '_MODEL', $Model, 'Process')
    }
}
Write-Host "Gateway model-list check passed. Model ID: $Model"
if ($CheckOnly) { Write-Host "Check-only mode: no database startup, parsing or model completion request was sent."; return }
$env:EXAM_CHECKER_PREFER_EMBEDDED_PDF_TEXT = if ($PreferEmbeddedPdfText) { "true" } else { "false" }
if ($PreferEmbeddedPdfText) {
    Write-Host "Verified text-only PDFs: prefer embedded text; sparse/image PDFs still use MinerU. Review is unchanged."
}
if (-not $env:EXAM_CHECKER_JEV_API_KEY) {
    if ($env:OPENROUTER_API_KEY) { $env:EXAM_CHECKER_JEV_API_KEY = $env:OPENROUTER_API_KEY }
    else {
        $jevSecret = Read-Host "OpenRouter Jev API Key (hidden; Enter to use specialist fallback)" -AsSecureString
        $env:EXAM_CHECKER_JEV_API_KEY = ([Net.NetworkCredential]::new('', $jevSecret)).Password.Trim()
    }
}
if (-not $env:EXAM_CHECKER_JEV_API_KEY) {
    Write-Host "Jev key not configured. Existing backend policy will run the gated specialist checks as fallback."
}
if (-not $env:EXAM_CHECKER_DATABASE_URL) {
    $env:EXAM_CHECKER_DATABASE_URL = "postgresql+asyncpg://qodex:qodex-local@127.0.0.1:5433/qodex"
}
Write-Host "Starting local PostgreSQL with its existing data volume..."
& docker compose -f (Join-Path $serviceRoot "compose.yaml") up -d --wait postgres
if ($LASTEXITCODE -ne 0) { throw "Database startup failed. Open Docker Desktop and retry." }
$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $serviceRoot "src"
    if ($previousPythonPath) { $env:PYTHONPATH += [IO.Path]::PathSeparator + $previousPythonPath }
    Push-Location $serviceRoot
    try {
        Write-Host "Applying database migrations..."
        & $Python -m alembic upgrade head
        if ($LASTEXITCODE -ne 0) { throw "Database migration failed; service was not started." }
        Write-Host "Starting exam-checker on 127.0.0.1:$Port using model $Model. Keep this window open."
        & $Python -X utf8 -m uvicorn exam_checker.api.app:app --host 127.0.0.1 --port $Port
    } finally { Pop-Location }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}
