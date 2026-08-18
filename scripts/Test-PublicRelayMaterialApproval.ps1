#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$PublicBaseUrl = "https://39.105.79.0",
    [string]$ProjectId = "dfaefd9a-8e5e-4775-bc18-e3d551c651e4",
    [string]$DepartmentId = ""
)

$ErrorActionPreference = "Stop"
if ($ProjectId -notmatch "^[0-9a-fA-F-]{36}$") {
    throw "ProjectId must be a UUID."
}

$serviceRole = ((
    Get-Content -LiteralPath (Join-Path $PSScriptRoot "..\.env") |
        Where-Object { $_ -like "SUPABASE_SERVICE_ROLE_KEY=*" } |
        Select-Object -First 1
) -split "=", 2)[1]
if (-not $serviceRole) { throw "Missing local Supabase service role key." }

function Invoke-ScalarSql {
    param([Parameter(Mandatory = $true)][string]$Sql)

    $output = & docker exec supabase_db_database `
        psql -U postgres -d postgres -At -v ON_ERROR_STOP=1 -c $Sql
    if ($LASTEXITCODE -ne 0) { throw "Database query failed." }
    return ([string]($output -join "`n")).Trim()
}

function Invoke-SupabaseJsonInContainer {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("POST", "DELETE")]
        [string]$Method,
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [string]$Body = "",
        [string]$BearerToken = $serviceRole
    )

    $python = @'
import base64
import os
import sys
import urllib.error
import urllib.request

method, path = sys.argv[1:3]
service_role = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
bearer_token = os.environ.get("SB_BEARER_TOKEN", "")
if not service_role or not bearer_token:
    raise SystemExit("Missing Supabase credentials inside the API transport.")

payload = base64.b64decode(os.environ.get("SB_REQUEST_BODY_BASE64", ""))
request = urllib.request.Request(
    "http://supabase_kong_database:8000" + path,
    data=payload or None,
    method=method,
    headers={
        "apikey": service_role,
        "Authorization": "Bearer " + bearer_token,
        "Content-Type": "application/json",
    },
)
try:
    with urllib.request.urlopen(request, timeout=30) as response:
        sys.stdout.buffer.write(response.read())
except urllib.error.HTTPError as exc:
    detail = exc.read().decode("utf-8", errors="replace")
    print(f"Supabase API returned HTTP {exc.code}: {detail}", file=sys.stderr)
    raise SystemExit(1)
'@

    $previousServiceRole = $env:SUPABASE_SERVICE_ROLE_KEY
    $previousBearerToken = $env:SB_BEARER_TOKEN
    $previousRequestBody = $env:SB_REQUEST_BODY_BASE64
    try {
        $env:SUPABASE_SERVICE_ROLE_KEY = $serviceRole
        $env:SB_BEARER_TOKEN = $BearerToken
        $env:SB_REQUEST_BODY_BASE64 = [Convert]::ToBase64String(
            [Text.Encoding]::UTF8.GetBytes($Body)
        )
        $response = $python | & docker exec -i `
            -e SUPABASE_SERVICE_ROLE_KEY `
            -e SB_BEARER_TOKEN `
            -e SB_REQUEST_BODY_BASE64 `
            agentops-api-1 `
            /app/.venv/bin/python - $Method $Path
        if ($LASTEXITCODE -ne 0) {
            throw "Supabase API container transport failed for $Method $Path."
        }
        $rawResponse = [string]($response -join "`n")
        if ($rawResponse.Trim()) {
            return $rawResponse | ConvertFrom-Json
        }
        return $null
    } finally {
        if ($null -eq $previousServiceRole) {
            Remove-Item Env:SUPABASE_SERVICE_ROLE_KEY -ErrorAction SilentlyContinue
        } else {
            $env:SUPABASE_SERVICE_ROLE_KEY = $previousServiceRole
        }
        if ($null -eq $previousBearerToken) {
            Remove-Item Env:SB_BEARER_TOKEN -ErrorAction SilentlyContinue
        } else {
            $env:SB_BEARER_TOKEN = $previousBearerToken
        }
        if ($null -eq $previousRequestBody) {
            Remove-Item Env:SB_REQUEST_BODY_BASE64 -ErrorAction SilentlyContinue
        } else {
            $env:SB_REQUEST_BODY_BASE64 = $previousRequestBody
        }
    }
}

function Get-JwtSessionId {
    param([Parameter(Mandatory = $true)][string]$AccessToken)

    $parts = $AccessToken.Split(".")
    if ($parts.Count -ne 3) { throw "Supabase access token is not a JWT." }
    $payload = $parts[1].Replace("-", "+").Replace("_", "/")
    switch ($payload.Length % 4) {
        2 { $payload += "==" }
        3 { $payload += "=" }
        1 { throw "Supabase access token contains invalid base64url payload." }
    }
    $claims = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payload)) |
        ConvertFrom-Json
    $sessionId = [string]$claims.session_id
    if ($sessionId -notmatch "^[0-9a-fA-F-]{36}$") {
        throw "Supabase access token does not contain a valid session_id."
    }
    return $sessionId
}

$email = "material-approval-$([guid]::NewGuid().ToString('N'))@local.dev"
$password = "Relay!$([guid]::NewGuid().ToString('N'))9a"
$marker = "MATERIAL_APPROVAL_$([guid]::NewGuid().ToString('N').ToUpperInvariant())"
$adminEmail = "hanshangbo@local.dev"
$adminHeaders = @{
    apikey = $serviceRole
    Authorization = "Bearer $serviceRole"
    "Content-Type" = "application/json"
}

$created = $null
$intakeId = $null
$fileId = $null
$draftId = $null
$documentId = $null
$adminUserId = $null
$adminAccessToken = $null
$adminSupabaseSessionId = $null
$storageKeys = @()
$adminWebSession = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$memberCookieJar = $null
$result = $null
$cleanupResult = $null
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) (
    "smartbrain-material-approval-$([guid]::NewGuid().ToString('N'))"
)
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null

try {
    $effectiveDepartmentId = $DepartmentId.Trim()
    if (-not $effectiveDepartmentId) {
        $effectiveDepartmentId = Invoke-ScalarSql `
            "SELECT department_id FROM public.projects WHERE id='$ProjectId'"
        if (-not $effectiveDepartmentId) {
            throw "Could not resolve the project's current category."
        }
    }

    $adminUserId = Invoke-ScalarSql @"
SELECT id::text
FROM public.users
WHERE email='$adminEmail' AND is_system_admin=true AND is_active=true
"@
    if ($adminUserId -notmatch "^[0-9a-fA-F-]{36}$") {
        throw "The hanshangbo system administrator account is missing or inactive."
    }

    $createBody = @{
        email = $email
        password = $password
        email_confirm = $true
        user_metadata = @{ full_name = "Material Approval E2E Member" }
    } | ConvertTo-Json -Depth 4
    try {
        $created = Invoke-RestMethod -Method Post `
            -Uri "http://127.0.0.1:54321/auth/v1/admin/users" `
            -Headers $adminHeaders `
            -Body $createBody `
            -TimeoutSec 5
    } catch {
        $created = Invoke-SupabaseJsonInContainer `
            -Method POST `
            -Path "/auth/v1/admin/users" `
            -Body $createBody
    }
    if ([string]$created.id -notmatch "^[0-9a-fA-F-]{36}$") {
        throw "Temporary member creation did not return a valid user ID."
    }

    & docker exec supabase_db_database psql -U postgres -d postgres -v ON_ERROR_STOP=1 `
        -c "INSERT INTO public.project_members(project_id,user_id,role) VALUES ('$ProjectId','$($created.id)','developer') ON CONFLICT (project_id,user_id) DO UPDATE SET role=EXCLUDED.role" |
        Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not add the temporary project member." }

    $loginRequest = Join-Path $tempRoot "member-login.json"
    $loginResponse = Join-Path $tempRoot "member-login-response.json"
    $memberCookieJar = Join-Path $tempRoot "member-cookies.txt"
    $loginJson = @{ email = $email; password = $password } | ConvertTo-Json -Compress
    [IO.File]::WriteAllText($loginRequest, $loginJson, (New-Object Text.UTF8Encoding $false))
    $loginStatus = & curl.exe -sS `
        -o $loginResponse `
        -c $memberCookieJar `
        -w "%{http_code}" `
        -H "Origin: $PublicBaseUrl" `
        -H "Content-Type: application/json" `
        --data-binary "@$loginRequest" `
        "$PublicBaseUrl/auth/login"
    if ([int]$loginStatus -ne 200) {
        throw "Temporary member login failed: HTTP $loginStatus"
    }

    $uploadPath = Join-Path $tempRoot "direct-upload-r58.md"
    $fixture = @"
# 普通成员上传、管理员审批验收

这是不含敏感信息的自动验收资料。

Validation-Marker: $marker
"@
    [IO.File]::WriteAllText($uploadPath, $fixture, (New-Object Text.UTF8Encoding $false))
    $repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
    $uploadFiles = @(
        [pscustomobject]@{ Name = "direct-upload-r58.md"; Path = $uploadPath },
        [pscustomobject]@{ Name = "format-test-excel-r55.xlsx"; Path = Join-Path $repoRoot ".tmp\upload-format-r55\format-test-excel-r55.xlsx" },
        [pscustomobject]@{ Name = "format-test-word-r55.docx"; Path = Join-Path $repoRoot ".tmp\upload-format-r55\format-test-word-r55.docx" },
        [pscustomobject]@{ Name = "format-test-powerpoint-r56.pptx"; Path = Join-Path $repoRoot ".tmp\upload-format-r56-ppt\format-test-powerpoint-r56.pptx" },
        [pscustomobject]@{ Name = "format-test-pdf-r55.pdf"; Path = Join-Path $repoRoot ".tmp\upload-format-r55\format-test-pdf-r55.pdf" }
    )
    foreach ($uploadFile in $uploadFiles) {
        if (-not (Test-Path -LiteralPath $uploadFile.Path -PathType Leaf)) {
            throw "Missing direct-upload fixture: $($uploadFile.Path)"
        }
    }

    $clientUploadId = [guid]::NewGuid().ToString()
    $sessionRequest = Join-Path $tempRoot "upload-session.json"
    $sessionResponse = Join-Path $tempRoot "upload-session-response.json"
    $sessionJson = @{
        project_id = $ProjectId
        department_id = $effectiveDepartmentId
        client_upload_id = $clientUploadId
        files = @($uploadFiles | ForEach-Object {
            @{
                filename = $_.Name
                size_bytes = (Get-Item -LiteralPath $_.Path).Length
            }
        })
    } | ConvertTo-Json -Depth 5 -Compress
    [IO.File]::WriteAllText($sessionRequest, $sessionJson, (New-Object Text.UTF8Encoding $false))
    $sessionStatus = & curl.exe -sS `
        --max-time 120 `
        -o $sessionResponse `
        -b $memberCookieJar `
        -w "%{http_code}" `
        -H "Content-Type: application/json" `
        --data-binary "@$sessionRequest" `
        "$PublicBaseUrl/v4/knowledge/material-intakes/upload-sessions"
    if ([int]$sessionStatus -ne 201) {
        $detail = (Get-Content -LiteralPath $sessionResponse -Raw -Encoding UTF8).Trim()
        throw "Public direct-upload session creation failed: HTTP $sessionStatus - $detail"
    }
    $uploadSession = Get-Content -LiteralPath $sessionResponse -Raw -Encoding UTF8 |
        ConvertFrom-Json
    $intakeId = [string]$uploadSession.intake_id
    if ($intakeId -notmatch "^[0-9a-fA-F-]{36}$") {
        throw "Direct upload did not return a valid intake ID."
    }
    if (@($uploadSession.files).Count -ne 5) {
        throw "direct upload did not retain five files"
    }

    foreach ($sessionFile in @($uploadSession.files)) {
        $fileId = [string]$sessionFile.id
        $sourceFile = $uploadFiles | Where-Object { $_.Name -eq [string]$sessionFile.filename } |
            Select-Object -First 1
        if ($fileId -notmatch "^[0-9a-fA-F-]{36}$" -or -not $sourceFile) {
            throw "Direct upload returned an unknown file entry."
        }
        $chunkResponse = Join-Path $tempRoot "chunk-$fileId.json"
        $chunkStatus = & curl.exe -sS `
            --max-time 180 `
            -o $chunkResponse `
            -b $memberCookieJar `
            -w "%{http_code}" `
            -X PUT `
            -H "Content-Type: application/octet-stream" `
            --data-binary "@$($sourceFile.Path)" `
            "$PublicBaseUrl/v4/knowledge/material-intakes/upload-sessions/$intakeId/files/$fileId`?offset=0"
        if ([int]$chunkStatus -ne 200) {
            $detail = (Get-Content -LiteralPath $chunkResponse -Raw -Encoding UTF8).Trim()
            throw "Direct file upload failed for $($sourceFile.Name): HTTP $chunkStatus - $detail"
        }
        $uploadedChunk = Get-Content -LiteralPath $chunkResponse -Raw -Encoding UTF8 |
            ConvertFrom-Json
        if ([int64]$uploadedChunk.received_bytes -ne [int64]$sessionFile.size_bytes) {
            throw "Direct file upload byte count mismatch for $($sourceFile.Name)."
        }
    }

    $confirmResponse = Join-Path $tempRoot "confirm-response.json"
    $confirmStatus = & curl.exe -sS `
        --max-time 180 `
        -o $confirmResponse `
        -b $memberCookieJar `
        -w "%{http_code}" `
        -X POST `
        "$PublicBaseUrl/v4/knowledge/material-intakes/upload-sessions/$intakeId/complete"
    if ([int]$confirmStatus -ne 200) {
        $detail = (Get-Content -LiteralPath $confirmResponse -Raw -Encoding UTF8).Trim()
        throw "Direct material completion failed: HTTP $confirmStatus - $detail"
    }
    $confirmed = Get-Content -LiteralPath $confirmResponse -Raw -Encoding UTF8 |
        ConvertFrom-Json
    $draftId = [string]$confirmed.draft_id
    if ($draftId -notmatch "^[0-9a-fA-F-]{36}$") {
        throw "Material confirmation did not return a valid draft ID."
    }
    if ($confirmed.status -ne "pending_review" -or [int]$confirmed.raw_document_count -ne 5) {
        throw "Direct material completion did not enter pending_review with five files."
    }

    $memberReviewRequest = Join-Path $tempRoot "member-review.json"
    $memberReviewResponse = Join-Path $tempRoot "member-review-response.json"
    $memberReviewJson = @{
        decision = "approve"
        comment = "ordinary member must not approve this batch"
    } | ConvertTo-Json -Compress
    [IO.File]::WriteAllText(
        $memberReviewRequest,
        $memberReviewJson,
        (New-Object Text.UTF8Encoding $false)
    )
    $memberReviewStatus = & curl.exe -sS `
        -o $memberReviewResponse `
        -b $memberCookieJar `
        -w "%{http_code}" `
        -H "Content-Type: application/json" `
        --data-binary "@$memberReviewRequest" `
        "$PublicBaseUrl/v4/project-memory/drafts/$draftId/review"
    if ([int]$memberReviewStatus -ne 403) {
        $detail = (Get-Content -LiteralPath $memberReviewResponse -Raw -Encoding UTF8).Trim()
        throw "Ordinary member review expected HTTP 403 but received $memberReviewStatus - $detail"
    }
    $statusAfterDeniedReview = Invoke-ScalarSql `
        "SELECT status FROM public.project_memory_drafts WHERE id='$draftId'"
    if ($statusAfterDeniedReview -ne "pending_review") {
        throw "Denied ordinary-member review changed the draft state."
    }

    $generateLinkBody = @{
        type = "magiclink"
        email = $adminEmail
    } | ConvertTo-Json -Compress
    $generatedLink = Invoke-SupabaseJsonInContainer `
        -Method POST `
        -Path "/auth/v1/admin/generate_link" `
        -Body $generateLinkBody
    $hashedToken = [string]$generatedLink.hashed_token
    if (-not $hashedToken -and $generatedLink.properties) {
        $hashedToken = [string]$generatedLink.properties.hashed_token
    }
    if (-not $hashedToken) {
        throw "Supabase magic-link generation did not return a hashed token."
    }

    $verifyBody = @{
        type = "magiclink"
        token_hash = $hashedToken
    } | ConvertTo-Json -Compress
    $verifiedAdmin = Invoke-SupabaseJsonInContainer `
        -Method POST `
        -Path "/auth/v1/verify" `
        -Body $verifyBody
    $adminAccessToken = [string]$verifiedAdmin.access_token
    if (-not $adminAccessToken) {
        throw "Supabase magic-link verification did not return an access token."
    }
    if ([string]$verifiedAdmin.user.id -ne $adminUserId) {
        throw "Supabase magic-link verification returned the wrong administrator."
    }
    $adminSupabaseSessionId = Get-JwtSessionId -AccessToken $adminAccessToken

    $sessionBody = "access_token=$([Uri]::EscapeDataString($adminAccessToken))"
    $adminSessionResponse = Invoke-WebRequest `
        -Method Post `
        -Uri "$PublicBaseUrl/auth/session" `
        -ContentType "application/x-www-form-urlencoded" `
        -Body $sessionBody `
        -WebSession $adminWebSession `
        -UseBasicParsing
    if ([int]$adminSessionResponse.StatusCode -ne 200) {
        throw "AgentOps administrator session creation failed."
    }

    $reviewJson = @{
        decision = "approve"
        comment = "普通用户上传、hanshangbo 管理员审批链路验收通过 [$marker]"
    } | ConvertTo-Json -Compress
    $adminReviewResponse = Invoke-WebRequest `
        -Method Post `
        -Uri "$PublicBaseUrl/v4/project-memory/drafts/$draftId/review" `
        -ContentType "application/json" `
        -Body $reviewJson `
        -WebSession $adminWebSession `
        -UseBasicParsing `
        -TimeoutSec 180
    if ([int]$adminReviewResponse.StatusCode -ne 200) {
        throw "hanshangbo approval failed."
    }
    $reviewed = $adminReviewResponse.Content | ConvertFrom-Json
    $documentId = [string]$reviewed.document_id
    if ($reviewed.status -ne "approved" -or $documentId -notmatch "^[0-9a-fA-F-]{36}$") {
        throw "hanshangbo approval did not create an approved document."
    }

    $verificationJson = Invoke-ScalarSql @"
SELECT json_build_object(
    'draft_status', d.status,
    'draft_created_by_user_id', d.created_by_user_id,
    'reviewed_by_user_id', d.reviewed_by_user_id,
    'reviewed_at_present', d.reviewed_at IS NOT NULL,
    'review_comment_matches', d.review_comment LIKE '%$marker%',
    'intake_status', i.status,
    'intake_created_by_user_id', i.created_by_user_id,
    'intake_file_count', (SELECT count(*) FROM public.project_material_intake_files WHERE intake_id=i.id),
    'intake_document_count', (SELECT count(*) FROM public.project_material_intake_files WHERE intake_id=i.id AND document_id IS NOT NULL),
    'ai_scan_not_run', i.preview_model IS NULL
        AND i.preview_used_fallback=false,
    'document_id', doc.id,
    'document_status', doc.status,
    'document_memory_type', doc.memory_type,
    'document_created_by_user_id', doc.created_by_user_id,
    'uploaded_by_user_id', pmd.uploaded_by_user_id,
    'file_document_id', f.document_id,
    'review_decision', r.decision,
    'reviewer_user_id', r.reviewer_user_id,
    'marker_in_chunks', (
        EXISTS (
            SELECT 1
            FROM public.document_chunks c
            JOIN public.project_material_intake_files marker_file ON marker_file.document_id=c.document_id
            WHERE marker_file.intake_id=i.id AND c.content LIKE '%$marker%'
        )
        OR EXISTS (
            SELECT 1
            FROM public.document_chunks_v2 c
            JOIN public.project_material_intake_files marker_file ON marker_file.document_id=c.document_id
            WHERE marker_file.intake_id=i.id AND c.content LIKE '%$marker%'
        )
    ),
    'upload_audit_count', (
        SELECT count(*) FROM public.audit_logs a
        WHERE a.action='material_batch_upload'
          AND a.resource_type='project_material_intake'
          AND a.resource_id='$intakeId'
    ),
    'review_audit_count', (
        SELECT count(*) FROM public.audit_logs a
        WHERE a.action='project_memory_review' AND a.resource_type='project_memory_draft' AND a.resource_id='$draftId'
    )
)
FROM public.project_memory_drafts d
JOIN public.project_material_intakes i ON i.id=d.intake_id
JOIN public.project_material_intake_files f ON f.intake_id=i.id
JOIN public.documents doc ON doc.id=f.document_id
JOIN public.project_material_documents pmd ON pmd.document_id=doc.id
JOIN public.project_memory_reviews r ON r.draft_id=d.id
WHERE d.id='$draftId' AND doc.id='$documentId'
"@
    if (-not $verificationJson) { throw "Approval verification query returned no rows." }
    $verified = $verificationJson | ConvertFrom-Json

    $expectedUploaderId = [string]$created.id
    if ($verified.draft_status -ne "approved" -or $verified.intake_status -ne "approved") {
        throw "Draft or intake did not reach approved status."
    }
    if ([int]$verified.intake_file_count -ne 5 -or [int]$verified.intake_document_count -ne 5) {
        throw "Direct upload approval did not preserve five source files and documents."
    }
    if (-not [bool]$verified.ai_scan_not_run) {
        throw "AI sensitive scan must not run"
    }
    if ([string]$verified.reviewed_by_user_id -ne $adminUserId -or
        [string]$verified.reviewer_user_id -ne $adminUserId) {
        throw "Approval was not attributed to hanshangbo."
    }
    foreach ($actualUploader in @(
        [string]$verified.draft_created_by_user_id,
        [string]$verified.intake_created_by_user_id,
        [string]$verified.document_created_by_user_id,
        [string]$verified.uploaded_by_user_id
    )) {
        if ($actualUploader -ne $expectedUploaderId) {
            throw "Approved material did not preserve the ordinary uploader identity."
        }
    }
    if ([string]$verified.file_document_id -ne $documentId -or
        [string]$verified.document_id -ne $documentId -or
        $verified.document_status -ne "ready" -or
        $verified.document_memory_type -ne "raw_project_material") {
        throw "Approved document linkage or metadata is incorrect."
    }
    if (-not [bool]$verified.reviewed_at_present -or
        -not [bool]$verified.review_comment_matches -or
        $verified.review_decision -ne "approve" -or
        -not [bool]$verified.marker_in_chunks) {
        throw (
            "Approval audit details or searchable document content are incomplete: " +
            "reviewed_at_present=$($verified.reviewed_at_present); " +
            "review_comment_matches=$($verified.review_comment_matches); " +
            "review_decision=$($verified.review_decision); " +
            "marker_in_chunks=$($verified.marker_in_chunks)"
        )
    }
    if ([int]$verified.upload_audit_count -lt 1 -or [int]$verified.review_audit_count -lt 1) {
        throw "Upload or review audit row is missing."
    }

    $result = [ordered]@{
        member_login_status = [int]$loginStatus
        upload_session_status = [int]$sessionStatus
        uploaded_file_count = 5
        confirm_status = [int]$confirmStatus
        confirm_state = [string]$confirmed.status
        ordinary_member_review_status = [int]$memberReviewStatus
        admin_account = $adminEmail
        admin_review_status = [int]$adminReviewResponse.StatusCode
        approved_state = [string]$reviewed.status
        draft_reviewer_verified = $true
        uploader_identity_preserved = $true
        searchable_marker_verified = [bool]$verified.marker_in_chunks
        document_chunk_count = [int]$reviewed.chunk_count
        intake_id = $intakeId
        draft_id = $draftId
        document_id = $documentId
    }
} finally {
    if ($memberCookieJar -and (Test-Path -LiteralPath $memberCookieJar)) {
        & curl.exe -sS -o NUL -b $memberCookieJar -X POST "$PublicBaseUrl/auth/logout" |
            Out-Null
    }

    try {
        Invoke-WebRequest `
            -Method Post `
            -Uri "$PublicBaseUrl/auth/logout" `
            -WebSession $adminWebSession `
            -UseBasicParsing `
            -ErrorAction Stop | Out-Null
    } catch {
        # There may be no AgentOps administrator session if setup failed before auth/session.
    }

    if ($adminAccessToken) {
        try {
            Invoke-SupabaseJsonInContainer `
                -Method POST `
                -Path "/auth/v1/logout?scope=local" `
                -BearerToken $adminAccessToken | Out-Null
        } catch {
            # The exact session row is removed below if GoTrue logout did not finish.
        }
    }

    $safeIntakeId = if ($intakeId -match "^[0-9a-fA-F-]{36}$") {
        "'$intakeId'::uuid"
    } else { "NULL::uuid" }
    $safeDraftId = if ($draftId -match "^[0-9a-fA-F-]{36}$") {
        "'$draftId'::uuid"
    } else { "NULL::uuid" }
    $safeDocumentId = if ($documentId -match "^[0-9a-fA-F-]{36}$") {
        "'$documentId'::uuid"
    } else { "NULL::uuid" }
    $safeUserId = if ($created -and [string]$created.id -match "^[0-9a-fA-F-]{36}$") {
        "'$($created.id)'::uuid"
    } else { "NULL::uuid" }
    $safeAdminSessionId = if ($adminSupabaseSessionId -match "^[0-9a-fA-F-]{36}$") {
        "'$adminSupabaseSessionId'::uuid"
    } else { "NULL::uuid" }
    $safeAdminUserId = if ($adminUserId -match "^[0-9a-fA-F-]{36}$") {
        "'$adminUserId'::uuid"
    } else { "NULL::uuid" }

    if ($intakeId -match "^[0-9a-fA-F-]{36}$") {
        $storageKeyText = Invoke-ScalarSql `
            "SELECT COALESCE(string_agg(storage_key, E'`n'), '') FROM public.project_material_intake_files WHERE intake_id='$intakeId'::uuid AND storage_key IS NOT NULL"
        $storageKeys = @($storageKeyText -split "`n" | Where-Object { $_ })
    }

    $cleanupSql = @"
BEGIN;
CREATE TEMP TABLE approval_cleanup_documents(id uuid PRIMARY KEY) ON COMMIT DROP;
INSERT INTO approval_cleanup_documents(id)
SELECT id FROM public.documents WHERE id=$safeDocumentId
UNION
SELECT document_id FROM public.project_material_intake_files
WHERE intake_id=$safeIntakeId AND document_id IS NOT NULL
UNION
SELECT document_id FROM public.project_material_documents
WHERE draft_id=$safeDraftId;

DELETE FROM public.audit_logs
WHERE resource_id IN (($safeIntakeId)::text, ($safeDraftId)::text);
DELETE FROM public.project_memory_reviews WHERE draft_id=$safeDraftId;
DELETE FROM public.project_material_documents
WHERE draft_id=$safeDraftId OR document_id IN (SELECT id FROM approval_cleanup_documents);
UPDATE public.project_material_intake_files
SET document_id=NULL
WHERE intake_id=$safeIntakeId;
UPDATE public.project_memory_drafts
SET approved_document_id=NULL
WHERE id=$safeDraftId;
DELETE FROM public.documents WHERE id IN (SELECT id FROM approval_cleanup_documents);
DELETE FROM public.project_memory_drafts WHERE id=$safeDraftId;
DELETE FROM public.project_material_intakes WHERE id=$safeIntakeId;
DELETE FROM public.project_members
WHERE project_id='$ProjectId'::uuid AND user_id=$safeUserId;
DELETE FROM auth.sessions
WHERE id=$safeAdminSessionId AND user_id=$safeAdminUserId;
COMMIT;
"@
    $cleanupSql | & docker exec -i supabase_db_database `
        psql -U postgres -d postgres -v ON_ERROR_STOP=1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Precise material approval cleanup failed."
    }

    foreach ($storageKey in $storageKeys) {
        if ($storageKey -notmatch "^[0-9a-f-]{36}/[0-9a-f-]{36}/[0-9a-f-]{36}\.[a-z0-9]+$") {
            throw "Unexpected material storage key during cleanup."
        }
        & docker exec agentops-api-1 rm -f -- "/var/lib/agentops/material-uploads/$storageKey"
        if ($LASTEXITCODE -ne 0) { throw "Could not delete a temporary material upload file." }
    }
    $temporaryStorageFilesRemaining = 0
    foreach ($storageKey in $storageKeys) {
        & docker exec agentops-api-1 test -e "/var/lib/agentops/material-uploads/$storageKey"
        if ($LASTEXITCODE -eq 0) { $temporaryStorageFilesRemaining += 1 }
    }
    if ($temporaryStorageFilesRemaining -ne 0) {
        throw "temporary_storage_files_remaining=$temporaryStorageFilesRemaining"
    }

    if ($created -and $created.id) {
        & (Join-Path $PSScriptRoot "Remove-TemporarySupabaseUser.ps1") `
            -UserId $created.id `
            -ServiceRoleKey $serviceRole | Out-Null
    }

    $temporaryTestRowsRemaining = Invoke-ScalarSql @"
SELECT
    (SELECT count(*) FROM public.project_material_intakes WHERE id=$safeIntakeId)
  + (SELECT count(*) FROM public.project_material_intake_files WHERE intake_id=$safeIntakeId)
  + (SELECT count(*) FROM public.project_memory_drafts WHERE id=$safeDraftId)
  + (SELECT count(*) FROM public.project_memory_reviews WHERE draft_id=$safeDraftId)
  + (SELECT count(*) FROM public.documents WHERE id=$safeDocumentId)
  + (SELECT count(*) FROM public.document_chunks WHERE document_id=$safeDocumentId)
  + (SELECT count(*) FROM public.document_chunks_v2 WHERE document_id=$safeDocumentId)
  + (SELECT count(*) FROM public.project_material_documents WHERE document_id=$safeDocumentId)
  + (SELECT count(*) FROM public.audit_logs WHERE resource_id IN (($safeIntakeId)::text, ($safeDraftId)::text))
  + (SELECT count(*) FROM public.project_members WHERE project_id='$ProjectId'::uuid AND user_id=$safeUserId)
  + (SELECT count(*) FROM auth.sessions WHERE id=$safeAdminSessionId AND user_id=$safeAdminUserId)
  + (SELECT count(*) FROM auth.users WHERE id=$safeUserId)
  + (SELECT count(*) FROM public.users WHERE id=$safeUserId)
"@
    if ([int64]$temporaryTestRowsRemaining -ne 0) {
        throw "temporary_test_rows_remaining=$temporaryTestRowsRemaining"
    }
    $cleanupResult = [ordered]@{
        temporary_test_rows_remaining = [int64]$temporaryTestRowsRemaining
        temporary_member_deleted = $true
        temporary_project_membership_deleted = $true
        admin_test_session_deleted = $true
        temporary_storage_files_remaining = $temporaryStorageFilesRemaining
        temporary_files_deleted = $true
    }

    $adminAccessToken = $null
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}

if ($null -eq $result) {
    throw "Material approval validation did not complete."
}

[pscustomobject]@{
    flow = [pscustomobject]$result
    cleanup = [pscustomobject]$cleanupResult
}
