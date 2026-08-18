#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$UserId,
    [string]$ServiceRoleKey = ""
)

$ErrorActionPreference = "Stop"
if ($UserId -notmatch "^[0-9a-fA-F-]{36}$") {
    throw "UserId must be a UUID."
}
if (-not $ServiceRoleKey) {
    $ServiceRoleKey = ((
        Get-Content -LiteralPath (Join-Path $PSScriptRoot "..\.env") |
            Where-Object { $_ -like "SUPABASE_SERVICE_ROLE_KEY=*" } |
            Select-Object -First 1
    ) -split "=", 2)[1]
}
if (-not $ServiceRoleKey) { throw "Missing local Supabase service role key." }

$cleanupSql = @'
DO $$
DECLARE
    unsafe_org_count integer;
BEGIN
    SELECT count(*)
      INTO unsafe_org_count
      FROM public.orgs o
      JOIN public.user_orgs mine
        ON mine.org_id = o.id
       AND mine.user_id = '__USER_ID__'::uuid
     WHERE NOT EXISTS (
               SELECT 1
                 FROM public.user_orgs other
                WHERE other.org_id = o.id
                  AND other.user_id <> mine.user_id
           )
       AND (
           EXISTS (
               SELECT 1
                 FROM public.projects p
                WHERE p.org_id = o.id
                  AND (
                      p.name <> 'Default Project'
                      OR EXISTS (SELECT 1 FROM public.project_members x WHERE x.project_id = p.id)
                      OR EXISTS (SELECT 1 FROM public.documents x WHERE x.project_id = p.id)
                      OR EXISTS (SELECT 1 FROM public.document_chunks x WHERE x.project_id = p.id)
                      OR EXISTS (SELECT 1 FROM public.document_chunks_v2 x WHERE x.project_id = p.id)
                      OR EXISTS (SELECT 1 FROM public.meeting_summaries x WHERE x.project_id = p.id)
                      OR EXISTS (SELECT 1 FROM public.project_material_documents x WHERE x.project_id = p.id)
                      OR EXISTS (SELECT 1 FROM public.project_material_intakes x WHERE x.project_id = p.id)
                      OR EXISTS (SELECT 1 FROM public.project_memory_drafts x WHERE x.project_id = p.id)
                      OR EXISTS (SELECT 1 FROM public.project_repositories x WHERE x.project_id = p.id)
                      OR EXISTS (SELECT 1 FROM public.project_wiki_changes x WHERE x.project_id = p.id)
                      OR EXISTS (SELECT 1 FROM public.project_wiki_pages x WHERE x.project_id = p.id)
                      OR EXISTS (SELECT 1 FROM public.project_wiki_processed_sources x WHERE x.project_id = p.id)
                      OR EXISTS (SELECT 1 FROM public.ai_chat_sessions x WHERE x.project_id = p.id)
                      OR EXISTS (SELECT 1 FROM public.ai_monitor_devices x WHERE x.project_id = p.id)
                      OR EXISTS (SELECT 1 FROM public.sessions x WHERE x.project_id = p.id OR x.project_id_secondary = p.id)
                      OR EXISTS (SELECT 1 FROM public.cc_switch_usage_daily x WHERE x.project_id = p.id)
                      OR EXISTS (SELECT 1 FROM public.cc_switch_usage_sync_status x WHERE x.project_id = p.id)
                      OR EXISTS (SELECT 1 FROM deploy.deployments x WHERE x.project_id = p.id)
                      OR EXISTS (SELECT 1 FROM deploy.projects x WHERE x.id = p.id)
                  )
           )
           OR EXISTS (SELECT 1 FROM public.billing_periods x WHERE x.org_id = o.id)
           OR EXISTS (SELECT 1 FROM public.org_invites x WHERE x.org_id = o.id)
           OR EXISTS (SELECT 1 FROM public.billing_audit_logs x WHERE x.org_id = o.id)
       );

    IF unsafe_org_count > 0 THEN
        RAISE EXCEPTION 'Refusing to delete a temporary user whose private organization contains business data';
    END IF;

    DELETE FROM public.orgs o
     USING public.user_orgs mine
     WHERE mine.org_id = o.id
       AND mine.user_id = '__USER_ID__'::uuid
       AND NOT EXISTS (
               SELECT 1
                 FROM public.user_orgs other
                WHERE other.org_id = o.id
                  AND other.user_id <> mine.user_id
           );
END
$$;
'@.Replace("__USER_ID__", $UserId)

$cleanupSql | & docker exec -i supabase_db_database psql -U postgres -d postgres -v ON_ERROR_STOP=1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Private organization cleanup failed for temporary user $UserId."
}

$headers = @{
    apikey = $ServiceRoleKey
    Authorization = "Bearer $ServiceRoleKey"
}
try {
    Invoke-RestMethod -Method Delete `
        -Uri "http://127.0.0.1:54321/auth/v1/admin/users/$UserId" `
        -Headers $headers `
        -TimeoutSec 5 | Out-Null
} catch {
    $python = @'
import os
import sys
import urllib.error
import urllib.request

user_id = sys.argv[1]
service_role = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
if not service_role:
    raise SystemExit("Missing SUPABASE_SERVICE_ROLE_KEY inside Admin API transport.")

request = urllib.request.Request(
    "http://supabase_kong_database:8000/auth/v1/admin/users/" + user_id,
    method="DELETE",
    headers={
        "apikey": service_role,
        "Authorization": "Bearer " + service_role,
    },
)
try:
    with urllib.request.urlopen(request, timeout=30) as response:
        response.read()
except urllib.error.HTTPError as exc:
    detail = exc.read().decode("utf-8", errors="replace")
    print(f"Supabase Admin API returned HTTP {exc.code}: {detail}", file=sys.stderr)
    raise SystemExit(1)
'@

    $previousServiceRole = $env:SUPABASE_SERVICE_ROLE_KEY
    try {
        $env:SUPABASE_SERVICE_ROLE_KEY = $ServiceRoleKey
        $python | & docker exec -i `
            -e SUPABASE_SERVICE_ROLE_KEY `
            agentops-api-1 `
            /app/.venv/bin/python - $UserId | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Supabase Admin API container transport failed while deleting temporary user $UserId."
        }
    } finally {
        if ($null -eq $previousServiceRole) {
            Remove-Item Env:SUPABASE_SERVICE_ROLE_KEY -ErrorAction SilentlyContinue
        } else {
            $env:SUPABASE_SERVICE_ROLE_KEY = $previousServiceRole
        }
    }
}

Write-Output "temporary_user_deleted=True"
Write-Output "empty_private_orgs_deleted=True"
