#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$PublicBaseUrl = "https://39.105.79.0",
    [string]$InstalledMonitorPath = "$env:LOCALAPPDATA\SmartBrainTemporaryTokenMonitor\SmartBrainTemporaryTokenMonitorSetup.exe"
)

$ErrorActionPreference = "Stop"
$serviceRole = (((Get-Content -LiteralPath (Join-Path $PSScriptRoot "..\.env") |
    Where-Object { $_ -like "SUPABASE_SERVICE_ROLE_KEY=*" } | Select-Object -First 1) -split "=", 2)[1])
if (-not $serviceRole) { throw "Missing local Supabase service role key." }

$suffix = [guid]::NewGuid().ToString("N")
$email = "temporary-token-monitor-$suffix@local.dev"
$employeeId = "temporary-token-monitor-$suffix"
$password = "Temporary!${suffix}9a"
$deviceId = "temporary-e2e-$suffix"
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) "smartbrain-temporary-token-$suffix"
$user = $null
$session = $null
$probe = $null
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
$adminHeaders = @{ apikey=$serviceRole; Authorization="Bearer $serviceRole"; "Content-Type"="application/json" }

function Invoke-PublicJson([string]$Method, [string]$Path, [string]$CookiePath, [object]$Body=$null) {
    $responsePath = Join-Path $tempRoot "$([guid]::NewGuid().ToString('N')).response.json"
    $args = @("-sS", "-o", $responsePath, "-b", $CookiePath, "-w", "%{http_code}", "-X", $Method)
    if ($null -ne $Body) {
        $requestPath = Join-Path $tempRoot "$([guid]::NewGuid().ToString('N')).request.json"
        [IO.File]::WriteAllText($requestPath, ($Body | ConvertTo-Json -Depth 10 -Compress), (New-Object Text.UTF8Encoding $false))
        $args += @("-H", "Content-Type: application/json", "--data-binary", "@$requestPath")
    }
    $args += "$PublicBaseUrl$Path"
    $status = & curl.exe @args
    if ($LASTEXITCODE -ne 0 -or [int]$status -lt 200 -or [int]$status -ge 300) {
        $payload = if (Test-Path $responsePath) { Get-Content -Raw -Encoding UTF8 $responsePath } else { "" }
        throw "$Method $Path failed (HTTP $status): $payload"
    }
    if ((Get-Item $responsePath).Length -eq 0) { return $null }
    return Get-Content -Raw -Encoding UTF8 $responsePath | ConvertFrom-Json
}

try {
    $user = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:54321/auth/v1/admin/users" -Headers $adminHeaders -Body (@{
        email=$email; password=$password; email_confirm=$true; user_metadata=@{ full_name="Temporary Token E2E" }
    } | ConvertTo-Json -Depth 4)
    $sql = @"
INSERT INTO public.users (id, email, full_name, is_system_admin)
VALUES ('$($user.id)'::uuid, '$email', 'Temporary Token E2E', false)
ON CONFLICT (id) DO UPDATE SET full_name=EXCLUDED.full_name;
"@
    $sql | docker exec -i supabase_db_database psql -U postgres -d postgres -v ON_ERROR_STOP=1 | Out-Null

    $cookies = Join-Path $tempRoot "cookies.txt"
    $loginBody = Join-Path $tempRoot "login.json"
    [IO.File]::WriteAllText($loginBody, (@{email=$email;password=$password}|ConvertTo-Json -Compress), (New-Object Text.UTF8Encoding $false))
    $loginStatus = & curl.exe -sS -o NUL -c $cookies -w "%{http_code}" -H "Origin: $PublicBaseUrl" -H "Content-Type: application/json" --data-binary "@$loginBody" "$PublicBaseUrl/auth/login"
    if ([int]$loginStatus -ne 200) { throw "Login failed: $loginStatus" }

    $probe = Invoke-PublicJson "POST" "/v4/ai-usage/temporary-monitor-probes" $cookies
    $blockedResponse = Join-Path $tempRoot "blocked-start.json"
    $blockedBody = Join-Path $tempRoot "blocked-start-request.json"
    [IO.File]::WriteAllText($blockedBody, (@{installation_probe_id=$probe.id;stop_mode="manual_only"}|ConvertTo-Json -Compress), (New-Object Text.UTF8Encoding $false))
    $blockedStatus = & curl.exe -k -sS -o $blockedResponse -b $cookies -w "%{http_code}" -H "Content-Type: application/json" --data-binary "@$blockedBody" "$PublicBaseUrl/v4/ai-usage/shared-sessions/start"
    if ([int]$blockedStatus -ne 409) { throw "Undetected probe unexpectedly started a session: $blockedStatus" }

    if (-not (Test-Path -LiteralPath $InstalledMonitorPath -PathType Leaf)) {
        throw "Installed temporary Token Monitor was not found: $InstalledMonitorPath"
    }
    $probeUri = "smartbrain-temp-token://session?action=status&probe_id=$([Uri]::EscapeDataString([string]$probe.id))&probe_token=$([Uri]::EscapeDataString([string]$probe.probe_token))"
    $probeProcess = Start-Process -FilePath $InstalledMonitorPath -ArgumentList @("--protocol", $probeUri) -PassThru -Wait -WindowStyle Hidden
    if ($probeProcess.ExitCode -ne 0) { throw "Installed temporary Token Monitor probe failed: $($probeProcess.ExitCode)" }
    $confirmed = Invoke-PublicJson "GET" "/v4/ai-usage/temporary-monitor-probes/$($probe.id)" $cookies
    if ($confirmed.status -ne "detected") { throw "Temporary Monitor probe was not detected." }
    $deviceId = [string]$confirmed.device_id
    if (-not $deviceId.StartsWith("temp-token-")) { throw "Temporary Monitor returned an invalid device id." }
    $session = Invoke-PublicJson "POST" "/v4/ai-usage/shared-sessions/start" $cookies @{
        installation_probe_id=$probe.id; stop_mode="manual_only"
    }
    if ($session.project_id) { throw "Temporary session unexpectedly has project attribution." }
    $started = [DateTimeOffset]::UtcNow.AddSeconds(-2)
    $activation = Invoke-PublicJson "POST" "/v4/ai-usage/shared-sessions/device-activate" $cookies @{
        session_id=$session.id; activation_token=$session.activation_token; device_id=$deviceId
        started_at=$started.ToString("o"); start_watermark="0"
    }
    $requestAt = [DateTimeOffset]::UtcNow.AddSeconds(-1).ToString("o")
    $syncBody = @{
        session_id=$session.id; activation_token=$session.activation_token; device_id=$deviceId
        checked_at=[DateTimeOffset]::UtcNow.ToString("o"); last_watermark="1"
        requests=@(@{request_id="request-1";requested_at=$requestAt;app_type="codex";provider_id="openai";model="gpt-5";request_model="gpt-5";pricing_model="gpt-5";status_code=200;input_tokens=100;output_tokens=20;cache_read_tokens=30;cache_creation_tokens=0;total_tokens=120;total_cost_usd=0.1;input_token_semantics=1})
    }
    $first = Invoke-PublicJson "POST" "/v4/ai-usage/shared-sessions/device-sync" $cookies $syncBody
    $duplicate = Invoke-PublicJson "POST" "/v4/ai-usage/shared-sessions/device-sync" $cookies $syncBody
    if ($first.request_count -ne 1 -or $duplicate.request_count -ne 1) { throw "Incremental dedupe failed." }
    $stopped = Invoke-PublicJson "POST" "/v4/ai-usage/shared-sessions/$($session.id)/stop" $cookies @{reason="manual"}
    $final = Invoke-PublicJson "POST" "/v4/ai-usage/shared-sessions/device-finalize" $cookies @{
        session_id=$session.id;activation_token=$session.activation_token;device_id=$deviceId
        stopped_at=$stopped.actual_stop_at;stop_reason="manual";requests=@()
    }
    if ($final.request_count -ne 1 -or $final.total_tokens -ne 120) { throw "Final tail aggregation failed." }
    $today = [DateTimeOffset]::Now.ToString("yyyy-MM-dd")
    $leaderboard = Invoke-PublicJson "GET" "/v4/ai-usage/leaderboard?start_date=$today&end_date=$today" $cookies
    $member = @($leaderboard.members) | Where-Object { $_.employee_id -eq $employeeId } | Select-Object -First 1
    if (-not $member -or $member.total_tokens -ne 120 -or $member.official_cc_switch) { throw "Leaderboard attribution failed." }
    [pscustomobject]@{ login=200; undetected_start=$blockedStatus; probe_status=$confirmed.status; project_id=$session.project_id; incremental_requests=$first.request_count; duplicate_requests=$duplicate.request_count; finalized_requests=$final.request_count; finalized_tokens=$final.total_tokens; official_cc_switch=$member.official_cc_switch }
} finally {
    if ($session) {
        "DELETE FROM public.cc_switch_attribution_sessions WHERE id='$($session.id)'::uuid;" | docker exec -i supabase_db_database psql -U postgres -d postgres -v ON_ERROR_STOP=1 | Out-Null
    }
    if ($user -and $user.id) {
        & (Join-Path $PSScriptRoot "Remove-TemporarySupabaseUser.ps1") -UserId $user.id -ServiceRoleKey $serviceRole | Out-Null
    }
    if (Test-Path $tempRoot) { Remove-Item -LiteralPath $tempRoot -Recurse -Force }
    Write-Output "temporary_token_monitor_e2e_deleted=True"
}
