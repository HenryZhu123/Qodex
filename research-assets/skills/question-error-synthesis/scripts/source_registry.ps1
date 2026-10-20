[CmdletBinding()]
param(
    [Parameter(Mandatory, Position = 0)]
    [ValidateSet('fingerprint', 'check', 'reserve', 'commit', 'release')]
    [string]$Command,

    [string]$Registry,
    [string[]]$OtherRegistry = @(),
    [string]$Text,
    [string]$TextFile,
    [string]$SourceFile = '',
    [string]$SourceQuestionNumber,
    [string]$SourcePage,
    [string]$RunId = '',
    [string]$SampleId = '',
    [string]$TaskType = '',
    [string]$Note = '',
    [switch]$AllowUsed
)

$ErrorActionPreference = 'Stop'

function Get-NormalizedText {
    param([Parameter(Mandatory)][string]$Value)

    $normalized = $Value.Normalize([Text.NormalizationForm]::FormKC)
    $normalized = $normalized -replace "`r`n?", "`n"
    $lines = foreach ($line in ($normalized -split "`n", -1)) {
        (($line.Trim()) -replace '[\t\x20]+', ' ')
    }
    while ($lines.Count -gt 0 -and $lines[0] -eq '') { $lines = @($lines | Select-Object -Skip 1) }
    while ($lines.Count -gt 0 -and $lines[-1] -eq '') { $lines = @($lines | Select-Object -First ($lines.Count - 1)) }
    return ($lines -join "`n")
}

function Get-TextFingerprint {
    param([Parameter(Mandatory)][string]$Value)

    $bytes = [Text.Encoding]::UTF8.GetBytes((Get-NormalizedText -Value $Value))
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-RegistryRows {
    param([Parameter(Mandatory)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) { return @() }
    $lineNumber = 0
    return @(
        foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
            $lineNumber++
            if ([string]::IsNullOrWhiteSpace($line)) { continue }
            try { $line | ConvertFrom-Json }
            catch { throw "Invalid JSON at ${Path}:${lineNumber}: $($_.Exception.Message)" }
        }
    )
}

function Get-LatestRecords {
    param([Parameter(Mandatory)][string[]]$Paths)

    $latest = @{}
    foreach ($path in $Paths) {
        foreach ($row in Get-RegistryRows -Path $path) {
            $fingerprint = [string]$row.source_fingerprint_sha256
            if (-not $fingerprint -and $row.source_text) {
                $fingerprint = Get-TextFingerprint -Value ([string]$row.source_text)
            }
            if ($fingerprint) {
                $row | Add-Member -NotePropertyName _registry -NotePropertyValue $path -Force
                $latest[$fingerprint] = $row
            }
        }
    }
    return $latest
}

$hasText = $PSBoundParameters.ContainsKey('Text')
$hasTextFile = $PSBoundParameters.ContainsKey('TextFile')
if ($hasText -and $hasTextFile) {
    throw 'Provide only one of -Text and -TextFile.'
}
if ($hasTextFile) {
    $questionText = Get-Content -LiteralPath $TextFile -Raw -Encoding UTF8
}
elseif ($hasText) {
    $questionText = $Text
}
else {
    throw 'Provide -Text or -TextFile.'
}

$fingerprint = Get-TextFingerprint -Value $questionText
if ($Command -eq 'fingerprint') {
    Write-Output $fingerprint
    exit 0
}
if (-not $Registry) { throw '-Registry is required for this command.' }

$resolvedRegistry = [IO.Path]::GetFullPath($Registry)
$registryDirectory = Split-Path -Parent $resolvedRegistry
if (-not (Test-Path -LiteralPath $registryDirectory)) {
    New-Item -ItemType Directory -Path $registryDirectory | Out-Null
}
$lockPath = "$resolvedRegistry.lock"
$lockStream = $null
$deadline = [DateTime]::UtcNow.AddSeconds(15)
while ($null -eq $lockStream) {
    try {
        $lockStream = [IO.File]::Open($lockPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    }
    catch [IO.IOException] {
        if ([DateTime]::UtcNow -ge $deadline) { throw "Registry lock timeout: $lockPath" }
        Start-Sleep -Milliseconds 100
    }
}

try {
    $paths = @($OtherRegistry | ForEach-Object { [IO.Path]::GetFullPath($_) }) + @($resolvedRegistry)
    $latest = Get-LatestRecords -Paths $paths
    $prior = $latest[$fingerprint]

    if ($Command -eq 'check') {
        $blocked = $null -ne $prior -and $prior.status -in @('used', 'reserved')
        [ordered]@{ fingerprint = $fingerprint; blocked = $blocked; record = $prior } |
            ConvertTo-Json -Depth 8 -Compress
        if ($blocked) { exit 2 }
        exit 0
    }

    if ($prior -and $prior.status -eq 'used' -and -not $AllowUsed) {
        [ordered]@{ fingerprint = $fingerprint; blocked = $true; record = $prior } |
            ConvertTo-Json -Depth 8 -Compress
        exit 2
    }
    if ($prior -and $prior.status -eq 'reserved') {
        $sameRun = $RunId -and $prior.reserved_for_run -eq $RunId
        if (-not $sameRun) {
            [ordered]@{ fingerprint = $fingerprint; blocked = $true; record = $prior } |
                ConvertTo-Json -Depth 8 -Compress
            exit 2
        }
    }
    if ($Command -in @('commit', 'release')) {
        if (-not $prior -or $prior.status -ne 'reserved' -or $prior.reserved_for_run -ne $RunId) {
            throw "$Command requires a reservation owned by -RunId '$RunId'."
        }
    }

    $status = @{ reserve = 'reserved'; commit = 'used'; release = 'released' }[$Command]
    $timestamp = [DateTimeOffset]::Now.ToString('yyyy-MM-ddTHH:mm:sszzz')
    $row = [ordered]@{
        source_fingerprint_sha256 = $fingerprint
        source_text = $questionText
        source_file = $SourceFile
        source_question_number = $SourceQuestionNumber
        source_page = $SourcePage
        status = $status
        reserved_for_run = $RunId
        sample_id = $SampleId
        task_type = $TaskType
        reserved_at = if ($status -eq 'reserved') { $timestamp } else { $prior.reserved_at }
        used_at = if ($status -eq 'used') { $timestamp } else { $null }
        released_at = if ($status -eq 'released') { $timestamp } else { $null }
        note = $Note
    }

    $json = $row | ConvertTo-Json -Depth 8 -Compress
    $writer = [IO.StreamWriter]::new($resolvedRegistry, $true, [Text.UTF8Encoding]::new($false))
    try {
        $writer.WriteLine($json)
        $writer.Flush()
    }
    finally {
        $writer.Dispose()
    }
    Write-Output $json
}
finally {
    if ($lockStream) { $lockStream.Dispose() }
    Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
}
