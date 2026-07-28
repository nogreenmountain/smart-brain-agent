#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,
    [Parameter(Mandatory = $true)]
    [string]$ServerIP,
    [string]$DefaultEmailDomain = "local.dev",
    [string]$OutputRoot = "employee-deploy\universal"
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $root

$compose = @("-f", "compose.server.yaml", "-f", "compose.server.override.yaml")
$containerId = (docker compose @compose ps -q api).Trim()
if (-not $containerId) {
    throw "API container is not running."
}

$apiEndpoint = "http://${ServerIP}:8000"
$collectorEndpoint = "http://${ServerIP}:4318"
$runId = Get-Date -Format "yyyyMMdd-HHmmss"
$containerRoot = "/tmp/ai-workday-universal-$runId"
$hostOutput = Join-Path $root $OutputRoot
New-Item -ItemType Directory -Force -Path $hostOutput | Out-Null

docker exec $containerId python -m employee_telemetry.cli `
    --universal `
    --project-id $ProjectId `
    --api-endpoint $apiEndpoint `
    --collector-endpoint $collectorEndpoint `
    --default-email-domain $DefaultEmailDomain `
    --output-root $containerRoot
if ($LASTEXITCODE -ne 0) {
    throw "Failed to generate employee bundle."
}

docker cp "${containerId}:${containerRoot}/." $hostOutput
if ($LASTEXITCODE -ne 0) {
    throw "Failed to copy employee bundle from API container."
}

Write-Host "Generated universal employee bundle:" -ForegroundColor Green
Write-Host (Join-Path $hostOutput "ai-workday-universal")
