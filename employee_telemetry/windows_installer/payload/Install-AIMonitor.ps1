#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$Username,
    [switch]$PasswordFromStdin,
    [string]$PythonPath,
    [switch]$NonInteractive
)

$ErrorActionPreference = "Stop"
$OutputEncoding = New-Object System.Text.UTF8Encoding $false
[Console]::OutputEncoding = $OutputEncoding
[Console]::InputEncoding = $OutputEncoding

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "== $Message ==" -ForegroundColor Cyan
}

function Get-ApiHostPattern {
    param([object]$Manifest)
    $apiUri = [Uri]$Manifest.api_endpoint
    $authority = $apiUri.Host
    if ($apiUri.Port -gt 0 -and -not (($apiUri.Scheme -eq "http" -and $apiUri.Port -eq 80) -or ($apiUri.Scheme -eq "https" -and $apiUri.Port -eq 443))) {
        $authority = "$authority`:$($apiUri.Port)"
    }
    return "$($apiUri.Scheme)://$authority/*"
}

function Get-SmartBrainBase {
    param([object]$Manifest)
    $apiUri = [Uri]$Manifest.api_endpoint
    return "$($apiUri.Scheme)://$($apiUri.Host):3002"
}

function Get-SmartBrainHostPattern {
    param([object]$Manifest)
    return "$(Get-SmartBrainBase -Manifest $Manifest)/*"
}

function Write-ExtensionConfig {
    param(
        [object]$Manifest,
        [string]$ExtensionDir
    )
    $runtimeManifestPath = Join-Path (Join-Path (Join-Path $env:LOCALAPPDATA "AIWorkdayTelemetry") "current") "manifest.json"
    $runtimeManifest = $null
    if (Test-Path -LiteralPath $runtimeManifestPath) {
        $runtimeManifest = Get-Content -LiteralPath $runtimeManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    $deviceId = ""
    $employeeId = ""
    $employeeName = ""
    if ($runtimeManifest) {
        $deviceId = [string]$runtimeManifest.device_id
        $employeeId = [string]$runtimeManifest.employee_id
        $employeeName = [string]$runtimeManifest.employee_name
    }
    $config = [ordered]@{
        apiBase = [string]$Manifest.api_endpoint
        projectId = [string]$Manifest.project_id
        defaultEmailDomain = [string]$Manifest.default_email_domain
        source = "chatgpt_web"
        smartBrainBase = (Get-SmartBrainBase -Manifest $Manifest)
        packageVersion = [string]$Manifest.package_version
        deviceId = $deviceId
        employeeId = $employeeId
        employeeName = $employeeName
    } | ConvertTo-Json -Compress
    Set-Content -LiteralPath (Join-Path $ExtensionDir "config.js") `
        -Encoding UTF8 `
        -Value "globalThis.AI_MONITOR_CONFIG = $config;"

    $manifestPath = Join-Path $ExtensionDir "manifest.json"
    $extensionManifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $extensionManifest.host_permissions = @(
        "https://chatgpt.com/*",
        "https://chat.openai.com/*",
        (Get-ApiHostPattern -Manifest $Manifest),
        (Get-SmartBrainHostPattern -Manifest $Manifest)
    )
    $extensionManifest.content_scripts = @(
        [ordered]@{
            matches = @("https://chatgpt.com/*", "https://chat.openai.com/*")
            js = @("config.js", "monitor-core.js", "content.js")
            css = @("content.css")
            run_at = "document_idle"
        },
        [ordered]@{
            matches = @((Get-SmartBrainHostPattern -Manifest $Manifest))
            js = @("config.js", "smartbrain-bridge.js")
            run_at = "document_idle"
        }
    )
    $extensionManifest | ConvertTo-Json -Depth 10 |
        Set-Content -LiteralPath $manifestPath -Encoding UTF8
}

function Find-Browser {
    param([string[]]$Candidates)
    foreach ($candidate in $Candidates) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return $null
}

function New-MonitoredShortcut {
    param(
        [string]$Name,
        [string]$BrowserPath,
        [string]$ExtensionDir,
        [string]$ProfileDir,
        [string]$Url = "https://chatgpt.com/"
    )
    if (-not $BrowserPath) { return $false }
    New-Item -ItemType Directory -Force -Path $ProfileDir | Out-Null
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktop "$Name.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $BrowserPath
    $shortcut.Arguments = "--user-data-dir=`"$ProfileDir`" --no-first-run --disable-extensions-except=`"$ExtensionDir`" --load-extension=`"$ExtensionDir`" `"$Url`""
    $shortcut.WorkingDirectory = Split-Path -Parent $BrowserPath
    $shortcut.IconLocation = $BrowserPath
    $shortcut.Description = "ChatGPT Web with SmartBrain AI Monitor extension"
    $shortcut.Save()
    return $true
}

$bundleManifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot "manifest.json") -Raw -Encoding UTF8 |
    ConvertFrom-Json

Write-Step "1/3 Enroll employee and configure CC Switch"
$telemetryArguments = @{}
if ($Username) { $telemetryArguments.Username = $Username }
if ($PasswordFromStdin) { $telemetryArguments.PasswordFromStdin = $true }
if ($PythonPath) { $telemetryArguments.PythonPath = $PythonPath }
& (Join-Path $PSScriptRoot "Install-AIWorkdayTelemetry.ps1") @telemetryArguments
if ($LASTEXITCODE -ne 0) {
    throw "CC Switch / Workday telemetry configuration failed."
}

Write-Step "2/3 Install ChatGPT web monitor extension"
$runtimeRoot = Join-Path $env:LOCALAPPDATA "AIMonitor"
$extensionDir = Join-Path $runtimeRoot "chatgpt-web-extension"
$profileRoot = Join-Path $runtimeRoot "browser-profiles"
New-Item -ItemType Directory -Force -Path $extensionDir | Out-Null
Copy-Item -Path (Join-Path $PSScriptRoot "chatgpt-web-extension\*") `
    -Destination $extensionDir `
    -Recurse `
    -Force
Write-ExtensionConfig -Manifest $bundleManifest -ExtensionDir $extensionDir

Write-Step "3/3 Create monitored ChatGPT browser shortcuts"
$smartBrainSetupUrl = "$(Get-SmartBrainBase -Manifest $bundleManifest)/monitor/setup"
$edgePath = Find-Browser @(
    (Join-Path ${env:ProgramFiles(x86)} "Microsoft\Edge\Application\msedge.exe"),
    (Join-Path $env:ProgramFiles "Microsoft\Edge\Application\msedge.exe"),
    (Join-Path $env:LOCALAPPDATA "Microsoft\Edge\Application\msedge.exe")
)
$chromePath = Find-Browser @(
    (Join-Path ${env:ProgramFiles} "Google\Chrome\Application\chrome.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe"),
    (Join-Path $env:LOCALAPPDATA "Google\Chrome\Application\chrome.exe")
)
$created = @()
if (New-MonitoredShortcut -Name "ChatGPT Monitored - Edge" -BrowserPath $edgePath -ExtensionDir $extensionDir -ProfileDir (Join-Path $profileRoot "edge-chatgpt")) {
    $created += "Edge"
}
if (New-MonitoredShortcut -Name "ChatGPT Monitored - Chrome" -BrowserPath $chromePath -ExtensionDir $extensionDir -ProfileDir (Join-Path $profileRoot "chrome-chatgpt")) {
    $created += "Chrome"
}
if ($edgePath) {
    New-MonitoredShortcut -Name "SmartBrain Monitor Setup - Edge" -BrowserPath $edgePath -ExtensionDir $extensionDir -ProfileDir (Join-Path $profileRoot "edge-setup") -Url $smartBrainSetupUrl | Out-Null
}
if ($chromePath) {
    New-MonitoredShortcut -Name "SmartBrain Monitor Setup - Chrome" -BrowserPath $chromePath -ExtensionDir $extensionDir -ProfileDir (Join-Path $profileRoot "chrome-setup") -Url $smartBrainSetupUrl | Out-Null
}

Write-Host ""
Write-Host "AI Monitor universal installation finished." -ForegroundColor Green
Write-Host "CC Switch: reopen CC Switch, switch Claude and Codex providers once, then restart Claude Code/Codex."
Write-Host "Codex / Claude conversations: the latest 7 days sync now, then every two minutes in the background."
if ($created.Count -gt 0) {
    Write-Host "ChatGPT Web: use desktop shortcuts: $($created -join ', '). These shortcuts use an isolated browser profile so the extension loads reliably."
} else {
    Write-Host "Edge or Chrome was not found. Extension folder is ready for manual loading: $extensionDir" -ForegroundColor Yellow
}
Write-Host "Personal ChatGPT desktop app is not locally captured. Use the monitored ChatGPT Web shortcut."
