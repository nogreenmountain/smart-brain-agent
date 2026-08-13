BEGIN;

CREATE TABLE IF NOT EXISTS public.project_creation_requests (
    id uuid PRIMARY KEY,
    requester_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    org_id uuid NOT NULL REFERENCES public.orgs(id) ON DELETE CASCADE,
    name text NOT NULL,
    environment environment NOT NULL DEFAULT 'development',
    department_id text NOT NULL REFERENCES public.departments(id),
    completed_at date NULL,
    reason text NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    review_comment text NULL,
    reviewed_by_user_id uuid NULL REFERENCES public.users(id) ON DELETE SET NULL,
    created_project_id uuid NULL REFERENCES public.projects(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    reviewed_at timestamptz NULL,
    CONSTRAINT project_creation_requests_name_check
        CHECK (char_length(btrim(name)) BETWEEN 1 AND 200),
    CONSTRAINT project_creation_requests_reason_check
        CHECK (char_length(btrim(reason)) BETWEEN 1 AND 2000),
    CONSTRAINT project_creation_requests_status_check
        CHECK (status IN ('pending', 'approved', 'rejected'))
);

CREATE INDEX IF NOT EXISTS project_creation_requests_requester_created_idx
    ON public.project_creation_requests (requester_id, created_at DESC);

CREATE INDEX IF NOT EXISTS project_creation_requests_status_created_idx
    ON public.project_creation_requests (status, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS project_creation_requests_pending_name_idx
    ON public.project_creation_requests (requester_id, org_id, lower(btrim(name)))
    WHERE status = 'pending';

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
    'rename_member_username', 'request_project_creation',
    'review_project_creation'
]));

COMMIT;
