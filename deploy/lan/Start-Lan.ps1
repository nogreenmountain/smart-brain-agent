#Requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$Build,
    [switch]$WithGpuRag
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $root

if (-not (Test-Path ".env")) {
    throw ".env not found. Run deploy/lan/New-LanEnv.ps1 first."
}

if ($Build) {
    & (Join-Path $PSScriptRoot "Build-Images.ps1")
}

$supabaseNetwork = docker network ls --format "{{.Name}}" | Select-String -SimpleMatch "supabase_network_database"
if (-not $supabaseNetwork) {
    Write-Warning "Docker network supabase_network_database was not found."
    Write-Warning "Start local Supabase first, for example: supabase start"
}

$compose = @("-f", "compose.server.yaml", "-f", "compose.server.override.yaml")
if ($WithGpuRag) {
    $compose += @("-f", "compose.rag-gpu.override.yaml")
}

docker compose @compose up -d
if ($LASTEXITCODE -ne 0) {
    throw "docker compose up failed"
}

Write-Host ""
Write-Host "SmartBrain LAN services are starting." -ForegroundColor Green
Write-Host "API:        http://<server-ip>:8000/health"
Write-Host "SmartBrain: http://<server-ip>:3002"
Write-Host "Trace UI:   http://<server-ip>:3001"
