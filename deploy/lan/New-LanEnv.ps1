#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ServerIP,
    [string]$EnvPath = ".env",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$template = Join-Path $root ".env.lan.example"
$target = Join-Path $root $EnvPath

if ((Test-Path $target) -and -not $Force) {
    Write-Host ".env already exists: $target"
    Write-Host "Use -Force to regenerate it."
    exit 0
}

function New-Secret([int]$Bytes = 48) {
    $buffer = New-Object byte[] $Bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buffer)
    return [Convert]::ToBase64String($buffer)
}

$content = Get-Content -Raw -Path $template
$content = $content.Replace("192.168.1.40", $ServerIP)
$content = $content.Replace("CHANGE_ME_LONG_RANDOM_JWT_SECRET", (New-Secret 48))
$content = $content.Replace("CHANGE_ME_LONG_RANDOM_COOKIE_SECRET", (New-Secret 48))
$content = $content.Replace("CHANGE_ME_SUPABASE_JWT_SECRET", "super-secret-jwt-token-with-at-least-32-characters-long")
$content = $content.Replace("CHANGE_ME_SUPABASE_SERVICE_ROLE_KEY", "replace-with-supabase-service-role-key")

Set-Content -Path $target -Value $content -Encoding UTF8
Write-Host "Generated $target"
Write-Host "Edit SUPABASE_SERVICE_ROLE_KEY before starting the API."
