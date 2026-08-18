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
    return ([string]($result -join "`n")).Trim()
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
        $text = [string]($raw -join "`n")
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

function Start-JsonCurl {
    param([string]$Method, [string]$Path, [string]$CookieJar, [string]$BodyPath, [string]$Prefix)
    $responsePath = Join-Path $script:tempRoot "$Prefix-response.json"
    $statusPath = Join-Path $script:tempRoot "$Prefix-status.txt"
    $args = @('-sS', '-o', $responsePath, '-b', $CookieJar, '-w', '%{http_code}', '-X', $Method, '-H', '"Content-Type: application/json"', '--data-binary', "@$BodyPath", "$PublicBaseUrl$Path")
    $process = Start-Process -FilePath 'curl.exe' -ArgumentList $args -NoNewWindow -PassThru -RedirectStandardOutput $statusPath
    return [pscustomobject]@{ Process = $process; StatusPath = $statusPath; ResponsePath = $responsePath }
}

$marker = "UNIFIED_R61_$([guid]::NewGuid().ToString('N').ToUpperInvariant())"
$email = "unified-r61-$([guid]::NewGuid().ToString('N'))@local.dev"
$password = "Unified!$([guid]::NewGuid().ToString('N'))9a"
$projectA = [guid]::NewGuid()
$projectB = [guid]::NewGuid()
$materialId = [guid]::NewGuid()
$intakeId = [guid]::NewGuid()
$materialFileId = [guid]::NewGuid()
$wikiId = [guid]::NewGuid()
$wikiDocumentId = [guid]::NewGuid()
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) "smartbrain-unified-r61-$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $tempRoot | Out-Null
$memberCookies = Join-Path $tempRoot 'member-cookies.txt'
$adminCookies = Join-Path $tempRoot 'admin-cookies.txt'
$createdUser = $null
$adminAccessToken = $null
$adminSessionId = $null
$adminUserId = $null

try {
    $adminUserId = Invoke-Sql "SELECT id::text FROM public.users WHERE email='hanshangbo@local.dev' AND is_system_admin=true AND is_active=true"
    if ($adminUserId -notmatch '^[0-9a-f-]{36}$') { throw 'Active hanshangbo system administrator not found' }
    $orgId = Invoke-Sql "SELECT org_id::text FROM public.projects ORDER BY created_at LIMIT 1"
    $departmentId = Invoke-Sql "SELECT id FROM public.departments WHERE allows_projects=true ORDER BY sort_order, id LIMIT 1"

    $createdUser = Invoke-SupabaseAdmin 'POST' '/auth/v1/admin/users' (@{
        email = $email; password = $password; email_confirm = $true
        user_metadata = @{ full_name = "Unified R61 Test Member" }
    } | ConvertTo-Json -Depth 4 -Compress)
    $userId = [string]$createdUser.id
    if ($userId -notmatch '^[0-9a-f-]{36}$') { throw 'Temporary user creation failed' }

    $projectSetupSql = @"
BEGIN;
INSERT INTO public.projects(id,org_id,name,environment,department_id) VALUES
('$projectA','$orgId','统一内容验收A-$marker','development','$departmentId'),
('$projectB','$orgId','统一内容验收B-$marker','development','$departmentId');
INSERT INTO public.project_members(project_id,user_id,role) VALUES
('$projectA','$userId','developer'),('$projectB','$userId','developer');
COMMIT;
"@
    Invoke-Sql $projectSetupSql | Out-Null

    $loginRequest = Join-Path $tempRoot 'member-login.json'
    Write-Utf8 $loginRequest (@{ email = $email; password = $password } | ConvertTo-Json -Compress)
    $loginStatus = [int](& curl.exe -sS -o (Join-Path $tempRoot 'member-login-response.json') -c $memberCookies -w '%{http_code}' -H 'Content-Type: application/json' --data-binary "@$loginRequest" "$PublicBaseUrl/auth/login")
    if ($loginStatus -ne 200) { throw "Member login failed: $loginStatus" }

    $meetingPath = Join-Path $tempRoot 'meeting.md'
    Write-Utf8 $meetingPath "# $marker 会议原文`n`n会议内容标记：$marker`n`n- 决议：统一审批。"
    $meetingResponse = Join-Path $tempRoot 'meeting-response.json'
    $participants = '["' + $userId + '"]'
    $meetingStatus = [int](& curl.exe -sS -o $meetingResponse -b $memberCookies -w '%{http_code}' -F "project_id=$projectA" -F "title=$marker 会议" -F 'meeting_date=2026-08-18' -F "participant_user_ids=$participants" -F "file=@$meetingPath;type=text/markdown" "$PublicBaseUrl/v4/meeting-summaries")
    if ($meetingStatus -ne 200) { throw "Meeting submission failed: $meetingStatus $(Get-Content -Raw $meetingResponse)" }
    $meetingSubmission = Get-Content -Raw -Encoding UTF8 $meetingResponse | ConvertFrom-Json
    $meetingDraftId = [string]$meetingSubmission.draft_id

    $repositoryUrl = "https://github.com/example/$($marker.ToLowerInvariant()).git"
    $repositorySubmit = Invoke-JsonApi PUT "/v4/project-memory/projects/$projectA/repository" $memberCookies @{ git_url = $repositoryUrl; git_branch = 'main' } @(200)
    $repositoryDraftId = [string]$repositorySubmit.Json.draft_id
    $repositoryBefore = Invoke-JsonApi GET "/v4/project-memory/projects/$projectA/repository" $memberCookies $null @(200)
    if ($null -ne $repositoryBefore.Json) { throw 'Repository became active before approval' }

    $denied = Invoke-JsonApi POST "/v4/project-memory/drafts/$meetingDraftId/review" $memberCookies @{ decision = 'approve'; comment = 'must be denied' } @(403)

    $link = Invoke-SupabaseAdmin 'POST' '/auth/v1/admin/generate_link' (@{ type = 'magiclink'; email = 'hanshangbo@local.dev' } | ConvertTo-Json -Compress)
    $hashedToken = [string]$link.hashed_token
    if (-not $hashedToken -and $link.properties) { $hashedToken = [string]$link.properties.hashed_token }
    $verified = Invoke-SupabaseAdmin 'POST' '/auth/v1/verify' (@{ type = 'magiclink'; token_hash = $hashedToken } | ConvertTo-Json -Compress)
    $adminAccessToken = [string]$verified.access_token
    $adminSessionId = Get-JwtSessionId $adminAccessToken
    $sessionBody = "access_token=$([Uri]::EscapeDataString($adminAccessToken))"
    $adminSessionStatus = [int](& curl.exe -sS -o (Join-Path $tempRoot 'admin-session.json') -c $adminCookies -w '%{http_code}' -H 'Content-Type: application/x-www-form-urlencoded' --data $sessionBody "$PublicBaseUrl/auth/session")
    if ($adminSessionStatus -ne 200) { throw "Admin session failed: $adminSessionStatus" }

    $queue = Invoke-JsonApi GET '/v4/project-memory/review-queue' $adminCookies $null @(200)
    $queueKinds = @($queue.Json | Where-Object { $_.id -in @($meetingDraftId, $repositoryDraftId) } | ForEach-Object { $_.review_kind })
    if ('meeting_summary' -notin $queueKinds -or 'project_repository' -notin $queueKinds) { throw 'Unified queue is missing meeting or repository item' }

    $approvalBodyPath = Join-Path $tempRoot 'approval.json'
    Write-Utf8 $approvalBodyPath (@{ decision = 'approve'; comment = "concurrent approval $marker" } | ConvertTo-Json -Compress)
    $approvalCalls = 1..5 | ForEach-Object { Start-JsonCurl POST "/v4/project-memory/drafts/$meetingDraftId/review" $adminCookies $approvalBodyPath "meeting-approval-$_" }
    $approvalCalls.Process | Wait-Process
    $approvalStatuses = @($approvalCalls | ForEach-Object { [int](Get-Content -Raw $_.StatusPath) })
    if (@($approvalStatuses | Where-Object { $_ -eq 200 }).Count -ne 1 -or @($approvalStatuses | Where-Object { $_ -eq 409 }).Count -ne 4) {
        throw "Meeting approval concurrency contract failed: $($approvalStatuses -join ',')"
    }
    $winningApproval = $approvalCalls | Where-Object { [int](Get-Content -Raw $_.StatusPath) -eq 200 } | Select-Object -First 1
    $meetingApproval = Get-Content -Raw -Encoding UTF8 $winningApproval.ResponsePath | ConvertFrom-Json
    $meetingId = [string]$meetingApproval.resource_id

    $repositoryApproval = Invoke-JsonApi POST "/v4/project-memory/drafts/$repositoryDraftId/review" $adminCookies @{ decision = 'approve'; comment = "repository approval $marker" } @(200)
    $repositoryAfter = Invoke-JsonApi GET "/v4/project-memory/projects/$projectA/repository" $memberCookies $null @(200)
    if ($repositoryAfter.Json.git_url -ne $repositoryUrl -or $repositoryAfter.Json.status -ne 'approved') { throw 'Approved repository was not activated' }

    $materialText = "原始资料预览标记 $marker"
    $materialBytes = [Text.Encoding]::UTF8.GetByteCount($materialText)
    $assetSetupSql = @"
BEGIN;
INSERT INTO public.project_material_intakes(id,project_id,department_id,status,preview_summary,created_by_user_id,confirmed_at,upload_completed_at)
VALUES('$intakeId','$projectA','$departmentId','approved','','$userId',now(),now());
INSERT INTO public.documents(id,project_id,filename,display_name,format,size_bytes,status,chunk_count,created_by_user_id,department_id,memory_type)
VALUES('$materialId','$projectA','r61-material.md','R61 原始资料','md',$materialBytes,'ready',1,'$userId','$departmentId','raw_project_material');
INSERT INTO public.project_material_intake_files(id,intake_id,filename,format,size_bytes,content_hash,raw_content,extracted_text,recommendation,included,reason,document_id,uploaded_bytes)
VALUES('$materialFileId','$intakeId','r61-material.md','md',$materialBytes,md5('$marker'),convert_to('$materialText','UTF8'),'$materialText','keep',true,'direct','$materialId',$materialBytes);
INSERT INTO public.project_material_documents(document_id,project_id,uploaded_by_user_id,content_hash,original_file_id)
VALUES('$materialId','$projectA','$userId',md5('$marker'),'$materialFileId');
INSERT INTO public.document_chunks(document_id,project_id,chunk_index,content,token_count,embedding)
VALUES('$materialId','$projectA',0,'$materialText',8,array_fill(0::real,ARRAY[384])::vector(384));
INSERT INTO public.documents(id,project_id,filename,display_name,format,size_bytes,status,chunk_count,created_by_user_id,department_id,memory_type)
VALUES('$wikiDocumentId','$projectA','r61-wiki.md','R61 Wiki','md',64,'ready',1,'$userId','$departmentId','project_wiki_page');
INSERT INTO public.document_chunks(document_id,project_id,chunk_index,content,token_count,embedding)
VALUES('$wikiDocumentId','$projectA',0,'Wiki 预览标记 $marker',8,array_fill(0::real,ARRAY[384])::vector(384));
INSERT INTO public.project_wiki_pages(id,project_id,page_key,title,page_type,status,summary,markdown_content,usefulness,confidence,created_by_user_id)
VALUES('$wikiId','$projectA','r61-$($wikiId.ToString('N'))','R61 Wiki','note','active','R61 smoke','# R61 Wiki`n`nWiki 预览标记 $marker',1,1,'$userId');
UPDATE public.project_wiki_pages SET document_id='$wikiDocumentId' WHERE id='$wikiId';
COMMIT;
"@
    Invoke-Sql $assetSetupSql | Out-Null

    Invoke-Sql "UPDATE public.project_members SET role='admin' WHERE user_id='$userId' AND project_id IN ('$projectA','$projectB')" | Out-Null

    $assets = @(
        [pscustomobject]@{ Type='project_material'; Id=[string]$materialId; NewName='重命名原始资料'; Marker=$marker },
        [pscustomobject]@{ Type='project_wiki'; Id=[string]$wikiId; NewName='重命名 Wiki'; Marker=$marker },
        [pscustomobject]@{ Type='meeting_record'; Id=$meetingId; NewName='重命名会议记录'; Marker=$marker }
    )
    $ledgers = @(
        [pscustomobject]@{ Category='project_material'; AssetId=[string]$materialId },
        [pscustomobject]@{ Category='project_wiki_source'; AssetId=[string]$wikiId },
        [pscustomobject]@{ Category='meeting_record'; AssetId=$meetingId }
    )
    foreach ($ledgerExpectation in $ledgers) {
        $ledger = Invoke-JsonApi GET "/v4/knowledge/ledger?project_id=$projectA&category=$($ledgerExpectation.Category)" $memberCookies $null @(200)
        if ($ledgerExpectation.AssetId -notin @($ledger.Json.documents | ForEach-Object { [string]$_.asset_id })) {
            throw "Knowledge ledger is missing $($ledgerExpectation.Category) asset"
        }
    }
    foreach ($asset in $assets) {
        $preview = Invoke-JsonApi GET "/v4/knowledge/assets/$($asset.Type)/$($asset.Id)/preview" $memberCookies $null @(200)
        if ([string]$preview.Json.content -notmatch [regex]::Escape($marker)) { throw "Preview marker missing for $($asset.Type)" }
        $downloadPath = Join-Path $tempRoot "$($asset.Type)-download.bin"
        $downloadStatus = [int](& curl.exe -sS -o $downloadPath -b $memberCookies -w '%{http_code}' "$PublicBaseUrl/v4/knowledge/assets/$($asset.Type)/$($asset.Id)/download")
        if ($downloadStatus -ne 200 -or (Get-Item $downloadPath).Length -le 0) { throw "Download failed for $($asset.Type)" }
        $renamed = Invoke-JsonApi PATCH "/v4/knowledge/assets/$($asset.Type)/$($asset.Id)" $memberCookies @{ name = $asset.NewName } @(200)
        if ($renamed.Json.name -ne $asset.NewName) { throw "Rename failed for $($asset.Type)" }
        $moved = Invoke-JsonApi POST "/v4/knowledge/assets/$($asset.Type)/$($asset.Id)/move" $memberCookies @{ target_project_id = [string]$projectB } @(200)
        if ([string]$moved.Json.project_id -ne [string]$projectB) { throw "Move failed for $($asset.Type)" }
        Invoke-JsonApi DELETE "/v4/knowledge/assets/$($asset.Type)/$($asset.Id)" $memberCookies $null @(403) | Out-Null
        Invoke-JsonApi DELETE "/v4/knowledge/assets/$($asset.Type)/$($asset.Id)" $adminCookies $null @(204) | Out-Null
    }

    $stressBodyPath = Join-Path $tempRoot 'repository-stress.json'
    Write-Utf8 $stressBodyPath (@{ git_url = "https://github.com/example/$($marker.ToLowerInvariant())-stress.git"; git_branch = 'stress' } | ConvertTo-Json -Compress)
    $stressCalls = 1..10 | ForEach-Object { Start-JsonCurl PUT "/v4/project-memory/projects/$projectA/repository" $memberCookies $stressBodyPath "repo-stress-$_" }
    $stressCalls.Process | Wait-Process
    $stressStatuses = @($stressCalls | ForEach-Object { [int](Get-Content -Raw $_.StatusPath) })
    if (@($stressStatuses | Where-Object { $_ -eq 200 }).Count -ne 1 -or @($stressStatuses | Where-Object { $_ -eq 409 }).Count -ne 9) {
        throw "Repository proposal concurrency contract failed: $($stressStatuses -join ',')"
    }
    $stressWinner = $stressCalls | Where-Object { [int](Get-Content -Raw $_.StatusPath) -eq 200 } | Select-Object -First 1
    $stressDraft = [string]((Get-Content -Raw -Encoding UTF8 $stressWinner.ResponsePath | ConvertFrom-Json).draft_id)
    Invoke-JsonApi POST "/v4/project-memory/drafts/$stressDraft/review" $adminCookies @{ decision = 'reject'; comment = "stress cleanup $marker" } @(200) | Out-Null
    $repositoryStillActive = Invoke-JsonApi GET "/v4/project-memory/projects/$projectA/repository" $memberCookies $null @(200)
    if ($repositoryStillActive.Json.git_url -ne $repositoryUrl) { throw 'Rejected repository proposal changed the active repository' }

    $verificationSql = @"
SELECT json_build_object(
  'meeting_submission_approved', EXISTS(SELECT 1 FROM public.project_memory_submissions WHERE id='$($meetingSubmission.id)' AND status='approved' AND raw_content IS NULL),
  'repository_submission_approved', EXISTS(SELECT 1 FROM public.project_memory_submissions WHERE project_id='$projectA' AND submission_type='project_repository' AND status='approved' AND payload->>'git_url'='$repositoryUrl'),
  'assets_deleted', NOT EXISTS(SELECT 1 FROM public.documents WHERE id='$materialId') AND NOT EXISTS(SELECT 1 FROM public.project_wiki_pages WHERE id='$wikiId') AND NOT EXISTS(SELECT 1 FROM public.meeting_summaries WHERE id='$meetingId'),
  'queue_project_labels', (SELECT count(*) FROM public.project_memory_drafts WHERE project_id='$projectA' AND title LIKE '%审批%')
)
"@
    $verification = Invoke-Sql $verificationSql | ConvertFrom-Json
    if (-not $verification.meeting_submission_approved -or -not $verification.repository_submission_approved -or -not $verification.assets_deleted) { throw 'Final database verification failed' }

    [pscustomobject]@{
        marker = $marker
        member_login = $loginStatus
        meeting_submit = $meetingStatus
        member_review_denied = $denied.Status
        queue_kinds = ($queueKinds -join ',')
        meeting_approval_concurrency = ($approvalStatuses -join ',')
        repository_approved = $repositoryAfter.Json.status
        knowledge_assets_previewed_downloaded_renamed_moved_and_deleted = 3
        repository_proposal_concurrency = ($stressStatuses -join ',')
        rejected_repository_kept_active = $true
    } | ConvertTo-Json -Depth 4
} finally {
    if (Test-Path $memberCookies) { & curl.exe -sS -o NUL -b $memberCookies -X POST "$PublicBaseUrl/auth/logout" | Out-Null }
    if (Test-Path $adminCookies) { & curl.exe -sS -o NUL -b $adminCookies -X POST "$PublicBaseUrl/auth/logout" | Out-Null }
    if ($adminAccessToken) {
        try { Invoke-SupabaseAdmin 'POST' '/auth/v1/logout?scope=local' '' $adminAccessToken | Out-Null } catch {}
    }
    Invoke-Sql "DELETE FROM public.projects WHERE id IN ('$projectA','$projectB'); DELETE FROM auth.sessions WHERE id=NULLIF('$adminSessionId','')::uuid;" | Out-Null
    if ($createdUser -and $createdUser.id) {
        & (Join-Path $PSScriptRoot 'Remove-TemporarySupabaseUser.ps1') -UserId $createdUser.id -ServiceRoleKey $serviceRole | Out-Null
    }
    if (Test-Path $tempRoot) { Remove-Item $tempRoot -Recurse -Force }
    $remaining = Invoke-Sql "SELECT (SELECT count(*) FROM public.projects WHERE id IN ('$projectA','$projectB')) + (SELECT count(*) FROM auth.users WHERE email='$email') + (SELECT count(*) FROM public.project_memory_submissions WHERE project_id IN ('$projectA','$projectB'))"
    if ([int64]$remaining -ne 0) { throw "Unified R61 cleanup left $remaining rows" }
}
