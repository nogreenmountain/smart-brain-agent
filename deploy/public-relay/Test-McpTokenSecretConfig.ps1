#Requires -Version 5.1
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$baseCompose = Join-Path $repoRoot "compose.server.yaml"
$overrideCompose = Join-Path $repoRoot "compose.server.override.yaml"

$rendered = docker compose `
    -f $baseCompose `
    -f $overrideCompose `
    config --format json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) {
    throw "docker compose config failed"
}

$apiSecret = [string]$rendered.services.api.environment.WIKI_MCP_TOKEN_SECRET
$mcpSecret = [string]$rendered.services."wiki-mcp".environment.WIKI_MCP_TOKEN_SECRET
if ([string]::IsNullOrWhiteSpace($apiSecret)) {
    throw "API service must receive WIKI_MCP_TOKEN_SECRET so newly issued tokens use the MCP verifier key."
}
if ([string]::IsNullOrWhiteSpace($mcpSecret)) {
    throw "Wiki MCP service must receive WIKI_MCP_TOKEN_SECRET."
}
if (-not [string]::Equals($apiSecret, $mcpSecret, [StringComparison]::Ordinal)) {
    throw "API and Wiki MCP services must use the same WIKI_MCP_TOKEN_SECRET."
}

Write-Output "Wiki MCP token secret configuration passed."
