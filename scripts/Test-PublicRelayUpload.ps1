#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$PublicBaseUrl = "https://39.105.79.0",
    [string]$ProjectId = "dfaefd9a-8e5e-4775-bc18-e3d551c651e4",
    [string]$DepartmentId = "research"
)

$ErrorActionPreference = "Stop"
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
$created = $null
$intakeId = $null
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) (
    "smartbrain-public-upload-$([guid]::NewGuid().ToString('N'))"
)
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null

try {
    $createBody = @{
        email = $email
        password = $password
        email_confirm = $true
        user_metadata = @{ full_name = "Public Relay Upload Smoke" }
    } | ConvertTo-Json -Depth 4
    $created = Invoke-RestMethod -Method Post `
        -Uri "http://127.0.0.1:54321/auth/v1/admin/users" `
        -Headers $adminHeaders `
        -Body $createBody

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

    $uploadPath = Join-Path $tempRoot "public-relay-smoke.txt"
    [IO.File]::WriteAllText(
        $uploadPath,
        "Public relay upload smoke test. This file contains no credentials or personal information.",
        (New-Object Text.UTF8Encoding $false)
    )
    $previewPath = Join-Path $tempRoot "preview.json"
    $previewStatus = & curl.exe -sS `
        --max-time 120 `
        -o $previewPath `
        -b $cookieJar `
        -w "%{http_code}" `
        -F "project_id=$ProjectId" `
        -F "department_id=$DepartmentId" `
        -F "files=@$uploadPath;type=text/plain" `
        "$PublicBaseUrl/v4/knowledge/material-intakes/preview"
    if ([int]$previewStatus -ne 200) { throw "Public upload preview failed: HTTP $previewStatus" }
    $preview = Get-Content -Raw -Encoding UTF8 $previewPath | ConvertFrom-Json
    $intakeId = [string]$preview.id

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
