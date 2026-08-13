#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$PublicBaseUrl = "https://39.105.79.0"
)

$ErrorActionPreference = "Stop"
$serviceRole = ((
    Get-Content -LiteralPath (Join-Path $PSScriptRoot "..\.env") |
        Where-Object { $_ -like "SUPABASE_SERVICE_ROLE_KEY=*" } |
        Select-Object -First 1
) -split "=", 2)[1]
if (-not $serviceRole) { throw "Missing local Supabase service role key." }

$suffix = [guid]::NewGuid().ToString("N")
$memberEmail = "project-request-member-$suffix@local.dev"
$adminEmail = "project-request-admin-$suffix@local.dev"
$password = "Project!${suffix}9a"
$projectName = "project-request-smoke-$suffix"
$adminHeaders = @{
    apikey = $serviceRole
    Authorization = "Bearer $serviceRole"
    "Content-Type" = "application/json"
}
$member = $null
$admin = $null
$requestId = $null
$projectId = $null
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) "smartbrain-project-request-$suffix"
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null

function New-TemporaryUser([string]$Email, [string]$DisplayName) {
    $body = @{
        email = $Email
        password = $password
        email_confirm = $true
        user_metadata = @{ full_name = $DisplayName }
    } | ConvertTo-Json -Depth 4
    Invoke-RestMethod -Method Post `
        -Uri "http://127.0.0.1:54321/auth/v1/admin/users" `
        -Headers $adminHeaders `
        -Body $body
}

function New-PublicLogin([string]$Email, [string]$CookiePath) {
    $requestPath = "$CookiePath.request.json"
    $responsePath = "$CookiePath.response.json"
    [IO.File]::WriteAllText(
        $requestPath,
        (@{ email = $Email; password = $password } | ConvertTo-Json -Compress),
        (New-Object Text.UTF8Encoding $false)
    )
    $status = & curl.exe -sS -o $responsePath -c $CookiePath -w "%{http_code}" `
        -H "Origin: $PublicBaseUrl" -H "Content-Type: application/json" `
        --data-binary "@$requestPath" "$PublicBaseUrl/auth/login"
    if ($LASTEXITCODE -ne 0 -or [int]$status -ne 200) {
        throw "Public login failed for temporary user (HTTP $status)."
    }
}

function Invoke-PublicJson(
    [string]$Method,
    [string]$Path,
    [string]$CookiePath,
    [object]$Body = $null
) {
    $responsePath = Join-Path $tempRoot "$([guid]::NewGuid().ToString('N')).response.json"
    $arguments = @("-sS", "-o", $responsePath, "-b", $CookiePath, "-w", "%{http_code}", "-X", $Method)
    if ($null -ne $Body) {
        $requestPath = Join-Path $tempRoot "$([guid]::NewGuid().ToString('N')).request.json"
        [IO.File]::WriteAllText(
            $requestPath,
            ($Body | ConvertTo-Json -Depth 8 -Compress),
            (New-Object Text.UTF8Encoding $false)
        )
        $arguments += @("-H", "Content-Type: application/json", "--data-binary", "@$requestPath")
    }
    $arguments += "$PublicBaseUrl$Path"
    $status = & curl.exe @arguments
    if ($LASTEXITCODE -ne 0 -or [int]$status -lt 200 -or [int]$status -ge 300) {
        $payload = if (Test-Path -LiteralPath $responsePath) { Get-Content -Raw -Encoding UTF8 $responsePath } else { "" }
        throw "$Method $Path failed (HTTP $status): $payload"
    }
    if ((Get-Item -LiteralPath $responsePath).Length -eq 0) { return $null }
    Get-Content -Raw -Encoding UTF8 $responsePath | ConvertFrom-Json
}

try {
    $member = New-TemporaryUser $memberEmail "Project Request Member"
    $admin = New-TemporaryUser $adminEmail "Project Request Admin"
    $orgId = docker exec supabase_db_database psql -U postgres -d postgres -Atc `
        "SELECT id::text FROM public.orgs ORDER BY id LIMIT 1;"
    if (-not $orgId) { throw "No organization available for project request smoke test." }

    $setupSql = @"
INSERT INTO public.users (id, email, full_name, is_system_admin)
VALUES
  ('$($member.id)'::uuid, '$memberEmail', 'Project Request Member', false),
  ('$($admin.id)'::uuid, '$adminEmail', 'Project Request Admin', true)
ON CONFLICT (id) DO UPDATE
SET email = EXCLUDED.email,
    full_name = EXCLUDED.full_name,
    is_system_admin = EXCLUDED.is_system_admin;
INSERT INTO public.user_orgs (user_id, org_id, role, user_email)
VALUES ('$($member.id)'::uuid, '$orgId'::uuid, 'business_user', '$memberEmail')
ON CONFLICT (user_id, org_id) DO UPDATE
SET role = EXCLUDED.role,
    user_email = EXCLUDED.user_email;
"@
    $setupSql | docker exec -i supabase_db_database psql -v ON_ERROR_STOP=1 -U postgres -d postgres | Out-Null

    $memberCookies = Join-Path $tempRoot "member.cookies"
    $adminCookies = Join-Path $tempRoot "admin.cookies"
    New-PublicLogin $memberEmail $memberCookies
    New-PublicLogin $adminEmail $adminCookies

    $submitted = Invoke-PublicJson "POST" "/v4/project-requests" $memberCookies @{
        org_id = $orgId
        name = $projectName
        environment = "development"
        department_id = "research"
        completed_at = "2026-12-31"
        reason = "Public smoke test for an ordinary member project request."
    }
    $requestId = $submitted.id
    if ($submitted.status -ne "pending") { throw "Submitted request was not pending." }

    $memberRequests = @(Invoke-PublicJson "GET" "/v4/project-requests" $memberCookies)
    $adminRequests = @(Invoke-PublicJson "GET" "/v4/project-requests" $adminCookies)
    if (-not ($memberRequests | Where-Object { $_.id -eq $requestId })) { throw "Member cannot see own request." }
    if (-not ($adminRequests | Where-Object { $_.id -eq $requestId })) { throw "System admin cannot see pending request." }

    $reviewed = Invoke-PublicJson "POST" "/v4/project-requests/$requestId/review" $adminCookies @{
        decision = "approve"
        comment = "Approved by public smoke test"
    }
    $projectId = $reviewed.created_project_id
    if ($reviewed.status -ne "approved" -or -not $projectId) { throw "Approval did not create a project." }

    $projects = @(Invoke-PublicJson "GET" "/v4/projects" $memberCookies)
    $createdProject = $projects | Where-Object { $_.id -eq $projectId } | Select-Object -First 1
    if (-not $createdProject -or $createdProject.role -ne "owner") {
        throw "Approved requester did not become project owner."
    }

    [pscustomobject]@{
        member_login = 200
        admin_login = 200
        submitted_status = $submitted.status
        member_visible = $true
        admin_visible = $true
        reviewed_status = $reviewed.status
        created_project_id = $projectId
        requester_project_role = $createdProject.role
    }
} finally {
    if ($requestId) {
        docker exec supabase_db_database psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c `
            "DELETE FROM public.project_creation_requests WHERE id = '$requestId'::uuid;" | Out-Null
    }
    if ($projectId) {
        docker exec supabase_db_database psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c `
            "DELETE FROM public.projects WHERE id = '$projectId'::uuid;" | Out-Null
    }
    foreach ($createdUser in @($member, $admin)) {
        if ($createdUser -and $createdUser.id) {
            & (Join-Path $PSScriptRoot "Remove-TemporarySupabaseUser.ps1") `
                -UserId $createdUser.id `
                -ServiceRoleKey $serviceRole | Out-Null
        }
    }
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
    Write-Output "temporary_project_request_data_deleted=True"
}
