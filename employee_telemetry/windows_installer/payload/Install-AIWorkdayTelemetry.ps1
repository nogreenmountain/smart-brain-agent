#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$Username,
    [switch]$PasswordFromStdin,
    [string]$PythonPath
)

$ErrorActionPreference = "Stop"
$OutputEncoding = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = $OutputEncoding
[Console]::InputEncoding = $OutputEncoding

function Find-Python {
    if ($PythonPath) {
        if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
            throw "Bundled Python runtime was not found."
        }
        return @([System.IO.Path]::GetFullPath($PythonPath))
    }
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
if ($manifest.trusted_root_ca_file) {
    $caPath = Join-Path $PSScriptRoot ([string]$manifest.trusted_root_ca_file)
    if (-not (Test-Path -LiteralPath $caPath -PathType Leaf)) {
        throw "Trusted SmartBrain root certificate was not found in the installer."
    }
    $certificate = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($caPath)
    $store = New-Object System.Security.Cryptography.X509Certificates.X509Store("Root", "CurrentUser")
    try {
        $store.Open([System.Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
        $alreadyTrusted = $store.Certificates | Where-Object {
            $_.Thumbprint -eq $certificate.Thumbprint
        }
        if (-not $alreadyTrusted) {
            $store.Add($certificate)
        }
    } finally {
        $store.Close()
    }
}
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
    $enrollArguments = @(
        "--bundle-dir", $PSScriptRoot,
        "--runtime-dir", $runtimeDir
    )
    if ($Username) {
        $enrollArguments += @("--username", $Username)
    }
    if ($PasswordFromStdin) {
        $enrollArguments += "--password-stdin"
    }
    Invoke-PythonHelper `
        -Script (Join-Path $PSScriptRoot "Enroll-AIWorkday.py") `
        -Arguments $enrollArguments
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

$syncSource = Join-Path $PSScriptRoot "ConversationSync.py"
$syncScript = Join-Path $runtimeDir "ConversationSync.py"
$usageSyncSource = Join-Path $PSScriptRoot "CCSwitchUsageSync.py"
$usageSyncScript = Join-Path $runtimeDir "CCSwitchUsageSync.py"
$syncRunner = Join-Path $runtimeDir "Run-ConversationSync.ps1"
$syncRunnerVbs = Join-Path $runtimeDir "Run-ConversationSync.vbs"
Copy-Item -LiteralPath $syncSource -Destination $syncScript -Force
Copy-Item -LiteralPath $usageSyncSource -Destination $usageSyncScript -Force
$pythonPrefix = if ($pythonCommand.Count -gt 1) { "$($pythonCommand[1]) " } else { "" }
$runnerContent = @"
`$ErrorActionPreference = "SilentlyContinue"
& "$($pythonCommand[0])" $pythonPrefix`"$syncScript`" --runtime-dir `"$runtimeDir`" | Out-Null
& "$($pythonCommand[0])" $pythonPrefix`"$usageSyncScript`" --runtime-dir `"$runtimeDir`" --trigger automatic | Out-Null
"@
Set-Content -LiteralPath $syncRunner -Encoding UTF8 -Value $runnerContent
$vbsRunnerContent = @(
    'Set shell = CreateObject("WScript.Shell")'
    ('shell.Run "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File " & Chr(34) & "' + $syncRunner + '" & Chr(34), 0, False')
)
Set-Content -LiteralPath $syncRunnerVbs -Encoding Unicode -Value $vbsRunnerContent

$taskName = "SmartBrain AI Conversation Sync"
try {
    $action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$syncRunnerVbs`""
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 2) -RepetitionDuration (New-TimeSpan -Days 3650)
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
} catch {
    Write-Host "AI conversation sync scheduled task could not be created: $($_.Exception.Message)" -ForegroundColor Yellow
}

try {
    $syncArguments = @()
    if ($pythonCommand.Count -gt 1) { $syncArguments += $pythonCommand[1] }
    $syncArguments += @($syncScript, "--runtime-dir", $runtimeDir)
    & $pythonCommand[0] @syncArguments
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Initial AI conversation sync found old records it could not upload; background sync will retry." -ForegroundColor Yellow
    }
} catch {
    Write-Host "Initial AI conversation sync will retry in the background." -ForegroundColor Yellow
}
try {
    $usageSyncArguments = @()
    if ($pythonCommand.Count -gt 1) { $usageSyncArguments += $pythonCommand[1] }
    $usageSyncArguments += @($usageSyncScript, "--runtime-dir", $runtimeDir, "--trigger", "automatic")
    & $pythonCommand[0] @usageSyncArguments | Out-Null
} catch {
    Write-Host "Initial CC Switch usage sync will retry in the background." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "AI 工作日监控已安装。" -ForegroundColor Green
Write-Host "请重新打开 CC Switch，分别切换一次 Claude 和 Codex 当前供应商，然后重启 Claude Code/Codex。"
$global:LASTEXITCODE = 0
