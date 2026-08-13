param(
    [string]$BundlePath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $BundlePath) {
    $BundlePath = Join-Path $repoRoot "smartbrain-dashboard\public\downloads\smartbrain-company-memory-codex.zip"
}

$caseRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("smartbrain-codex-bundle-test-" + [guid]::NewGuid().ToString("N"))
$marketplaceRoot = Join-Path $caseRoot "marketplace"
$isolatedCodexHome = Join-Path $caseRoot "codex-home"

try {
    New-Item -ItemType Directory -Path $marketplaceRoot, $isolatedCodexHome -Force | Out-Null
    Expand-Archive -LiteralPath $BundlePath -DestinationPath $marketplaceRoot -Force
    $env:CODEX_HOME = $isolatedCodexHome
    $env:SMARTBRAIN_WIKI_MCP_TOKEN = "sbmcp_isolated_validation"

    $marketplace = codex.cmd plugin marketplace add $marketplaceRoot --json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw "Marketplace installation failed" }
    $plugin = codex.cmd plugin add "company-memory@smartbrain" --json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw "Plugin installation failed" }
    $installed = codex.cmd plugin list --json | ConvertFrom-Json

    $manifestPath = Join-Path $marketplaceRoot "plugins\company-memory\.codex-plugin\plugin.json"
    $skillPath = Join-Path $marketplaceRoot "plugins\company-memory\skills\company-memory\SKILL.md"
    $manifest = Get-Content -LiteralPath $manifestPath -Encoding utf8 -Raw | ConvertFrom-Json
    $skill = Get-Content -LiteralPath $skillPath -Encoding utf8 -Raw
    foreach ($toolName in @(
        "list_member_wikis",
        "search_member_experience",
        "get_member_experience",
        "get_member_recent_experience",
        "list_meeting_summaries",
        "search_meeting_summaries",
        "get_meeting_summary"
    )) {
        if (-not $skill.Contains($toolName)) {
            throw "Plugin skill does not document MCP tool: $toolName"
        }
    }
    if (-not $manifest.description.Contains("member") -or -not $manifest.description.Contains("meeting")) {
        throw "Plugin manifest does not advertise member experience and meeting summaries"
    }
    if (-not $manifest.description.Contains("identity-attributed")) {
        throw "Plugin manifest does not advertise identity-attributed writes"
    }
    if (-not $skill.Contains("authenticated MCP Token owner")) {
        throw "Plugin skill does not explain automatic uploader attribution"
    }
    if (-not $manifest.description.Contains("publish") -or -not $manifest.description.Contains("safety checks")) {
        throw "Plugin manifest does not advertise direct publishing after safety checks"
    }
    if (-not $skill.Contains("status=published")) {
        throw "Plugin skill does not document the direct-publish success response"
    }
    if ($skill.Contains("pending administrator review") -or $skill.Contains("does not publish directly")) {
        throw "Plugin skill still documents the removed MCP approval flow"
    }
    $hash = Get-FileHash -Algorithm SHA256 -LiteralPath $BundlePath

    [pscustomobject]@{
        marketplace = $marketplace.marketplaceName
        plugin = $plugin.pluginId
        version = $manifest.version
        mcp_url = $manifest.mcpServers."smartbrain-company-memory".url
        bearer_token_env_var = $manifest.mcpServers."smartbrain-company-memory".bearer_token_env_var
        installed_count = $installed.installed.Count
        zip_bytes = (Get-Item -LiteralPath $BundlePath).Length
        sha256 = $hash.Hash
    } | ConvertTo-Json
}
finally {
    $resolvedCase = [System.IO.Path]::GetFullPath($caseRoot)
    $resolvedTemp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
    if ($resolvedCase.StartsWith($resolvedTemp, [System.StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $resolvedCase)) {
        Remove-Item -LiteralPath $resolvedCase -Recurse -Force
    }
}
