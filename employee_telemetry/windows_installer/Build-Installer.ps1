#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$BundleDir,
    [Parameter(Mandatory = $true)]
    [string]$OutputPath,
    [string]$CacheDir = "D:\AgentOpsServer\AgentOps\installer-cache"
)

$ErrorActionPreference = "Stop"
if (-not $BundleDir) {
    $BundleDir = Join-Path $PSScriptRoot "payload"
}
$ccSwitchUsageSource = Join-Path (Split-Path -Parent $PSScriptRoot) "cc_switch_usage_sync.py"
$ccSwitchUsageTarget = Join-Path $BundleDir "CCSwitchUsageSync.py"
$sharedCcSwitchSource = Join-Path (Split-Path -Parent $PSScriptRoot) "shared_cc_switch_session.py"
$sharedCcSwitchTarget = Join-Path $BundleDir "SharedCCSwitchSession.py"
if (-not (Test-Path -LiteralPath $ccSwitchUsageSource -PathType Leaf)) {
    throw "CC Switch usage sync source was not found."
}
Copy-Item -LiteralPath $ccSwitchUsageSource -Destination $ccSwitchUsageTarget -Force
if (-not (Test-Path -LiteralPath $sharedCcSwitchSource -PathType Leaf)) {
    throw "Shared CC Switch session source was not found."
}
Copy-Item -LiteralPath $sharedCcSwitchSource -Destination $sharedCcSwitchTarget -Force
$pythonArchiveName = "python-3.12.10-embed-amd64.zip"
$pythonUrl = "https://www.python.org/ftp/python/3.12.10/$pythonArchiveName"
$pythonSha256 = "4ACBED6DD1C744B0376E3B1CF57CE906F9DC9E95E68824584C8099A63025A3C3"
$required = @(
    "Install-AIMonitor.ps1",
    "Uninstall-AIMonitor.ps1",
    "Install-AIWorkdayTelemetry.ps1",
    "Uninstall-AIWorkdayTelemetry.ps1",
    "Enroll-AIWorkday.py",
    "Update-CCSwitchCommonConfig.py",
    "ConversationSync.py",
    "CCSwitchUsageSync.py",
    "SharedCCSwitchSession.py",
    "manifest.json",
    "chatgpt-web-extension"
)

foreach ($name in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $BundleDir $name))) {
        throw "Bundle is missing required payload: $name"
    }
}

$bundleManifest = Get-Content -LiteralPath (Join-Path $BundleDir "manifest.json") -Raw -Encoding UTF8 |
    ConvertFrom-Json
if ($bundleManifest.trusted_root_ca_file) {
    $trustedRootCaFile = [string]$bundleManifest.trusted_root_ca_file
    if ([System.IO.Path]::GetFileName($trustedRootCaFile) -ne $trustedRootCaFile) {
        throw "trusted_root_ca_file must be a filename inside the bundle."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $BundleDir $trustedRootCaFile) -PathType Leaf)) {
        throw "Bundle is missing trusted root CA: $trustedRootCaFile"
    }
}

$csc = @(
    "C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
    "C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe"
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $csc) { throw ".NET Framework C# compiler was not found." }

New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null
$pythonArchive = Join-Path $CacheDir $pythonArchiveName
if (-not (Test-Path -LiteralPath $pythonArchive)) {
    Invoke-WebRequest -Uri $pythonUrl -OutFile $pythonArchive
}
$actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $pythonArchive).Hash
if ($actualHash -ne $pythonSha256) {
    throw "Embedded Python archive hash verification failed."
}

$outputDirectory = Split-Path -Parent ([System.IO.Path]::GetFullPath($OutputPath))
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
$workRoot = Join-Path $outputDirectory (".installer-build-" + [Guid]::NewGuid().ToString("N"))
$payloadDir = Join-Path $workRoot "payload"
$payloadZip = Join-Path $workRoot "payload.zip"
$verifyDir = Join-Path $workRoot "verify"
try {
    New-Item -ItemType Directory -Force -Path $payloadDir | Out-Null
    Get-ChildItem -LiteralPath $BundleDir -Force |
        Where-Object { $_.Name -notin @("__pycache__", "tests") } |
        Copy-Item -Destination $payloadDir -Recurse -Force

    $pythonRuntime = Join-Path $payloadDir "python-runtime"
    Expand-Archive -LiteralPath $pythonArchive -DestinationPath $pythonRuntime -Force
    $pthFile = Get-ChildItem -LiteralPath $pythonRuntime -Filter "python*._pth" | Select-Object -First 1
    if (-not $pthFile) { throw "Embedded Python path configuration was not found." }
    Set-Content -LiteralPath $pthFile.FullName -Encoding ASCII -Value @("python312.zip", ".", "..")

    Compress-Archive -Path (Join-Path $payloadDir "*") -DestinationPath $payloadZip -CompressionLevel Optimal
    $source = Join-Path $PSScriptRoot "SmartBrainAIMonitorSetup.cs"
    & $csc /nologo /target:winexe /platform:anycpu /optimize+ `
        /reference:System.Windows.Forms.dll `
        /reference:System.Drawing.dll `
        /reference:System.IO.Compression.dll `
        /reference:System.IO.Compression.FileSystem.dll `
        /resource:"$payloadZip",SmartBrainPayload.zip `
        /out:"$OutputPath" `
        "$source"
    if ($LASTEXITCODE -ne 0) { throw "Installer compilation failed." }

    $selfTest = Start-Process -FilePath $OutputPath `
        -ArgumentList @("--extract-only", $verifyDir) `
        -Wait `
        -PassThru `
        -WindowStyle Hidden
    if ($selfTest.ExitCode -ne 0) { throw "Installer self-test failed." }
    $selfTestRequired = @("Install-AIMonitor.ps1", "manifest.json", "python-runtime\python.exe")
    if ($bundleManifest.trusted_root_ca_file) {
        $selfTestRequired += [string]$bundleManifest.trusted_root_ca_file
    }
    foreach ($name in $selfTestRequired) {
        if (-not (Test-Path -LiteralPath (Join-Path $verifyDir $name))) {
            throw "Installer self-test did not extract: $name"
        }
    }
    Get-Item -LiteralPath $OutputPath | Select-Object FullName, Length
    Get-FileHash -Algorithm SHA256 -LiteralPath $OutputPath
} finally {
    if (Test-Path -LiteralPath $workRoot) {
        Remove-Item -LiteralPath $workRoot -Recurse -Force
    }
}
