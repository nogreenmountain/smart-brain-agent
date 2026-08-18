#Requires -Version 5.1
[CmdletBinding()]
param([string]$PublicBaseUrl = "https://39.105.79.0")

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$serviceRole = (((Get-Content (Join-Path $repoRoot ".env") | Where-Object { $_ -like "SUPABASE_SERVICE_ROLE_KEY=*" } | Select-Object -First 1) -split "=", 2)[1])
if (-not $serviceRole) { throw "Missing SUPABASE_SERVICE_ROLE_KEY" }

function Invoke-Sql([string]$Sql) {
    $result = & docker exec supabase_db_database psql -U postgres -d postgres -At -v ON_ERROR_STOP=1 -c $Sql
    if ($LASTEXITCODE -ne 0) { throw "SQL failed" }
    return ([string]($result -join [Environment]::NewLine)).Trim()
}

function Invoke-SupabaseAdmin([string]$Method, [string]$Path, [string]$Body, [string]$Bearer = $serviceRole) {
    $python = @'
import base64, os, sys, urllib.request
method, path = sys.argv[1:3]
payload = base64.b64decode(os.environ.get("SB_BODY", ""))
req = urllib.request.Request(
    "http://supabase_kong_database:8000" + path,
    data=payload or None,
    method=method,
    headers={
        "apikey": os.environ["SB_SERVICE_ROLE"],
        "Authorization": "Bearer " + os.environ["SB_BEARER"],
        "Content-Type": "application/json",
    },
)
with urllib.request.urlopen(req, timeout=30) as response:
    sys.stdout.buffer.write(response.read())
'@
    $oldService = $env:SB_SERVICE_ROLE
    $oldBearer = $env:SB_BEARER
    $oldBody = $env:SB_BODY
    try {
        $env:SB_SERVICE_ROLE = $serviceRole
        $env:SB_BEARER = $Bearer
        $env:SB_BODY = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Body))
        $raw = $python | docker exec -i -e SB_SERVICE_ROLE -e SB_BEARER -e SB_BODY agentops-api-1 /app/.venv/bin/python - $Method $Path
        if ($LASTEXITCODE -ne 0) { throw "Supabase admin request failed: $Method $Path" }
        $text = [string]($raw -join [Environment]::NewLine)
        if ($text.Trim()) { return $text | ConvertFrom-Json }
        return $null
    } finally {
        if ($null -eq $oldService) { Remove-Item Env:SB_SERVICE_ROLE -ErrorAction SilentlyContinue } else { $env:SB_SERVICE_ROLE = $oldService }
        if ($null -eq $oldBearer) { Remove-Item Env:SB_BEARER -ErrorAction SilentlyContinue } else { $env:SB_BEARER = $oldBearer }
        if ($null -eq $oldBody) { Remove-Item Env:SB_BODY -ErrorAction SilentlyContinue } else { $env:SB_BODY = $oldBody }
    }
}

function Get-JwtSessionId([string]$AccessToken) {
    $payload = $AccessToken.Split('.')[1].Replace('-', '+').Replace('_', '/')
    while (($payload.Length % 4) -ne 0) { $payload += '=' }
    return [string](([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payload)) | ConvertFrom-Json).session_id)
}

function Write-Utf8([string]$Path, [string]$Value) {
    [IO.File]::WriteAllText($Path, $Value, (New-Object Text.UTF8Encoding $false))
}

function Invoke-JsonApi {
    param(
        [string]$Method,
        [string]$Path,
        [string]$CookieJar,
        [object]$Body = $null,
        [int[]]$Expected = @(200)
    )
    $id = [guid]::NewGuid().ToString('N')
    $requestPath = Join-Path $script:tempRoot "$id-request.json"
    $responsePath = Join-Path $script:tempRoot "$id-response.json"
    $arguments = @('-sS', '-o', $responsePath, '-b', $CookieJar, '-w', '%{http_code}', '-X', $Method)
    if ($null -ne $Body) {
        Write-Utf8 $requestPath ($Body | ConvertTo-Json -Depth 8 -Compress)
        $arguments += @('-H', 'Content-Type: application/json', '--data-binary', "@$requestPath")
    }
    $arguments += "$PublicBaseUrl$Path"
    $status = [int](& curl.exe @arguments)
    [string]$raw = ''
    if (Test-Path $responsePath) {
        $loaded = Get-Content -Raw -Encoding UTF8 $responsePath
        if ($null -ne $loaded) { $raw = [string]$loaded }
    }
    if ($status -notin $Expected) { throw "$Method $Path returned HTTP $status - $raw" }
    $json = if ($raw.Trim()) { $raw | ConvertFrom-Json } else { $null }
    return [pscustomobject]@{ Status = $status; Json = $json; Raw = $raw; ResponsePath = $responsePath }
}

function Get-CookieHeader([string]$CookieJar) {
    $cookies = foreach ($rawLine in Get-Content $CookieJar) {
        $line = [string]$rawLine
        if ($line.StartsWith('#HttpOnly_')) {
            $line = $line.Substring('#HttpOnly_'.Length)
        } elseif ($line.StartsWith('#') -or -not $line.Trim()) {
            continue
        }
        $parts = $line -split [char]9
        if ($parts.Count -ge 7) { "$($parts[5])=$($parts[6])" }
    }
    return ($cookies -join '; ')
}

function Invoke-ConcurrentJsonApi {
    param([string]$Path, [string]$CookieJar, [object]$Body, [int]$Count = 5)
    $python = @'
import base64, concurrent.futures, json, os, urllib.error, urllib.request

path = os.environ["SMOKE_PATH"]
cookie = os.environ["SMOKE_COOKIE"]
payload = base64.b64decode(os.environ["SMOKE_BODY"])
count = int(os.environ["SMOKE_COUNT"])

def call(index):
    request = urllib.request.Request(
        "http://127.0.0.1:8000" + path,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "Cookie": cookie},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return {"index": index, "status": response.status, "body": response.read().decode("utf-8")}
    except urllib.error.HTTPError as error:
        return {"index": index, "status": error.code, "body": error.read().decode("utf-8")}

with concurrent.futures.ThreadPoolExecutor(max_workers=count) as executor:
    results = list(executor.map(call, range(count)))
print(json.dumps(results, ensure_ascii=False))
'@
    $oldPath = $env:SMOKE_PATH
    $oldCookie = $env:SMOKE_COOKIE
    $oldBody = $env:SMOKE_BODY
    $oldCount = $env:SMOKE_COUNT
    try {
        $env:SMOKE_PATH = $Path
        $env:SMOKE_COOKIE = Get-CookieHeader $CookieJar
        $env:SMOKE_BODY = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($Body | ConvertTo-Json -Depth 8 -Compress)))
        $env:SMOKE_COUNT = [string]$Count
        $raw = $python | docker exec -i -e SMOKE_PATH -e SMOKE_COOKIE -e SMOKE_BODY -e SMOKE_COUNT agentops-api-1 /app/.venv/bin/python -
        if ($LASTEXITCODE -ne 0) { throw 'Concurrent API probe failed to run' }
        return ([string]($raw -join [Environment]::NewLine) | ConvertFrom-Json)
    } finally {
        if ($null -eq $oldPath) { Remove-Item Env:SMOKE_PATH -ErrorAction SilentlyContinue } else { $env:SMOKE_PATH = $oldPath }
        if ($null -eq $oldCookie) { Remove-Item Env:SMOKE_COOKIE -ErrorAction SilentlyContinue } else { $env:SMOKE_COOKIE = $oldCookie }
        if ($null -eq $oldBody) { Remove-Item Env:SMOKE_BODY -ErrorAction SilentlyContinue } else { $env:SMOKE_BODY = $oldBody }
        if ($null -eq $oldCount) { Remove-Item Env:SMOKE_COUNT -ErrorAction SilentlyContinue } else { $env:SMOKE_COUNT = $oldCount }
    }
}

function Login-User([string]$Email, [string]$Password, [string]$CookieJar, [string]$Prefix) {
    $requestPath = Join-Path $script:tempRoot "$Prefix-login.json"
    $responsePath = Join-Path $script:tempRoot "$Prefix-login-response.json"
    Write-Utf8 $requestPath (@{ email = $Email; password = $Password } | ConvertTo-Json -Compress)
    $status = [int](& curl.exe -sS -o $responsePath -c $CookieJar -w '%{http_code}' -H 'Content-Type: application/json' --data-binary "@$requestPath" "$PublicBaseUrl/auth/login")
    if ($status -ne 200) { throw "$Prefix login failed: HTTP $status $(Get-Content -Raw $responsePath)" }
    return $status
}

$marker = "PROJECT_VISIBILITY_R63_$([guid]::NewGuid().ToString('N').ToUpperInvariant())"
$memberEmail = "visibility-member-$([guid]::NewGuid().ToString('N'))@local.dev"
$leaderEmail = "visibility-leader-$([guid]::NewGuid().ToString('N'))@local.dev"
$targetEmail = "visibility-target-$([guid]::NewGuid().ToString('N'))@local.dev"
$memberPassword = "Visibility!$([guid]::NewGuid().ToString('N'))9a"
$leaderPassword = "Visibility!$([guid]::NewGuid().ToString('N'))9a"
$targetPassword = "Visibility!$([guid]::NewGuid().ToString('N'))9a"
$projectA = [guid]::NewGuid()
$projectB = [guid]::NewGuid()
$projectC = [guid]::NewGuid()
$projectEmpty = [guid]::NewGuid()
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) "smartbrain-project-visibility-r63-$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $tempRoot | Out-Null
$memberCookies = Join-Path $tempRoot 'member-cookies.txt'
$leaderCookies = Join-Path $tempRoot 'leader-cookies.txt'
$adminCookies = Join-Path $tempRoot 'admin-cookies.txt'
$createdUsers = @()
$adminAccessToken = $null
$adminSessionId = $null
$draftA = $null
$draftB = $null

try {
    $adminUserId = Invoke-Sql "SELECT id::text FROM public.users WHERE email='hanshangbo@local.dev' AND is_system_admin=true AND is_active=true"
    if ($adminUserId -notmatch '^[0-9a-f-]{36}$') { throw 'Active hanshangbo system administrator not found' }
    $orgId = Invoke-Sql "SELECT org_id::text FROM public.projects WHERE completed_at IS NULL ORDER BY created_at LIMIT 1"
    $departmentId = Invoke-Sql "SELECT id FROM public.departments WHERE allows_projects=true ORDER BY sort_order, id LIMIT 1"
    if (-not $orgId -or -not $departmentId) { throw 'Production project organization or department not found' }

    foreach ($definition in @(
        @{ Email = $memberEmail; Password = $memberPassword; Name = 'R63 Ordinary Member' },
        @{ Email = $leaderEmail; Password = $leaderPassword; Name = 'R63 Project Leader' },
        @{ Email = $targetEmail; Password = $targetPassword; Name = 'R63 Target Member' }
    )) {
        $created = Invoke-SupabaseAdmin 'POST' '/auth/v1/admin/users' (@{
            email = $definition.Email
            password = $definition.Password
            email_confirm = $true
            user_metadata = @{ full_name = $definition.Name }
        } | ConvertTo-Json -Depth 4 -Compress)
        if ([string]$created.id -notmatch '^[0-9a-f-]{36}$') { throw "Temporary user creation failed for $($definition.Email)" }
        $createdUsers += $created
    }
    $memberUserId = [string]$createdUsers[0].id
    $leaderUserId = [string]$createdUsers[1].id
    $targetUserId = [string]$createdUsers[2].id

    Invoke-Sql @"
BEGIN;
INSERT INTO public.projects(id,org_id,name,environment,department_id) VALUES
('$projectA','$orgId','R63 Project A $marker','development','$departmentId'),
('$projectB','$orgId','R63 Project B $marker','development','$departmentId'),
('$projectC','$orgId','R63 Project C $marker','development','$departmentId'),
('$projectEmpty','$orgId','R63 Empty Project $marker','development','$departmentId');
INSERT INTO public.project_members(project_id,user_id,role) VALUES
('$projectA','$leaderUserId','admin'),
('$projectA','$memberUserId','developer'),
('$projectB','$memberUserId','developer'),
('$projectC','$targetUserId','developer');
COMMIT;
"@ | Out-Null

    $memberLoginStatus = Login-User $memberEmail $memberPassword $memberCookies 'member'
    $leaderLoginStatus = Login-User $leaderEmail $leaderPassword $leaderCookies 'leader'

    $catalog = Invoke-JsonApi GET '/v4/projects/catalog' $memberCookies $null @(200)
    $catalogIds = @($catalog.Json | ForEach-Object { [string]$_.id })
    $databaseProjectIds = @((Invoke-Sql "SELECT id::text FROM public.projects ORDER BY id") -split '\r?\n' | Where-Object { $_ })
    $missingProjectIds = @($databaseProjectIds | Where-Object { $_ -notin $catalogIds })
    if ($missingProjectIds.Count -ne 0) { throw "Catalog omitted database projects: $($missingProjectIds -join ',')" }
    if ([string]$projectEmpty -notin $catalogIds) { throw 'Catalog omitted the empty project' }

    $unjoinedRoster = Invoke-JsonApi GET "/v4/projects/$projectC/members" $memberCookies $null @(200)
    if ($targetUserId -notin @($unjoinedRoster.Json | ForEach-Object { [string]$_.user_id })) { throw 'Ordinary member could not read the unjoined project roster' }
    $ordinaryManageDenied = Invoke-JsonApi POST "/v4/projects/$projectC/members" $memberCookies @{ user_id = $memberUserId; role = 'developer' } @(403)

    $leaderAdd = Invoke-JsonApi POST "/v4/projects/$projectA/members" $leaderCookies @{ user_id = $targetUserId; role = 'developer' } @(201)
    if ([string]$leaderAdd.Json.user_id -ne $targetUserId) { throw 'Project leader did not add the target member to Project A' }
    $projectARoster = Invoke-JsonApi GET "/v4/projects/$projectA/members" $leaderCookies $null @(200)
    if ($targetUserId -notin @($projectARoster.Json | ForEach-Object { [string]$_.user_id })) { throw 'Project A roster did not persist the leader member change' }
    $leaderOtherProjectRoster = Invoke-JsonApi GET "/v4/projects/$projectB/members" $leaderCookies $null @(200)
    if ($memberUserId -notin @($leaderOtherProjectRoster.Json | ForEach-Object { [string]$_.user_id })) { throw 'Project leader could not read another project roster' }
    $leaderManageOtherDenied = Invoke-JsonApi POST "/v4/projects/$projectB/members" $leaderCookies @{ user_id = $targetUserId; role = 'developer' } @(403)

    $repositoryA = Invoke-JsonApi PUT "/v4/project-memory/projects/$projectA/repository" $memberCookies @{
        git_url = "https://github.com/example/$($marker.ToLowerInvariant())-a.git"
        git_branch = 'main'
    } @(200)
    $repositoryB = Invoke-JsonApi PUT "/v4/project-memory/projects/$projectB/repository" $memberCookies @{
        git_url = "https://github.com/example/$($marker.ToLowerInvariant())-b.git"
        git_branch = 'main'
    } @(200)
    $draftA = [string]$repositoryA.Json.draft_id
    $draftB = [string]$repositoryB.Json.draft_id
    if ($draftA -notmatch '^[0-9a-f-]{36}$' -or $draftB -notmatch '^[0-9a-f-]{36}$') { throw 'Repository approval drafts were not created' }

    $ordinaryQueue = Invoke-JsonApi GET '/v4/project-memory/review-queue' $memberCookies $null @(200)
    if (@($ordinaryQueue.Json | Where-Object { [string]$_.id -in @($draftA, $draftB) }).Count -ne 0) { throw 'Ordinary member unexpectedly received approval items' }
    $leaderQueue = Invoke-JsonApi GET '/v4/project-memory/review-queue' $leaderCookies $null @(200)
    $leaderMarkerIds = @($leaderQueue.Json | Where-Object { [string]$_.id -in @($draftA, $draftB) } | ForEach-Object { [string]$_.id })
    if ($leaderMarkerIds.Count -ne 1 -or $draftA -notin $leaderMarkerIds) { throw "Project leader queue scope was incorrect: $($leaderMarkerIds -join ',')" }

    $link = Invoke-SupabaseAdmin 'POST' '/auth/v1/admin/generate_link' (@{ type = 'magiclink'; email = 'hanshangbo@local.dev' } | ConvertTo-Json -Compress)
    $hashedToken = [string]$link.hashed_token
    if (-not $hashedToken -and $link.properties) { $hashedToken = [string]$link.properties.hashed_token }
    $verified = Invoke-SupabaseAdmin 'POST' '/auth/v1/verify' (@{ type = 'magiclink'; token_hash = $hashedToken } | ConvertTo-Json -Compress)
    $adminAccessToken = [string]$verified.access_token
    $adminSessionId = Get-JwtSessionId $adminAccessToken
    $sessionBody = "access_token=$([Uri]::EscapeDataString($adminAccessToken))"
    $adminSessionStatus = [int](& curl.exe -sS -o (Join-Path $tempRoot 'admin-session.json') -c $adminCookies -w '%{http_code}' -H 'Content-Type: application/x-www-form-urlencoded' --data $sessionBody "$PublicBaseUrl/auth/session")
    if ($adminSessionStatus -ne 200) { throw "Admin session failed: HTTP $adminSessionStatus" }

    $adminQueue = Invoke-JsonApi GET '/v4/project-memory/review-queue' $adminCookies $null @(200)
    $adminMarkerIds = @($adminQueue.Json | Where-Object { [string]$_.id -in @($draftA, $draftB) } | ForEach-Object { [string]$_.id })
    if ($adminMarkerIds.Count -ne 2 -or $draftA -notin $adminMarkerIds -or $draftB -notin $adminMarkerIds) { throw "hanshangbo queue did not include both projects: $($adminMarkerIds -join ',')" }

    $leaderOtherReviewDenied = Invoke-JsonApi POST "/v4/project-memory/drafts/$draftB/review" $leaderCookies @{ decision = 'approve'; comment = "must be denied $marker" } @(403)

    $approvalCalls = @(Invoke-ConcurrentJsonApi "/v4/project-memory/drafts/$draftA/review" $leaderCookies @{
        decision = 'approve'
        comment = "concurrent project leader approval $marker"
    } 5)
    $approvalStatuses = @($approvalCalls | ForEach-Object { [int]$_.status })
    if (@($approvalStatuses | Where-Object { $_ -eq 200 }).Count -ne 5) { throw "Idempotent approval contract failed: $($approvalStatuses -join ',')" }
    $approvalResponses = @($approvalCalls | ForEach-Object { $_.body | ConvertFrom-Json })
    $resourceIds = @($approvalResponses | ForEach-Object { [string]$_.resource_id } | Select-Object -Unique)
    if ($resourceIds.Count -ne 1 -or $resourceIds[0] -ne [string]$projectA) { throw "Concurrent approvals returned inconsistent resources: $($resourceIds -join ',')" }

    $databaseApprovalA = Invoke-Sql @"
SELECT json_build_object(
  'repository_count', (SELECT count(*) FROM public.project_repositories WHERE project_id='$projectA'),
  'review_count', (SELECT count(*) FROM public.project_memory_reviews WHERE draft_id='$draftA'),
  'approved_submission_count', (SELECT count(*) FROM public.project_memory_submissions WHERE project_id='$projectA' AND status='approved'),
  'draft_status', (SELECT status::text FROM public.project_memory_drafts WHERE id='$draftA')
)
"@ | ConvertFrom-Json
    if ([int]$databaseApprovalA.repository_count -ne 1 -or [int]$databaseApprovalA.review_count -ne 1 -or [int]$databaseApprovalA.approved_submission_count -ne 1 -or $databaseApprovalA.draft_status -ne 'approved') {
        throw "Concurrent approval duplicated database state: $($databaseApprovalA | ConvertTo-Json -Compress)"
    }

    $oppositeDecision = Invoke-JsonApi POST "/v4/project-memory/drafts/$draftA/review" $adminCookies @{ decision = 'reject'; comment = "opposite decision $marker" } @(409)
    $adminApprovalB = Invoke-JsonApi POST "/v4/project-memory/drafts/$draftB/review" $adminCookies @{ decision = 'approve'; comment = "global approval $marker" } @(200)
    if ([string]$adminApprovalB.Json.resource_id -ne [string]$projectB) { throw 'hanshangbo approval did not activate Project B repository' }

    $finalQueueLeader = Invoke-JsonApi GET '/v4/project-memory/review-queue' $leaderCookies $null @(200)
    $finalQueueAdmin = Invoke-JsonApi GET '/v4/project-memory/review-queue' $adminCookies $null @(200)
    if (@($finalQueueLeader.Json | Where-Object { [string]$_.id -in @($draftA, $draftB) }).Count -ne 0) { throw 'Leader queue retained an approved marker draft' }
    if (@($finalQueueAdmin.Json | Where-Object { [string]$_.id -in @($draftA, $draftB) }).Count -ne 0) { throw 'Global queue retained an approved marker draft' }

    $finalDatabase = Invoke-Sql @"
SELECT json_build_object(
  'repository_count', (SELECT count(*) FROM public.project_repositories WHERE project_id IN ('$projectA','$projectB')),
  'review_count', (SELECT count(*) FROM public.project_memory_reviews WHERE draft_id IN ('$draftA','$draftB')),
  'approved_draft_count', (SELECT count(*) FROM public.project_memory_drafts WHERE id IN ('$draftA','$draftB') AND status='approved')
)
"@ | ConvertFrom-Json
    if ([int]$finalDatabase.repository_count -ne 2 -or [int]$finalDatabase.review_count -ne 2 -or [int]$finalDatabase.approved_draft_count -ne 2) { throw "Final approval database verification failed: $($finalDatabase | ConvertTo-Json -Compress)" }

    [pscustomobject]@{
        marker = $marker
        project_catalog_database_count = $databaseProjectIds.Count
        project_catalog_api_count = $catalogIds.Count
        empty_project_visible = $true
        ordinary_unjoined_roster_read = $unjoinedRoster.Status
        ordinary_member_management_denied = $ordinaryManageDenied.Status
        leader_project_a_member_add = $leaderAdd.Status
        leader_other_project_roster_read = $leaderOtherProjectRoster.Status
        leader_other_project_management_denied = $leaderManageOtherDenied.Status
        ordinary_approval_queue_marker_count = 0
        leader_approval_queue_projects = @([string]$projectA)
        hanshangbo_approval_queue_projects = @([string]$projectA, [string]$projectB)
        leader_other_project_review_denied = $leaderOtherReviewDenied.Status
        concurrent_same_decision_statuses = $approvalStatuses
        concurrent_unique_resource_ids = $resourceIds
        concurrent_repository_rows = [int]$databaseApprovalA.repository_count
        concurrent_review_rows = [int]$databaseApprovalA.review_count
        opposite_decision_after_approval = $oppositeDecision.Status
        hanshangbo_project_b_approval = $adminApprovalB.Status
        final_repository_rows = [int]$finalDatabase.repository_count
        final_review_rows = [int]$finalDatabase.review_count
    } | ConvertTo-Json -Depth 6
} finally {
    foreach ($cookieJar in @($memberCookies, $leaderCookies, $adminCookies)) {
        if (Test-Path $cookieJar) { & curl.exe -sS -o NUL -b $cookieJar -X POST "$PublicBaseUrl/auth/logout" | Out-Null }
    }
    if ($adminAccessToken) {
        try { Invoke-SupabaseAdmin 'POST' '/auth/v1/logout?scope=local' '' $adminAccessToken | Out-Null } catch {}
    }
    Invoke-Sql "DELETE FROM public.projects WHERE id IN ('$projectA','$projectB','$projectC','$projectEmpty'); DELETE FROM auth.sessions WHERE id=NULLIF('$adminSessionId','')::uuid;" | Out-Null
    foreach ($createdUser in $createdUsers) {
        if ($createdUser -and $createdUser.id) {
            & (Join-Path $PSScriptRoot 'Remove-TemporarySupabaseUser.ps1') -UserId $createdUser.id -ServiceRoleKey $serviceRole | Out-Null
        }
    }
    if (Test-Path $tempRoot) {
        $resolvedTemp = [IO.Path]::GetFullPath($tempRoot)
        $systemTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
        if (-not $resolvedTemp.StartsWith($systemTemp, [StringComparison]::OrdinalIgnoreCase) -or [IO.Path]::GetFileName($resolvedTemp) -notlike 'smartbrain-project-visibility-r63-*') {
            throw "Refusing to remove unexpected temporary directory: $resolvedTemp"
        }
        Remove-Item -LiteralPath $resolvedTemp -Recurse -Force
    }
    $remaining = Invoke-Sql @"
SELECT
  (SELECT count(*) FROM public.projects WHERE id IN ('$projectA','$projectB','$projectC','$projectEmpty')) +
  (SELECT count(*) FROM auth.users WHERE email IN ('$memberEmail','$leaderEmail','$targetEmail')) +
  (SELECT count(*) FROM public.project_memory_submissions WHERE project_id IN ('$projectA','$projectB','$projectC','$projectEmpty'))
"@
    if ([int64]$remaining -ne 0) { throw "R63 cleanup left $remaining rows" }
}
