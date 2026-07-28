#Requires -Version 5.1
$ErrorActionPreference = "Stop"

function Find-Python {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return @($py.Source, "-3") }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return @($python.Source) }
    throw "未找到 Python 3。请先安装 Python 3，再重新运行本安装器。"
}

if (Get-Process -Name "cc-switch" -ErrorAction SilentlyContinue) {
    throw "请先从系统托盘彻底退出 CC Switch，再重新运行安装器。"
}

$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot "manifest.json") -Raw |
    ConvertFrom-Json
$uri = [Uri]$manifest.collector_endpoint
$port = if ($uri.Port -gt 0) { $uri.Port } elseif ($uri.Scheme -eq "https") { 443 } else { 80 }
$probe = Test-NetConnection -ComputerName $uri.Host -Port $port -WarningAction SilentlyContinue
if (-not $probe.TcpTestSucceeded) {
    throw "无法连接遥测服务器 $($uri.Host):$port，请检查局域网、防火墙或 VPN。"
}

$pythonCommand = @(Find-Python)
$runtimeRoot = Join-Path $env:LOCALAPPDATA "AIWorkdayTelemetry"
$runtimeDir = Join-Path $runtimeRoot "current"
$backupRoot = Join-Path $runtimeRoot "backups"
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null

function Invoke-PythonHelper {
    param([string]$Script, [string[]]$Arguments)
    $allArguments = @()
    if ($pythonCommand.Count -gt 1) { $allArguments += $pythonCommand[1] }
    $allArguments += $Script
    $allArguments += $Arguments
    & $pythonCommand[0] @allArguments
    if ($LASTEXITCODE -ne 0) {
        throw "员工身份验证或配置写入失败。"
    }
}

$sensitiveFiles = @(
    (Join-Path $runtimeDir "Claude-Common-Config.json"),
    (Join-Path $runtimeDir "Codex-Common-Config.toml")
)
try {
    Invoke-PythonHelper `
        -Script (Join-Path $PSScriptRoot "Enroll-AIWorkday.py") `
        -Arguments @(
            "--bundle-dir", $PSScriptRoot,
            "--runtime-dir", $runtimeDir
        )
    Invoke-PythonHelper `
        -Script (Join-Path $PSScriptRoot "Update-CCSwitchCommonConfig.py") `
        -Arguments @(
            "install",
            "--bundle-dir", $runtimeDir,
            "--backup-root", $backupRoot
        )
} finally {
    foreach ($sensitiveFile in $sensitiveFiles) {
        if (Test-Path -LiteralPath $sensitiveFile) {
            Remove-Item -LiteralPath $sensitiveFile -Force
        }
    }
}

Write-Host ""
Write-Host "AI 工作日监控已安装。" -ForegroundColor Green
Write-Host "请重新打开 CC Switch，分别切换一次 Claude 和 Codex 当前供应商，然后重启 Claude Code/Codex。"
