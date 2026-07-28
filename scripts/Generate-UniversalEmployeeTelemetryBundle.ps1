#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$ProjectId = "f9505558-d67d-462f-b77e-6b9550458a2b",
    [string]$ApiEndpoint = "http://192.168.1.40:8000",
    [string]$CollectorEndpoint = "http://192.168.1.40:4318",
    [string]$DefaultEmailDomain = "local.dev",
    [string]$OutputRoot = "D:\AgentOpsServer\AgentOps\employee-deploy\universal"
)

$ErrorActionPreference = "Stop"
$composeFiles = @(
    "-f", "compose.server.yaml",
    "-f", "compose.server.override.yaml"
)
$containerId = (
    docker compose @composeFiles ps -q api
).Trim()
if (-not $containerId) {
    throw "AgentOps API container is not running."
}

docker exec $containerId python -c "import employee_telemetry.cli"
if ($LASTEXITCODE -ne 0) {
    throw "The API image does not contain employee_telemetry."
}

$runId = Get-Date -Format "yyyyMMdd-HHmmss"
$containerRoot = "/tmp/ai-workday-universal-$runId"
New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

docker exec $containerId python -m employee_telemetry.cli `
    --universal `
    --project-id $ProjectId `
    --api-endpoint $ApiEndpoint `
    --collector-endpoint $CollectorEndpoint `
    --default-email-domain $DefaultEmailDomain `
    --output-root $containerRoot
if ($LASTEXITCODE -ne 0) {
    throw "Failed to generate the universal bundle."
}

docker cp "${containerId}:${containerRoot}/." $OutputRoot
if ($LASTEXITCODE -ne 0) {
    throw "Failed to copy bundles from the API container."
}

Write-Host ""
Write-Host "Generated one universal employee bundle:" -ForegroundColor Green
Write-Host (Join-Path $OutputRoot "ai-workday-universal")
Write-Host "The same directory can be distributed to every employee."
