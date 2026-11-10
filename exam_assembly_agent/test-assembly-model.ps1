param([string]$Python = "python")
$ErrorActionPreference = "Stop"
if (-not $env:TALKWEB_API_KEY) {
    throw "TALKWEB_API_KEY is missing in this terminal. Enter the key locally first."
}
$request = Get-Content -LiteralPath (Join-Path $PSScriptRoot "examples/request.json") -Raw -Encoding UTF8
$prompt = "This is an explicitly authorized development demo using mock-reviewed questions. Call exam_assembly exactly once with bank=development and this request: " + $request +
    " Then summarize the actual returned status, question count, score and artifact paths. State that this is mock data and structural checks only. Do not generate questions or call another tool."
$runDir = Join-Path $PSScriptRoot ("outputs/pi_model_checks/" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $runDir -Force | Out-Null
$trace = Join-Path $runDir "trace.jsonl"
Write-Host "Starting Pi. Model test timeout: 180 seconds."
Write-Host "Trace: $trace"
$previousTimeout = $env:QODEX_PI_TIMEOUT_MS
$env:QODEX_PI_TIMEOUT_MS = '180000'
$printedModelProgress = $false
try {
& (Join-Path $PSScriptRoot "run-assembly-pi.ps1") -Python $Python -PiArguments @(
    '--provider', 'talkweb', '--model', 'gpu-deepseek-flash',
    '--no-session', '--no-context-files', '--tools', 'exam_assembly', '--mode', 'json', '-p', $prompt
) | Tee-Object -FilePath $trace | ForEach-Object {
    $event = $null
    try { $event = $_ | ConvertFrom-Json } catch { }
    if ($event.type -eq 'agent_start') { Write-Host '[progress] Pi started; waiting for model.' }
    if ($event.type -eq 'message_update' -and -not $printedModelProgress) {
        Write-Host '[progress] Model response received.'
        $printedModelProgress = $true
    }
    if ($event.type -eq 'tool_execution_start') { Write-Host ('[progress] Tool started: ' + $event.toolName) }
    if ($event.type -eq 'tool_execution_end') { Write-Host ('[progress] Tool completed: ' + $event.toolName) }
    if ($event.type -eq 'agent_end') { Write-Host '[progress] Agent completed.' }
}
} finally {
    $env:QODEX_PI_TIMEOUT_MS = $previousTimeout
}
$events = @(Get-Content -LiteralPath $trace | ForEach-Object {
    try { $_ | ConvertFrom-Json } catch { }
})
$completed = @($events | Where-Object { $_.type -eq 'tool_execution_end' -and $_.toolName -eq 'exam_assembly' })
$statuses = @($completed | ForEach-Object {
    foreach ($block in $_.result.content) {
        if ($block.type -eq 'text') {
            try { ($block.text | ConvertFrom-Json).status } catch { }
        }
    }
})
$summary = [pscustomobject]@{
    model = 'gpu-deepseek-flash'
    tool = 'exam_assembly'
    observed_tool_completions = $completed.Count
    returned_statuses = $statuses
    passed = ($completed.Count -eq 1 -and $statuses -contains 'STRUCTURAL_PASS' -and
              @($completed | Where-Object { $_.isError }).Count -eq 0)
    trace = $trace
    note = 'Mock-bank integration test only; not real review or semantic validation.'
}
$json = $summary | ConvertTo-Json -Depth 10
[IO.File]::WriteAllText((Join-Path $runDir "summary.json"), $json, [Text.UTF8Encoding]::new($false))
Write-Output $json
