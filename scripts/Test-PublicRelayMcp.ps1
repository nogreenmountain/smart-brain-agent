#Requires -Version 5.1
[CmdletBinding()]
param([string]$McpUrl = "https://39.105.79.0/mcp")

$ErrorActionPreference = "Stop"
$token = [Environment]::GetEnvironmentVariable("SMARTBRAIN_WIKI_MCP_TOKEN", "User")
if (-not $token) { $token = $env:SMARTBRAIN_WIKI_MCP_TOKEN }
if (-not $token) { throw "SMARTBRAIN_WIKI_MCP_TOKEN is not configured." }

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) (
    "smartbrain-public-mcp-$([guid]::NewGuid().ToString('N'))"
)
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null

function Invoke-McpRequest {
    param(
        [hashtable]$Payload,
        [string]$SessionId
    )
    $requestPath = Join-Path $tempRoot "$([guid]::NewGuid().ToString('N')).request.json"
    $responsePath = Join-Path $tempRoot "$([guid]::NewGuid().ToString('N')).response.txt"
    $headersPath = Join-Path $tempRoot "$([guid]::NewGuid().ToString('N')).headers.txt"
    $json = $Payload | ConvertTo-Json -Depth 10 -Compress
    [IO.File]::WriteAllText($requestPath, $json, (New-Object Text.UTF8Encoding $false))
    $arguments = @(
        "--ssl-no-revoke", "-sS",
        "-o", $responsePath,
        "-D", $headersPath,
        "-w", "%{http_code}",
        "-H", "Authorization: Bearer $token",
        "-H", "Content-Type: application/json",
        "-H", "Accept: application/json, text/event-stream"
    )
    if ($SessionId) { $arguments += @("-H", "Mcp-Session-Id: $SessionId") }
    $arguments += @("--data-binary", "@$requestPath", $McpUrl)
    $status = & curl.exe @arguments
    if ($LASTEXITCODE -ne 0) { throw "MCP request failed at the network layer." }
    $raw = Get-Content -Raw -Encoding UTF8 $responsePath
    $dataLine = @($raw -split "`r?`n") |
        Where-Object { $_ -like "data:*" } |
        Select-Object -Last 1
    $jsonResponse = if ($dataLine) {
        $dataLine.Substring(5).Trim() | ConvertFrom-Json
    } elseif ($raw.Trim().StartsWith("{")) {
        $raw | ConvertFrom-Json
    } else {
        $null
    }
    $sessionHeader = Get-Content $headersPath |
        Where-Object { $_ -match "^mcp-session-id:" } |
        Select-Object -First 1
    $returnedSession = if ($sessionHeader) {
        ($sessionHeader -split ":", 2)[1].Trim()
    } else {
        $SessionId
    }
    return [pscustomobject]@{
        status = [int]$status
        body = $jsonResponse
        session_id = $returnedSession
    }
}

try {
    $initialize = Invoke-McpRequest -Payload @{
        jsonrpc = "2.0"
        id = 1
        method = "initialize"
        params = @{
            protocolVersion = "2025-03-26"
            capabilities = @{}
            clientInfo = @{ name = "public-relay-smoke"; version = "1.0" }
        }
    }
    if ($initialize.status -ne 200 -or $initialize.body.error) {
        throw "MCP initialize did not succeed."
    }
    $tools = Invoke-McpRequest -SessionId $initialize.session_id -Payload @{
        jsonrpc = "2.0"
        id = 2
        method = "tools/list"
        params = @{}
    }
    if ($tools.status -ne 200 -or $tools.body.error) {
        throw "MCP tools/list did not succeed."
    }
    $toolNames = @($tools.body.result.tools | ForEach-Object { $_.name })
    [pscustomobject]@{
        initialize_status = $initialize.status
        server_name = $initialize.body.result.serverInfo.name
        tools_status = $tools.status
        tool_count = $toolNames.Count
        has_search_wiki = $toolNames -contains "search_wiki"
        has_propose_memory = $toolNames -contains "propose_memory"
    }
} finally {
    $token = $null
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
