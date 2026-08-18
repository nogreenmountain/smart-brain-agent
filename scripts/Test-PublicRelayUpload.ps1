#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$PublicBaseUrl = "https://39.105.79.0",
    [string]$ProjectId = "dfaefd9a-8e5e-4775-bc18-e3d551c651e4",
    [string]$DepartmentId = "",
    [string]$UploadPath = "",
    [string]$ExpectedText = ""
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

$email = "public-relay-upload-$([guid]::NewGuid().ToString('N'))@local.dev"
$password = "Relay!$([guid]::NewGuid().ToString('N'))9a"
$adminHeaders = @{
    apikey = $serviceRole
    Authorization = "Bearer $serviceRole"
    "Content-Type" = "application/json"
}

function Invoke-SupabaseAdminApiInContainer {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("POST", "DELETE")]
        [string]$Method,
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [string]$Body = ""
    )

    $python = @'
import base64
import os
import sys
import urllib.error
import urllib.request

method, path = sys.argv[1:3]
service_role = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
if not service_role:
    raise SystemExit("Missing SUPABASE_SERVICE_ROLE_KEY inside Admin API transport.")

payload = base64.b64decode(os.environ.get("SB_ADMIN_BODY_BASE64", ""))
request = urllib.request.Request(
    "http://supabase_kong_database:8000" + path,
    data=payload or None,
    method=method,
    headers={
        "apikey": service_role,
        "Authorization": "Bearer " + service_role,
        "Content-Type": "application/json",
    },
)
try:
    with urllib.request.urlopen(request, timeout=30) as response:
        sys.stdout.buffer.write(response.read())
except urllib.error.HTTPError as exc:
    detail = exc.read().decode("utf-8", errors="replace")
    print(f"Supabase Admin API returned HTTP {exc.code}: {detail}", file=sys.stderr)
    raise SystemExit(1)
'@

    $previousServiceRole = $env:SUPABASE_SERVICE_ROLE_KEY
    $previousAdminBody = $env:SB_ADMIN_BODY_BASE64
    try {
        $env:SUPABASE_SERVICE_ROLE_KEY = $serviceRole
        $env:SB_ADMIN_BODY_BASE64 = [Convert]::ToBase64String(
            [Text.Encoding]::UTF8.GetBytes($Body)
        )
        $response = $python | & docker exec -i `
            -e SUPABASE_SERVICE_ROLE_KEY `
            -e SB_ADMIN_BODY_BASE64 `
            agentops-api-1 `
            /app/.venv/bin/python - $Method $Path
        if ($LASTEXITCODE -ne 0) {
            throw "Supabase Admin API container transport failed for $Method $Path."
        }
        if ($response) {
            return ($response -join "`n") | ConvertFrom-Json
        }
        return $null
    } finally {
        if ($null -eq $previousServiceRole) {
            Remove-Item Env:SUPABASE_SERVICE_ROLE_KEY -ErrorAction SilentlyContinue
        } else {
            $env:SUPABASE_SERVICE_ROLE_KEY = $previousServiceRole
        }
        if ($null -eq $previousAdminBody) {
            Remove-Item Env:SB_ADMIN_BODY_BASE64 -ErrorAction SilentlyContinue
        } else {
            $env:SB_ADMIN_BODY_BASE64 = $previousAdminBody
        }
    }
}

$created = $null
$intakeId = $null
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) (
    "smartbrain-public-upload-$([guid]::NewGuid().ToString('N'))"
)
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null

try {
    $effectiveDepartmentId = $DepartmentId.Trim()
    if (-not $effectiveDepartmentId) {
        $departmentOutput = & docker exec supabase_db_database `
            psql -U postgres -d postgres -At -v ON_ERROR_STOP=1 `
            -c "SELECT department_id FROM public.projects WHERE id='$ProjectId'"
        $departmentExitCode = $LASTEXITCODE
        $effectiveDepartmentId = ([string]($departmentOutput | Select-Object -First 1)).Trim()
        if ($departmentExitCode -ne 0 -or -not $effectiveDepartmentId) {
            throw "Could not resolve the project's current category."
        }
    }

    $createBody = @{
        email = $email
        password = $password
        email_confirm = $true
        user_metadata = @{ full_name = "Public Relay Upload Smoke" }
    } | ConvertTo-Json -Depth 4
    try {
        $created = Invoke-RestMethod -Method Post `
            -Uri "http://127.0.0.1:54321/auth/v1/admin/users" `
            -Headers $adminHeaders `
            -Body $createBody `
            -TimeoutSec 5
    } catch {
        $created = Invoke-SupabaseAdminApiInContainer `
            -Method POST `
            -Path "/auth/v1/admin/users" `
            -Body $createBody
    }

    docker exec supabase_db_database psql -U postgres -d postgres -v ON_ERROR_STOP=1 `
        -c "INSERT INTO public.project_members(project_id,user_id,role) VALUES ('$ProjectId','$($created.id)','business_user') ON CONFLICT (project_id,user_id) DO UPDATE SET role=EXCLUDED.role" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not add the temporary project member." }

    $loginRequest = Join-Path $tempRoot "login-request.json"
    $loginResponse = Join-Path $tempRoot "login-response.json"
    $cookieJar = Join-Path $tempRoot "cookies.txt"
    $loginJson = @{ email = $email; password = $password } | ConvertTo-Json -Compress
    [IO.File]::WriteAllText($loginRequest, $loginJson, (New-Object Text.UTF8Encoding $false))
    $loginStatus = & curl.exe -sS `
        -o $loginResponse `
        -c $cookieJar `
        -w "%{http_code}" `
        -H "Origin: $PublicBaseUrl" `
        -H "Content-Type: application/json" `
        --data-binary "@$loginRequest" `
        "$PublicBaseUrl/auth/login"
    if ([int]$loginStatus -ne 200) { throw "Temporary member login failed: HTTP $loginStatus" }

    $uploadPath = if ($UploadPath) {
        if (-not (Test-Path -LiteralPath $UploadPath -PathType Leaf)) {
            throw "Upload fixture does not exist: $UploadPath"
        }
        (Resolve-Path -LiteralPath $UploadPath).Path
    } else {
        $defaultUploadPath = Join-Path $tempRoot "public-relay-smoke.txt"
        [IO.File]::WriteAllText(
            $defaultUploadPath,
            "Public relay upload smoke test. This file contains no credentials or personal information.",
            (New-Object Text.UTF8Encoding $false)
        )
        $defaultUploadPath
    }
    $previewPath = Join-Path $tempRoot "preview.json"
    $previewStatus = & curl.exe -sS `
        --max-time 120 `
        -o $previewPath `
        -b $cookieJar `
        -w "%{http_code}" `
        -F "project_id=$ProjectId" `
        -F "department_id=$effectiveDepartmentId" `
        -F "files=@$uploadPath" `
        "$PublicBaseUrl/v4/knowledge/material-intakes/preview"
    if ([int]$previewStatus -ne 200) {
        $previewDetail = if (Test-Path -LiteralPath $previewPath) {
            (Get-Content -LiteralPath $previewPath -Raw -Encoding UTF8).Trim()
        } else {
            "<empty response>"
        }
        throw "Public upload preview failed: HTTP $previewStatus - $previewDetail"
    }
    $preview = Get-Content -Raw -Encoding UTF8 $previewPath | ConvertFrom-Json
    $intakeId = [string]$preview.id
    $extractedTextVerified = $null
    if ($ExpectedText) {
        $extractedOutput = & docker exec supabase_db_database `
            psql -U postgres -d postgres -At -v ON_ERROR_STOP=1 `
            -c "SELECT extracted_text FROM public.project_material_intake_files WHERE intake_id='$intakeId' ORDER BY filename"
        $extractedExitCode = $LASTEXITCODE
        if ($extractedExitCode -ne 0) {
            throw "Could not inspect extracted upload text."
        }
        $extractedText = $extractedOutput -join "`n"
        $extractedTextVerified = $extractedText.Contains($ExpectedText)
        if (-not $extractedTextVerified) {
            throw "Uploaded file was accepted but expected extracted text was not found."
        }
    }

    $deleteStatus = & curl.exe -sS `
        -o NUL `
        -b $cookieJar `
        -w "%{http_code}" `
        -X DELETE `
        "$PublicBaseUrl/v4/knowledge/material-intakes/$intakeId"
    if ([int]$deleteStatus -ne 204) { throw "Preview cleanup failed: HTTP $deleteStatus" }
    $intakeId = $null

    [pscustomobject]@{
        login_status = [int]$loginStatus
        preview_status = [int]$previewStatus
        preview_file_count = @($preview.items).Count
        preview_filename = $preview.items[0].filename
        preview_format = $preview.items[0].format
        extracted_text_verified = $extractedTextVerified
        preview_recommendation = $preview.items[0].recommendation
        preview_used_fallback = [bool]$preview.used_fallback
        preview_delete_status = [int]$deleteStatus
    }
} finally {
    if ($intakeId -and $intakeId -match "^[0-9a-f-]{36}$") {
        docker exec supabase_db_database psql -U postgres -d postgres `
            -c "DELETE FROM public.project_material_intakes WHERE id='$intakeId'" | Out-Null
    }
    if ($created -and $created.id) {
        docker exec supabase_db_database psql -U postgres -d postgres `
            -c "DELETE FROM public.project_members WHERE project_id='$ProjectId' AND user_id='$($created.id)'" | Out-Null
        & (Join-Path $PSScriptRoot "Remove-TemporarySupabaseUser.ps1") `
            -UserId $created.id `
            -ServiceRoleKey $serviceRole | Out-Null
        Write-Output "temporary_upload_user_deleted=True"
    }
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
