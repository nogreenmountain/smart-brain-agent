#Requires -Version 5.1
[CmdletBinding()]
param([string]$PythonPath)

$ErrorActionPreference = "Stop"

if (Get-Process -Name "cc-switch" -ErrorAction SilentlyContinue) {
    throw "请先从系统托盘彻底退出 CC Switch，再重新运行卸载器。"
}

$py = Get-Command py -ErrorAction SilentlyContinue
$python = Get-Command python -ErrorAction SilentlyContinue
$bundledPython = $null
if ($PythonPath) {
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        throw "Bundled Python runtime was not found."
    }
    $bundledPython = [System.IO.Path]::GetFullPath($PythonPath)
}
$runtimeRoot = Join-Path $env:LOCALAPPDATA "AIWorkdayTelemetry"
$runtimeDir = Join-Path $runtimeRoot "current"
$backupRoot = Join-Path $runtimeRoot "backups"
if (-not (Test-Path -LiteralPath (Join-Path $runtimeDir "manifest.json"))) {
    throw "未找到本机 AI Workday 安装记录。"
}

$helper = Join-Path $PSScriptRoot "Update-CCSwitchCommonConfig.py"
if ($bundledPython) {
    & $bundledPython $helper uninstall `
        --bundle-dir $runtimeDir `
        --backup-root $backupRoot
} elseif ($py) {
    & $py.Source -3 $helper uninstall `
        --bundle-dir $runtimeDir `
        --backup-root $backupRoot
} elseif ($python) {
    & $python.Source $helper uninstall `
        --bundle-dir $runtimeDir `
        --backup-root $backupRoot
} else {
    throw "未找到 Python 3，无法自动卸载。"
}
if ($LASTEXITCODE -ne 0) { throw "自动卸载失败。" }

Unregister-ScheduledTask -TaskName "SmartBrain AI Conversation Sync" -Confirm:$false -ErrorAction SilentlyContinue
foreach ($fileName in @(
    "ConversationSync.py",
    "Run-ConversationSync.ps1",
    "device-credentials.json",
    "conversation-sync-state.json",
    "conversation-sync-status.json"
)) {
    $path = Join-Path $runtimeDir $fileName
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Force
    }
}
Remove-Item -LiteralPath (Join-Path $runtimeDir "manifest.json") -Force
Write-Host "AI 工作日监控配置已移除。请重新打开 CC Switch。" -ForegroundColor Green
