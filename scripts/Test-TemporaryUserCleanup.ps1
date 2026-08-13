#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$CleanupScript = ""
)

$ErrorActionPreference = "Stop"
if (-not $CleanupScript) {
    $CleanupScript = Join-Path $PSScriptRoot "Remove-TemporarySupabaseUser.ps1"
}
$serviceRole = ((
    Get-Content -LiteralPath (Join-Path $PSScriptRoot "..\.env") |
        Where-Object { $_ -like "SUPABASE_SERVICE_ROLE_KEY=*" } |
        Select-Object -First 1
) -split "=", 2)[1]
if (-not $serviceRole) { throw "Missing local Supabase service role key." }

$adminHeaders = @{
    apikey = $serviceRole
    Authorization = "Bearer $serviceRole"
    "Content-Type" = "application/json"
}
$email = "temporary-cleanup-$([guid]::NewGuid().ToString('N'))@local.dev"
$password = "Cleanup!$([guid]::NewGuid().ToString('N'))9a"
$created = $null
$orgIds = @()

try {
    $body = @{
        email = $email
        password = $password
        email_confirm = $true
        user_metadata = @{ full_name = "Temporary Cleanup E2E" }
    } | ConvertTo-Json -Depth 4
    $created = Invoke-RestMethod -Method Post `
        -Uri "http://127.0.0.1:54321/auth/v1/admin/users" `
        -Headers $adminHeaders `
        -Body $body

    $orgIds = @(
        docker exec supabase_db_database psql -U postgres -d postgres -At `
            -c "SELECT mine.org_id FROM public.user_orgs mine WHERE mine.user_id='$($created.id)' AND NOT EXISTS (SELECT 1 FROM public.user_orgs other WHERE other.org_id=mine.org_id AND other.user_id<>mine.user_id)"
    ) | Where-Object { $_ -match "^[0-9a-f-]{36}$" }
    if ($orgIds.Count -lt 1) {
        throw "Expected at least one private organization."
    }

    & $CleanupScript -UserId $created.id -ServiceRoleKey $serviceRole

    $remainingUser = docker exec supabase_db_database psql -U postgres -d postgres -At `
        -c "SELECT count(*) FROM auth.users WHERE id='$($created.id)'"
    $orgIdList = ($orgIds | ForEach-Object { "'$_'" }) -join ","
    $remainingOrg = docker exec supabase_db_database psql -U postgres -d postgres -At `
        -c "SELECT count(*) FROM public.orgs WHERE id IN ($orgIdList)"
    $remainingProject = docker exec supabase_db_database psql -U postgres -d postgres -At `
        -c "SELECT count(*) FROM public.projects WHERE org_id IN ($orgIdList)"

    if ([int]$remainingUser -ne 0) { throw "Temporary auth user was not deleted." }
    if ([int]$remainingOrg -ne 0) { throw "Temporary private organization was not deleted." }
    if ([int]$remainingProject -ne 0) { throw "Temporary default project was not deleted." }

    [pscustomobject]@{
        auth_user_deleted = $true
        private_org_deleted = $true
        default_project_deleted = $true
    }
    $created = $null
} finally {
    if ($created -and $created.id) {
        docker exec supabase_db_database psql -U postgres -d postgres `
            -c "DELETE FROM public.orgs o WHERE o.id IN (SELECT mine.org_id FROM public.user_orgs mine WHERE mine.user_id='$($created.id)' AND NOT EXISTS (SELECT 1 FROM public.user_orgs other WHERE other.org_id=mine.org_id AND other.user_id<>mine.user_id))" | Out-Null
        try {
            Invoke-RestMethod -Method Delete `
                -Uri "http://127.0.0.1:54321/auth/v1/admin/users/$($created.id)" `
                -Headers $adminHeaders | Out-Null
        } catch {
            Write-Warning "Fallback auth-user cleanup failed: $($_.Exception.Message)"
        }
    }
}
