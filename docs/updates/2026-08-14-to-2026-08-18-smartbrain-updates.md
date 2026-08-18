# SmartBrain updates: 2026-08-14 to 2026-08-18

This release syncs the production-verified SmartBrain changes completed between
2026-08-14 and 2026-08-18. It intentionally excludes runtime data, credentials,
production backups, generated Next.js output, installer caches, and security
forensics.

## Security and runtime hardening

- Upgrade Next.js to `15.5.23` to close the React Flight unauthenticated RCE
  exposure found during the 2026-08-14 XMRig incident investigation.
- Run SmartBrain as the non-root `node` user with a read-only root filesystem,
  `no-new-privileges`, dropped Linux capabilities, a PID limit, and restricted
  temporary filesystems.
- Keep the temporary Token Monitor detection bounded: a missing local callback
  now times out with an actionable retry message instead of polling forever.

## Project and category management

- Move project membership administration into the selected project in the
  management workbench while keeping ordinary-member access read-only.
- Add same-parent drag sorting for first- and second-level categories, including
  pointer, touch, and keyboard operation. Sorting never changes parentage.
- Preserve completed category-migration audit history with source/target name
  snapshots while allowing retired category IDs to be cleared.
- Tighten category deletion checks for projects, requests, knowledge assets,
  custom children, and active migrations.

## Uploads, approval, and knowledge assets

- Raise original project-material upload limits to 500 MiB per file and per
  batch, with matching browser, API, and public Nginx validation.
- Support the core office/document formats used by the platform, including
  Word, Excel, PowerPoint, PDF, Markdown, and text sources.
- Route original materials, meeting records, and repository changes through the
  unified project approval queue.
- Retain upload and server-processing progress indicators and accessible error
  dialogs, including approval-to-storage progress.
- Add preview, original-file download, rename, cross-project move, and delete
  operations for project materials, Wiki content, and meeting records, subject
  to project-role permissions.

## Visibility and permissions

- All authenticated members can list every project and read each project's
  member roster, including empty projects.
- Project leaders can manage members and approve submissions only for projects
  they lead.
- `hanshangbo@local.dev` is the single global project-submission reviewer.
- Repeated approvals with the same decision are idempotent. Concurrent requests
  return the existing success result, create one resource and one review row,
  and do not conflict. A later opposite decision still returns HTTP 409.
- Refresh the approved submission resource after waiting for the draft row lock
  so concurrent responses cannot expose a stale `resource_id`.

## Database migrations

- `20260817000000_preserve_retired_department_migration_history.sql`
- `20260818010000_direct_material_upload_and_project_roles.sql`
- `20260818020000_allow_xlsx_documents.sql`
- `20260818030000_unify_content_approval_and_knowledge_assets.sql`

## Verification baseline

- Backend: 303 tests passed after the final approval-idempotency regression.
- SmartBrain: 140 tests passed, plus TypeScript, lint, and Next.js production
  build verification.
- Production approval smoke test: five concurrent identical approvals returned
  HTTP 200 with one unique resource ID, one stored resource, and one review row;
  the opposite decision returned HTTP 409.
- Real-browser verification confirmed global project visibility, read-only
  rosters outside the caller's managed projects, no management buttons for
  ordinary members, no horizontal overflow at 1280 px, and no site console
  warnings or errors.
