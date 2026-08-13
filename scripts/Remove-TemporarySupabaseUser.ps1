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
Invoke-RestMethod -Method Delete `
    -Uri "http://127.0.0.1:54321/auth/v1/admin/users/$UserId" `
    -Headers $headers | Out-Null

Write-Output "temporary_user_deleted=True"
Write-Output "empty_private_orgs_deleted=True"
