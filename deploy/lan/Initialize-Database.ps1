#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$DbContainer = "supabase_db_database",
    [string]$DbUser = "postgres",
    [string]$DbName = "postgres"
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$seed = Join-Path $PSScriptRoot "seed-smartbrain.sql"
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
$OutputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom

$containerId = (docker ps -q --filter "name=$DbContainer").Trim()
if (-not $containerId) {
    throw "Database container '$DbContainer' is not running. Start Supabase and run migrations first."
}

Get-Content -Path $seed -Raw -Encoding UTF8 | docker exec -i $DbContainer psql -U $DbUser -d $DbName
if ($LASTEXITCODE -ne 0) {
    throw "Database initialization failed."
}

Write-Host "Database initialized." -ForegroundColor Green
Write-Host "Admin: hanshangbo / 12345678"
Write-Host "Test users: test1-test12 / 123456"
