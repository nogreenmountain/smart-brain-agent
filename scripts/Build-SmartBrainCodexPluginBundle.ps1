param(
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$pluginSource = Join-Path $repoRoot "plugins\company-memory"
$marketplaceSource = Join-Path $repoRoot ".agents\plugins\marketplace.json"

if (-not $OutputPath) {
    $OutputPath = Join-Path $repoRoot "smartbrain-dashboard\public\downloads\smartbrain-company-memory-codex.zip"
}

$resolvedOutput = [System.IO.Path]::GetFullPath($OutputPath)
$allowedOutputRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot "smartbrain-dashboard\public\downloads"))
if (-not $resolvedOutput.StartsWith($allowedOutputRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputPath must stay inside smartbrain-dashboard\public\downloads"
}

$stagingRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("smartbrain-codex-plugin-" + [guid]::NewGuid().ToString("N"))
try {
    New-Item -ItemType Directory -Path (Join-Path $stagingRoot ".agents\plugins") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $stagingRoot "plugins") -Force | Out-Null
    Copy-Item -LiteralPath $marketplaceSource -Destination (Join-Path $stagingRoot ".agents\plugins\marketplace.json")
    Copy-Item -LiteralPath $pluginSource -Destination (Join-Path $stagingRoot "plugins\company-memory") -Recurse
    if (Test-Path -LiteralPath $resolvedOutput) {
        Remove-Item -LiteralPath $resolvedOutput -Force
    }
    Compress-Archive -Path (Join-Path $stagingRoot "*") -DestinationPath $resolvedOutput -CompressionLevel Optimal
    Write-Output $resolvedOutput
}
finally {
    if (Test-Path -LiteralPath $stagingRoot) {
        Remove-Item -LiteralPath $stagingRoot -Recurse -Force
    }
}
