BEGIN;

ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS nickname text;

ALTER TABLE public.users
    DROP CONSTRAINT IF EXISTS users_nickname_length_check;

ALTER TABLE public.users
    ADD CONSTRAINT users_nickname_length_check
    CHECK (nickname IS NULL OR char_length(nickname) <= 80);

ALTER TABLE public.audit_logs
    DROP CONSTRAINT IF EXISTS audit_logs_action_check;

ALTER TABLE public.audit_logs
    ADD CONSTRAINT audit_logs_action_check
    CHECK (
        action IN (
            'upload', 'search', 'answer', 'login', 'logout', 'delete_document',
            'add_member', 'remove_member', 'create_project', 'update_project',
            'delete_project', 'reset_member_password', 'workday_summary',
            'workday_enroll', 'ai_chat_ingest', 'ai_chat_list',
            'ai_monitor_device_register', 'ai_monitor_status',
            'project_memory_repository_upsert', 'project_memory_draft_create',
            'project_memory_review', 'material_batch_upload', 'knowledge_ledger_view',
            'ai_usage_view', 'ai_usage_report', 'project_wiki_compile',
            'project_wiki_view', 'project_wiki_review', 'member_wiki_view',
            'meeting_summary_view', 'meeting_summary_create',
            'update_profile', 'change_password'
        )
    );

COMMIT;
