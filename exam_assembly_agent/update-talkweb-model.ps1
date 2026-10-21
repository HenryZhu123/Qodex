# Change only the DeepSeek model entry. Never reads an API key from the terminal.
$ErrorActionPreference = "Stop"
$modelsPath = Join-Path $env:USERPROFILE ".pi/agent/models.json"
$config = Get-Content -LiteralPath $modelsPath -Raw | ConvertFrom-Json
if (-not $config.providers -or -not $config.providers.PSObject.Properties["talkweb"]) {
    throw "Talkweb provider is missing. Run setup-talkweb.ps1 first."
}
$provider = $config.providers.talkweb
$obsoleteIds = @("DeepSeek-V4.1-Flash", "gpu-deepseek-v4-flash", "gpu-deepseek-flash")
$models = @($provider.models | Where-Object { $_.id -notin $obsoleteIds })
$models += [pscustomobject]@{ id = "gpu-deepseek-flash"; name = "Talkweb GPU DeepSeek Flash" }
Copy-Item -LiteralPath $modelsPath -Destination ($modelsPath + ".backup-" + [guid]::NewGuid().ToString("N"))
$provider.models = $models
[IO.File]::WriteAllText($modelsPath, ($config | ConvertTo-Json -Depth 50), [Text.UTF8Encoding]::new($false))
Write-Output "Talkweb model updated to gpu-deepseek-flash. Endpoint and credentials configuration unchanged."
