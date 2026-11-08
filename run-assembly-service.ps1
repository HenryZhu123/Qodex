param(
    [string]$Python = "",
    [int]$Port = 8092
)
$ErrorActionPreference = "Stop"
if (-not $Python) {
    $localPython = Join-Path $PSScriptRoot ".venv/Scripts/python.exe"
    $teamPython = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) "hku-agent-exam-checker/services/exam-checker/.venv/Scripts/python.exe"
    if (Test-Path -LiteralPath $localPython) { $Python = $localPython }
    elseif (Test-Path -LiteralPath $teamPython) { $Python = $teamPython }
    else { $Python = (Get-Command python -ErrorAction Stop).Source }
}
$previousPythonPath = $env:PYTHONPATH
try {
    $service = Join-Path $PSScriptRoot "pi-coding-agent/services/exam-assembly/src"
    $env:PYTHONPATH = $PSScriptRoot + [IO.Path]::PathSeparator + $service
    if ($previousPythonPath) { $env:PYTHONPATH += [IO.Path]::PathSeparator + $previousPythonPath }
    Push-Location $PSScriptRoot
    try {
        & $Python -X utf8 -m uvicorn exam_assembly_service.app:app --host 127.0.0.1 --port $Port
    } finally { Pop-Location }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}
