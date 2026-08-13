BEGIN;

ALTER TABLE public.users
ADD COLUMN IF NOT EXISTS is_system_admin boolean NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS public.departments (
    id text PRIMARY KEY,
    name text NOT NULL UNIQUE,
    sort_order integer NOT NULL DEFAULT 0,
    created_by_user_id uuid NULL REFERENCES public.users(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT departments_id_check CHECK (id ~ '^[a-z][a-z0-9_-]{1,39}$'),
    CONSTRAINT departments_name_check CHECK (char_length(btrim(name)) BETWEEN 1 AND 80)
);

INSERT INTO public.departments (id, name, sort_order)
VALUES
    ('research', '研发', 1),
    ('marketing', '市场', 2),
    ('business', '业务', 3)
ON CONFLICT (id) DO UPDATE
SET name = excluded.name,
    sort_order = excluded.sort_order;

UPDATE public.users AS target
SET is_system_admin = true
FROM auth.users AS auth_user
WHERE target.id = auth_user.id
  AND lower(auth_user.email) = 'hanshangbo@local.dev';

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
    'rename_member_username'
]));

COMMIT;
