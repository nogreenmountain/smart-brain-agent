#Requires -Version 5.1
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$relayRoot = $PSScriptRoot
$composePath = Join-Path $relayRoot "docker-compose.reverse-tunnel.yaml"
$dockerfilePath = Join-Path $relayRoot "tunnel-client\Dockerfile"
$entrypointPath = Join-Path $relayRoot "tunnel-client\entrypoint.sh"
$nginxPath = Join-Path $relayRoot "nginx\smartbrain-ip.conf"

foreach ($path in @($composePath, $dockerfilePath, $entrypointPath, $nginxPath)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Missing reverse tunnel deployment file: $path"
    }
}

$nginxConfig = Get-Content -Raw -LiteralPath $nginxPath
foreach ($requiredSnippet in @(
    "listen 443 ssl http2 default_server;",
    "listen [::]:443 ssl http2 default_server;",
    "location ^~ /.well-known/acme-challenge/",
    "root /var/www/letsencrypt",
    "ssl_certificate /etc/letsencrypt/live/39.105.79.0/fullchain.pem",
    "ssl_certificate_key /etc/letsencrypt/live/39.105.79.0/privkey.pem",
    "location ^~ /auth/",
    "location ^~ /v4/",
    "location = /.well-known/oauth-protected-resource/mcp",
    "location = /mcp",
    "location = /v1/traces",
    "location ^~ /traces",
    "location @agentops_assets",
    "location = /smartbrain-root-ca.crt"
)) {
    if (-not $nginxConfig.Contains($requiredSnippet)) {
        throw "Missing public HTTPS relay route: $requiredSnippet"
    }
}

$v4Location = [regex]::Match(
    $nginxConfig,
    '(?s)location \^~ /v4/ \{.*?\n    \}'
)
if (-not $v4Location.Success) {
    throw "Unable to inspect the public /v4/ relay location"
}
if (-not $v4Location.Value.Contains("client_max_body_size 512m;")) {
    throw "Public /v4/ uploads must allow the 500 MB material batch limit plus multipart overhead"
}
if ([regex]::Matches($nginxConfig, 'client_max_body_size 512m;').Count -lt 2) {
    throw "Both standard HTTPS /v4/ and the direct API relay must use the 512 MB request limit"
}

$rendered = docker compose -f $composePath config --format json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) {
    throw "docker compose config failed"
}

$service = $rendered.services."smartbrain-reverse-tunnel"
if (-not $service) {
    throw "Missing smartbrain-reverse-tunnel service"
}
if ($service.restart -ne "unless-stopped") {
    throw "Reverse tunnel must restart unless stopped"
}
if (-not $service.read_only) {
    throw "Reverse tunnel container must use a read-only root filesystem"
}

$commandText = ($service.command -join " ")
foreach ($mapping in @(
    "127.0.0.1:13002:host.docker.internal:3002",
    "127.0.0.1:18000:host.docker.internal:8000",
    "127.0.0.1:18010:host.docker.internal:8010",
    "127.0.0.1:13001:host.docker.internal:3001",
    "127.0.0.1:14318:host.docker.internal:4318"
)) {
    if (-not $commandText.Contains($mapping)) {
        throw "Missing restricted reverse tunnel mapping: $mapping"
    }
}

Write-Output "Reverse tunnel compose validation passed."
