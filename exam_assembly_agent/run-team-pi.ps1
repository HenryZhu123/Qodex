param(
    [string]$PiRoot = "",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PiArguments
)

$ErrorActionPreference = "Stop"
if (-not $PiRoot) {
    $workspace = Split-Path -Parent $PSScriptRoot
    $parent = Split-Path -Parent $workspace
    $candidates = @(
        (Join-Path $workspace "pi-coding-agent"),
        (Join-Path $parent "hku-agent-exam-checker"),
        (Join-Path (Split-Path -Parent $parent) "hku-agent-exam-checker")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath (Join-Path $candidate "package.json")) {
            $PiRoot = $candidate
            break
        }
    }
    if (-not $PiRoot) { throw "Team Pi repository not found. Specify -PiRoot." }
}
$PiRoot = (Resolve-Path -LiteralPath $PiRoot).Path
if (Test-Path -LiteralPath (Join-Path $PiRoot "pi-coding-agent/package.json")) {
    $PiRoot = Join-Path $PiRoot "pi-coding-agent"
}
$nodePath = Join-Path $env:ProgramFiles "nodejs/node.exe"
if (-not (Test-Path -LiteralPath $nodePath)) {
    $nodePath = (Get-Command node -ErrorAction Stop).Source
}
$tsx = Join-Path $PiRoot "node_modules/tsx/dist/cli.mjs"
$entry = Join-Path $PiRoot "packages/coding-agent/src/experimental/cli.ts"
if (-not (Test-Path -LiteralPath $tsx)) {
    throw "Pi dependencies are missing. Run npm.cmd ci --ignore-scripts in the Pi repository first."
}
if (-not (Test-Path -LiteralPath $entry)) {
    throw "The team Pi source entry point was not found. Check -PiRoot."
}
# Keep the caller's working directory and credentials. Only child-process resolution changes temporarily.
$previousPath = $env:PATH
$previousOutputEncoding = $OutputEncoding
$previousConsoleEncoding = [Console]::OutputEncoding
$launchDir = Join-Path $PSScriptRoot "outputs/pi_launch"
New-Item -ItemType Directory -Path $launchDir -Force | Out-Null
$argsFile = Join-Path $launchDir ([guid]::NewGuid().ToString("N") + ".json")
[string[]]$safeArguments = @()
if ($PiArguments) { $safeArguments = $PiArguments }
$argsJson = ConvertTo-Json -InputObject $safeArguments -Depth 10
[IO.File]::WriteAllText($argsFile, $argsJson, [Text.UTF8Encoding]::new($false))
try {
    $OutputEncoding = [Text.UTF8Encoding]::new($false)
    [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
    $env:PATH = (Split-Path -Parent $nodePath) + [IO.Path]::PathSeparator + $env:PATH
    & $nodePath (Join-Path $PSScriptRoot "pi-launcher.mjs") $argsFile $tsx (Join-Path $PiRoot "tsconfig.json") $entry
    $piExitCode = $LASTEXITCODE
} finally {
    $env:PATH = $previousPath
    $OutputEncoding = $previousOutputEncoding
    [Console]::OutputEncoding = $previousConsoleEncoding
    Remove-Item -LiteralPath $argsFile -ErrorAction SilentlyContinue
}
exit $piExitCode
