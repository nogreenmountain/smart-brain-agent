#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$DownloadUrl = "https://39.105.79.0/downloads/SmartBrain-AIMonitor-Setup-latest.exe",
    [string]$PublishedFile = "D:\AgentOpsServer\AgentOps\app\smartbrain-dashboard\public\downloads\SmartBrain-AIMonitor-Setup-latest.exe"
)

$ErrorActionPreference = "Stop"
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) (
    "smartbrain-installer-verify-$([guid]::NewGuid().ToString('N'))"
)
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
try {
    $download = Join-Path $tempRoot "latest.exe"
    & curl.exe -sS --max-time 60 -o $download $DownloadUrl
    if ($LASTEXITCODE -ne 0) { throw "Installer download failed." }
    $extract = Join-Path $tempRoot "extract"
    $process = Start-Process -FilePath $download `
        -ArgumentList @("--extract-only", $extract) `
        -Wait `
        -PassThru `
        -WindowStyle Hidden
    if ($process.ExitCode -ne 0) { throw "Installer extraction failed." }

    $manifest = Get-Content -Raw -Encoding UTF8 (Join-Path $extract "manifest.json") |
        ConvertFrom-Json
    $caPath = Join-Path $extract ([string]$manifest.trusted_root_ca_file)
    if (-not (Test-Path -LiteralPath $caPath -PathType Leaf)) {
        throw "Installer did not contain its trusted root CA."
    }
    $certificate = Get-PfxCertificate -FilePath $caPath
    $localHash = (Get-FileHash -Algorithm SHA256 $PublishedFile).Hash
    $downloadHash = (Get-FileHash -Algorithm SHA256 $download).Hash

    [pscustomobject]@{
        hash_match = $localHash -eq $downloadHash
        sha256 = $downloadHash
        package_version = $manifest.package_version
        api_endpoint = $manifest.api_endpoint
        collector_endpoint = $manifest.collector_endpoint
        trusted_root_ca_file = $manifest.trusted_root_ca_file
        root_ca_thumbprint = $certificate.Thumbprint
    }
} finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
