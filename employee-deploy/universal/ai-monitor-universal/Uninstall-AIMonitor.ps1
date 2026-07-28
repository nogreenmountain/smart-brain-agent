#Requires -Version 5.1
$ErrorActionPreference = "Stop"

try {
    & (Join-Path $PSScriptRoot "Uninstall-AIWorkdayTelemetry.ps1")
} catch {
    Write-Host "CC Switch telemetry uninstall note: $($_.Exception.Message)" -ForegroundColor Yellow
}

$desktop = [Environment]::GetFolderPath("Desktop")
$shortcuts = @(
    (Join-Path $desktop "ChatGPT Monitored - Edge.lnk"),
    (Join-Path $desktop "ChatGPT Monitored - Chrome.lnk"),
    (Join-Path $desktop "SmartBrain Monitor Setup - Edge.lnk"),
    (Join-Path $desktop "SmartBrain Monitor Setup - Chrome.lnk")
)
foreach ($shortcut in $shortcuts) {
    if (Test-Path -LiteralPath $shortcut) {
        Remove-Item -LiteralPath $shortcut -Force
    }
}

$runtimeRoot = Join-Path $env:LOCALAPPDATA "AIMonitor"
$extensionDir = Join-Path $runtimeRoot "chatgpt-web-extension"
$resolvedRoot = [System.IO.Path]::GetFullPath($runtimeRoot)
$resolvedExtension = [System.IO.Path]::GetFullPath($extensionDir)
if (
    (Test-Path -LiteralPath $extensionDir) -and
    $resolvedExtension.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)
) {
    Remove-Item -LiteralPath $extensionDir -Recurse -Force
}

Write-Host "AI Monitor universal package configuration has been removed." -ForegroundColor Green
