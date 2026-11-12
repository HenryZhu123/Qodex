param([int]$WebPort = 3000, [switch]$NoWeb, [switch]$SkipDatabase)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskPython = Join-Path $taskRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Run scripts/setup-local.ps1 first.' }
Set-Location -LiteralPath $taskRoot
$taskArgs = @('scripts/local-stack.py', '--web-port', "$WebPort")
if ($NoWeb) { $taskArgs += '--no-web' }
if ($SkipDatabase) { $taskArgs += '--skip-database' }
& $taskPython @taskArgs
if ($LASTEXITCODE -ne 0) { throw 'Local stack stopped with an error. Check .local/web-stack logs.' }
