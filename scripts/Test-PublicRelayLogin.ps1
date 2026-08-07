#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$PublicBaseUrl = "https://39.105.79.0",
    [string]$TemporaryEmail = ""
)

$ErrorActionPreference = "Stop"
$serviceRole = ((
    Get-Content -LiteralPath (Join-Path $PSScriptRoot "..\.env") |
        Where-Object { $_ -like "SUPABASE_SERVICE_ROLE_KEY=*" } |
        Select-Object -First 1
) -split "=", 2)[1]
if (-not $serviceRole) { throw "Missing local Supabase service role key." }
if (-not $TemporaryEmail) {
    $TemporaryEmail = "public-relay-login-$([guid]::NewGuid().ToString('N'))@local.dev"
}

$password = "Relay!$([guid]::NewGuid().ToString('N'))9a"
$adminHeaders = @{
    apikey = $serviceRole
    Authorization = "Bearer $serviceRole"
    "Content-Type" = "application/json"
}
$created = $null
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) (
    "smartbrain-public-login-$([guid]::NewGuid().ToString('N'))"
)
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null

try {
    $createBody = @{
        email = $TemporaryEmail
        password = $password
        email_confirm = $true
        user_metadata = @{ full_name = "Public Relay Smoke" }
    } | ConvertTo-Json -Depth 4
    $created = Invoke-RestMethod -Method Post `
        -Uri "http://127.0.0.1:54321/auth/v1/admin/users" `
        -Headers $adminHeaders `
        -Body $createBody

    $loginBody = @{
        email = $TemporaryEmail
        password = $password
    } | ConvertTo-Json -Compress
    $cookieJar = Join-Path $tempRoot "cookies.txt"
    $loginHeaders = Join-Path $tempRoot "login-headers.txt"
    $loginResponse = Join-Path $tempRoot "login.json"
    $loginRequest = Join-Path $tempRoot "login-request.json"
    [IO.File]::WriteAllText(
        $loginRequest,
        $loginBody,
        (New-Object Text.UTF8Encoding $false)
    )
    $loginStatus = & curl.exe -sS `
        -o $loginResponse `
        -D $loginHeaders `
        -c $cookieJar `
        -w "%{http_code}" `
        -H "Origin: $PublicBaseUrl" `
        -H "Content-Type: application/json" `
        --data-binary "@$loginRequest" `
        "$PublicBaseUrl/auth/login"
    if ($LASTEXITCODE -ne 0) { throw "Public login request failed." }
    if ([int]$loginStatus -ne 200) {
        $errorPayload = Get-Content -Raw -Encoding UTF8 $loginResponse | ConvertFrom-Json
        $safeDetails = @($errorPayload.detail) | ForEach-Object {
            "type=$($_.type) loc=$($_.loc -join '.') msg=$($_.msg)"
        }
        throw "Public login returned HTTP $loginStatus. $($safeDetails -join '; ')"
    }

    $cors = Get-Content $loginHeaders |
        Where-Object { $_ -match "^access-control-allow-origin:" } |
        Select-Object -First 1
    $hasCookie = [bool](Get-Content $loginHeaders |
        Where-Object { $_ -match "^set-cookie:\s*session_id=" })

    $checks = [ordered]@{
        me = "/v4/auth/me"
        catalog = "/v4/projects/catalog"
        usage_options = "/v4/ai-usage/options"
        member_wiki_options = "/v4/member-wiki/options"
    }
    $results = [ordered]@{}
    foreach ($entry in $checks.GetEnumerator()) {
        $bodyPath = Join-Path $tempRoot "$($entry.Key).json"
        $status = & curl.exe -sS `
            -o $bodyPath `
            -b $cookieJar `
            -w "%{http_code}" `
            "$PublicBaseUrl$($entry.Value)"
        if ($LASTEXITCODE -ne 0) { throw "Public check failed: $($entry.Key)" }
        $results[$entry.Key] = @{
            status = [int]$status
            body = Get-Content -Raw -Encoding UTF8 $bodyPath | ConvertFrom-Json
        }
    }
    $traceStatus = & curl.exe -sS `
        -o NUL `
        -b $cookieJar `
        -w "%{http_code}" `
        "$PublicBaseUrl/traces"

    [pscustomobject]@{
        login_status = [int]$loginStatus
        login_set_cookie = $hasCookie
        login_cors = $cors
        me_status = $results.me.status
        me_email = $results.me.body.email
        catalog_status = $results.catalog.status
        project_count = @($results.catalog.body).Count
        usage_options_status = $results.usage_options.status
        usage_employee_count = @($results.usage_options.body.employees).Count
        member_wiki_options_status = $results.member_wiki_options.status
        member_wiki_employee_count = @($results.member_wiki_options.body.employees).Count
        trace_page_status = [int]$traceStatus
    }
} finally {
    if ($created -and $created.id) {
        Invoke-RestMethod -Method Delete `
            -Uri "http://127.0.0.1:54321/auth/v1/admin/users/$($created.id)" `
            -Headers $adminHeaders | Out-Null
        Write-Output "temporary_test_user_deleted=True"
    }
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
