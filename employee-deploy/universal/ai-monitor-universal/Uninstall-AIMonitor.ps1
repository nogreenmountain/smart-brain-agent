#Requires -Version 5.1
$ErrorActionPreference = "Stop"

try {
    & (Join-Path $PSScriptRoot "Uninstall-AIWorkdayTelemetry.ps1")
} catch {
    Write-Host "CC Switch telemetry uninstall note: $($_.Exception.Message)" -ForegroundColor Yellow
}

Unregister-ScheduledTask -TaskName "SmartBrain AI Conversation Sync" -Confirm:$false -ErrorAction SilentlyContinue
$conversationRuntime = Join-Path (Join-Path $env:LOCALAPPDATA "AIWorkdayTelemetry") "current"
foreach ($fileName in @(
    "ConversationSync.py",
    "Run-ConversationSync.ps1",
    "device-credentials.json",
    "conversation-sync-state.json",
    "conversation-sync-status.json"
)) {
    $path = Join-Path $conversationRuntime $fileName
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Force
    }
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
$profileRoot = Join-Path $runtimeRoot "browser-profiles"
$resolvedRoot = [System.IO.Path]::GetFullPath($runtimeRoot)
$resolvedExtension = [System.IO.Path]::GetFullPath($extensionDir)
if (
    (Test-Path -LiteralPath $extensionDir) -and
    $resolvedExtension.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)
) {
    Remove-Item -LiteralPath $extensionDir -Recurse -Force
}
$resolvedProfiles = [System.IO.Path]::GetFullPath($profileRoot)
if (
    (Test-Path -LiteralPath $profileRoot) -and
    $resolvedProfiles.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)
) {
    Remove-Item -LiteralPath $profileRoot -Recurse -Force
}

Write-Host "AI Monitor universal package configuration has been removed." -ForegroundColor Green
