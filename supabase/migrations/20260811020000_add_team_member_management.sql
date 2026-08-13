BEGIN;

ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS deactivated_at timestamptz NULL,
    ADD COLUMN IF NOT EXISTS deactivated_by_user_id uuid NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'users_deactivated_by_user_id_fkey'
          AND conrelid = 'public.users'::regclass
    ) THEN
        ALTER TABLE public.users
            ADD CONSTRAINT users_deactivated_by_user_id_fkey
            FOREIGN KEY (deactivated_by_user_id)
            REFERENCES public.users(id)
            ON DELETE SET NULL;
    END IF;
END
$$;

INSERT INTO public.users (id, email, full_name, is_active)
SELECT
    auth_user.id,
    auth_user.email,
    COALESCE(
        NULLIF(BTRIM(auth_user.raw_user_meta_data ->> 'full_name'), ''),
        split_part(auth_user.email, '@', 1)
    ),
    true
FROM auth.users auth_user
LEFT JOIN public.users public_user ON public_user.id = auth_user.id
WHERE public_user.id IS NULL;

UPDATE public.users
SET is_active = true
WHERE is_active IS NULL;

CREATE INDEX IF NOT EXISTS users_active_display_idx
    ON public.users (is_active, nickname, email);

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
    'review_project_creation', 'create_team_member',
    'deactivate_team_member', 'reactivate_team_member',
    'rename_team_member_username', 'reset_team_member_password'
]));

COMMIT;
