param([string]$PythonPath = 'python')
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
if (-not (Test-Path '.venv/Scripts/python.exe')) {
    & $PythonPath -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Creating Python environment failed; provide Python 3.11+ with -PythonPath.' }
}
& ./.venv/Scripts/python.exe -m pip install -e . -e 'pi-coding-agent/services/exam-checker[dev]' -e 'pi-coding-agent/services/exam-assembly[pdf]' -r question_generation/service-requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Python dependencies failed to install.' }
Push-Location pi-coding-agent
try {
    npm ci --ignore-scripts --no-audit
    if ($LASTEXITCODE -ne 0) { throw 'Pi dependencies failed to install.' }
    npm run hydrate:model-data:release
    if ($LASTEXITCODE -ne 0) { throw 'Model catalog preparation failed.' }
    node scripts/prepare-qodex-web.mjs
    if ($LASTEXITCODE -ne 0) { throw 'Pi SDK preparation failed.' }
    Push-Location apps/qodex-web
    try {
        npm ci --ignore-scripts --workspaces=false --no-audit
        if ($LASTEXITCODE -ne 0) { throw 'Web dependencies failed to install.' }
    } finally { Pop-Location }
} finally { Pop-Location }
Write-Host 'Setup complete. Start Docker Desktop; run scripts/configure-local.ps1, then scripts/start-local.ps1.'
