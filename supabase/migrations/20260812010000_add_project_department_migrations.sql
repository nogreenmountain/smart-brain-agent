BEGIN;

ALTER TABLE public.departments
    ADD COLUMN IF NOT EXISTS is_direct boolean NOT NULL DEFAULT false;

ALTER TABLE public.departments
    DROP CONSTRAINT IF EXISTS departments_parent_id_fkey;

ALTER TABLE public.departments
ADD CONSTRAINT departments_parent_id_fkey
FOREIGN KEY (parent_id) REFERENCES public.departments(id) ON DELETE CASCADE;

ALTER TABLE public.departments
    DROP CONSTRAINT IF EXISTS departments_sort_order_key;

CREATE INDEX IF NOT EXISTS departments_parent_sort_order_idx
    ON public.departments (parent_id, sort_order, id);

-- Mark the two stable direct categories introduced by the strict hierarchy migration.
UPDATE public.departments
SET name = '直属分级',
    is_direct = true,
    allows_projects = true
WHERE id IN ('research-direct', 'team-management-direct');

-- A direct child uses a deterministic ID that stays below the departments ID limit,
-- including for dynamically-created roots whose own IDs may already be 37 characters.
INSERT INTO public.departments (
    id, name, sort_order, parent_id, allows_projects, is_direct
)
SELECT
    'direct-' || substr(md5(root.id), 1, 32),
    '直属分级',
    COALESCE((
        SELECT max(sibling.sort_order) + 1
        FROM public.departments sibling
        WHERE sibling.parent_id = root.id
    ), 1),
    root.id,
    true,
    true
FROM public.departments root
WHERE root.parent_id IS NULL
  AND NOT EXISTS (
      SELECT 1
      FROM public.departments direct_child
      WHERE direct_child.parent_id = root.id
        AND direct_child.is_direct
  )
ON CONFLICT (id) DO UPDATE
SET name = EXCLUDED.name,
    parent_id = EXCLUDED.parent_id,
    allows_projects = true,
    is_direct = true;

CREATE UNIQUE INDEX IF NOT EXISTS departments_one_direct_child_per_root_idx
    ON public.departments (parent_id)
    WHERE is_direct;

ALTER TABLE public.departments
    DROP CONSTRAINT IF EXISTS departments_direct_category_shape_check;

ALTER TABLE public.departments
ADD CONSTRAINT departments_direct_category_shape_check CHECK (
    NOT is_direct OR (
        parent_id IS NOT NULL
        AND allows_projects
        AND name = '直属分级'
    )
);

CREATE OR REPLACE FUNCTION public.protect_direct_department()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.is_direct AND (
        NEW.name IS DISTINCT FROM OLD.name
        OR NEW.parent_id IS DISTINCT FROM OLD.parent_id
        OR NEW.allows_projects IS DISTINCT FROM OLD.allows_projects
        OR NEW.is_direct IS DISTINCT FROM OLD.is_direct
    ) THEN
        RAISE EXCEPTION 'generated direct categories cannot be renamed, moved, or disabled';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS departments_protect_direct_category
    ON public.departments;

CREATE TRIGGER departments_protect_direct_category
BEFORE UPDATE ON public.departments
FOR EACH ROW
EXECUTE FUNCTION public.protect_direct_department();

CREATE OR REPLACE FUNCTION public.protect_direct_department_delete()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.is_direct AND pg_trigger_depth() = 1 THEN
        RAISE EXCEPTION 'generated direct categories cannot be deleted directly';
    END IF;
    RETURN OLD;
END;
$$;

DROP TRIGGER IF EXISTS departments_protect_direct_category_delete
    ON public.departments;

CREATE TRIGGER departments_protect_direct_category_delete
BEFORE DELETE ON public.departments
FOR EACH ROW
EXECUTE FUNCTION public.protect_direct_department_delete();

CREATE OR REPLACE FUNCTION public.ensure_root_direct_department()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.parent_id IS NULL THEN
        INSERT INTO public.departments (
            id, name, sort_order, parent_id, allows_projects, is_direct
        )
        VALUES (
            'direct-' || substr(md5(NEW.id), 1, 32),
            '直属分级',
            COALESCE((
                SELECT max(sibling.sort_order) + 1
                FROM public.departments sibling
                WHERE sibling.parent_id = NEW.id
            ), 1),
            NEW.id,
            true,
            true
        )
        ON CONFLICT (id) DO UPDATE
        SET name = EXCLUDED.name,
            parent_id = EXCLUDED.parent_id,
            allows_projects = true,
            is_direct = true;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS departments_ensure_root_direct_child
    ON public.departments;

CREATE TRIGGER departments_ensure_root_direct_child
AFTER INSERT OR UPDATE OF parent_id ON public.departments
FOR EACH ROW
WHEN (NEW.parent_id IS NULL)
EXECUTE FUNCTION public.ensure_root_direct_department();

CREATE TABLE IF NOT EXISTS public.project_department_migrations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    source_department_id text NOT NULL REFERENCES public.departments(id),
    target_department_id text NOT NULL REFERENCES public.departments(id),
    requested_by_user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE RESTRICT,
    idempotency_key text NULL,
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    current_step text NOT NULL DEFAULT 'queued',
    progress integer NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    raw_material_count integer NOT NULL DEFAULT 0 CHECK (raw_material_count >= 0),
    wiki_page_count integer NOT NULL DEFAULT 0 CHECK (wiki_page_count >= 0),
    meeting_record_count integer NOT NULL DEFAULT 0 CHECK (meeting_record_count >= 0),
    documents_updated integer NOT NULL DEFAULT 0 CHECK (documents_updated >= 0),
    material_intakes_updated integer NOT NULL DEFAULT 0 CHECK (material_intakes_updated >= 0),
    memory_drafts_updated integer NOT NULL DEFAULT 0 CHECK (memory_drafts_updated >= 0),
    pending_requests_updated integer NOT NULL DEFAULT 0 CHECK (pending_requests_updated >= 0),
    verified boolean NOT NULL DEFAULT false,
    error_message text NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz NULL,
    completed_at timestamptz NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT project_department_migrations_distinct_departments_check
        CHECK (source_department_id <> target_department_id),
    CONSTRAINT project_department_migrations_idempotency_key_check
        CHECK (idempotency_key IS NULL OR char_length(idempotency_key) BETWEEN 1 AND 120)
);

CREATE UNIQUE INDEX IF NOT EXISTS project_department_migrations_active_project_idx
    ON public.project_department_migrations (project_id)
    WHERE status IN ('queued', 'running');

CREATE UNIQUE INDEX IF NOT EXISTS project_department_migrations_idempotency_idx
    ON public.project_department_migrations (
        project_id, requested_by_user_id, idempotency_key
    )
    WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS project_department_migrations_project_created_idx
    ON public.project_department_migrations (project_id, created_at DESC);

-- Move any legacy project that still points at a root to that root's direct child.
-- The preceding strict migration handled the two fixed roots; this also covers
-- dynamically-created roots and partially-applied historical states.
UPDATE public.projects project
SET department_id = direct_child.id
FROM public.departments root
JOIN public.departments direct_child
  ON direct_child.parent_id = root.id
 AND direct_child.is_direct
WHERE project.department_id = root.id
  AND root.parent_id IS NULL;

UPDATE public.project_creation_requests request_row
SET department_id = direct_child.id,
    updated_at = now()
FROM public.departments root
JOIN public.departments direct_child
  ON direct_child.parent_id = root.id
 AND direct_child.is_direct
WHERE request_row.department_id = root.id
  AND root.parent_id IS NULL;

-- Repair all current redundant snapshots before the API starts enforcing equality.
UPDATE public.documents document
SET department_id = project.department_id
FROM public.projects project
WHERE project.id = document.project_id
  AND document.department_id IS DISTINCT FROM project.department_id;

UPDATE public.project_material_intakes intake
SET department_id = project.department_id,
    updated_at = now()
FROM public.projects project
WHERE project.id = intake.project_id
  AND intake.department_id IS DISTINCT FROM project.department_id;

UPDATE public.project_memory_drafts draft
SET department_id = project.department_id,
    updated_at = now()
FROM public.projects project
WHERE project.id = draft.project_id
  AND draft.department_id IS DISTINCT FROM project.department_id;

UPDATE public.project_creation_requests request_row
SET department_id = project.department_id,
    updated_at = now()
FROM public.projects project
WHERE request_row.created_project_id = project.id
  AND request_row.department_id IS DISTINCT FROM project.department_id;

ALTER TABLE public.audit_logs
    DROP CONSTRAINT IF EXISTS audit_logs_action_check;

ALTER TABLE public.audit_logs
ADD CONSTRAINT audit_logs_action_check CHECK (action = ANY (ARRAY[
    'upload', 'search', 'answer', 'login', 'logout', 'delete_document',
    'add_member', 'remove_member', 'create_project', 'update_project',
    'delete_project', 'reset_member_password', 'workday_summary',
    'workday_enroll', 'ai_chat_ingest', 'ai_chat_list',
    'ai_monitor_device_register', 'ai_monitor_status',
    'project_memory_repository_upsert', 'project_memory_draft_create',
    'project_memory_review', 'material_batch_upload', 'knowledge_ledger_view',
    'ai_usage_view', 'ai_usage_report', 'ai_usage_sync',
    'project_wiki_compile', 'project_wiki_view', 'project_wiki_review',
    'member_wiki_view', 'meeting_summary_view', 'meeting_summary_create',
    'update_profile', 'change_password', 'create_department',
    'update_department', 'delete_department', 'rename_member_username',
    'request_project_creation', 'review_project_creation',
    'create_team_member', 'deactivate_team_member', 'reactivate_team_member',
    'rename_team_member_username', 'reset_team_member_password',
    'project_department_migration'
]));

COMMIT;
