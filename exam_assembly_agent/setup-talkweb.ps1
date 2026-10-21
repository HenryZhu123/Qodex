# Configure provider metadata only. Never accepts or saves an API key.
$ErrorActionPreference = "Stop"
$configDir = Join-Path $env:USERPROFILE ".pi/agent"
$modelsPath = Join-Path $configDir "models.json"
$provider = [pscustomobject]@{
    baseUrl = "https://llm.talkweb.com.cn/v1"
    api = "openai-completions"
    apiKey = '$TALKWEB_API_KEY'
    models = @(
        [pscustomobject]@{ id = "gpu-deepseek-flash"; name = "Talkweb GPU DeepSeek Flash" },
        [pscustomobject]@{ id = "qwen3.8-max"; name = "Talkweb Qwen 3.8 Max" }
    )
}
if (Test-Path -LiteralPath $modelsPath) {
    $config = Get-Content -LiteralPath $modelsPath -Raw | ConvertFrom-Json
    if ($config.providers -and $config.providers.PSObject.Properties["talkweb"]) {
        throw "Talkweb configuration already exists. Kept existing configuration; no files were changed."
    }
    Copy-Item -LiteralPath $modelsPath -Destination ($modelsPath + ".backup-" + [guid]::NewGuid().ToString("N"))
} else {
    $config = [pscustomobject]@{}
}
if (-not $config.PSObject.Properties["providers"]) {
    $config | Add-Member -NotePropertyName providers -NotePropertyValue ([pscustomobject]@{})
}
$config.providers | Add-Member -NotePropertyName talkweb -NotePropertyValue $provider
New-Item -ItemType Directory -Path $configDir -Force | Out-Null
$json = $config | ConvertTo-Json -Depth 50
[IO.File]::WriteAllText($modelsPath, $json, [Text.UTF8Encoding]::new($false))
Write-Output "Talkweb provider configured. No API key saved. Existing default model unchanged."
