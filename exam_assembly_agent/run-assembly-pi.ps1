param(
    [string]$Python = "python",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PiArguments
)
$ErrorActionPreference = "Stop"
$previousPython = $env:QODEX_PYTHON
try {
    $env:QODEX_PYTHON = (Get-Command $Python -ErrorAction Stop).Source
    $extension = Join-Path $PSScriptRoot "pi-extension.ts"
    & (Join-Path $PSScriptRoot "run-team-pi.ps1") -PiArguments (@('-e', $extension) + $PiArguments)
} finally {
    $env:QODEX_PYTHON = $previousPython
}
