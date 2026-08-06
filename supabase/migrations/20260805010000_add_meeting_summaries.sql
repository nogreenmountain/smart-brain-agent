BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS public.meeting_summaries (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
    meeting_date date NOT NULL,
    participants text[] NOT NULL DEFAULT ARRAY[]::text[],
    tags text[] NOT NULL DEFAULT ARRAY[]::text[],
    summary_markdown text NOT NULL CHECK (char_length(summary_markdown) > 0),
    decisions text[] NOT NULL DEFAULT ARRAY[]::text[],
    action_items text[] NOT NULL DEFAULT ARRAY[]::text[],
    source_filename text,
    created_by uuid NOT NULL,
    embedding vector(1024),
    embedding_model text,
    embedding_version text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_meeting_summaries_project_date
    ON public.meeting_summaries (project_id, meeting_date DESC, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_meeting_summaries_tags
    ON public.meeting_summaries USING gin (tags);
CREATE INDEX IF NOT EXISTS idx_meeting_summaries_title_trgm
    ON public.meeting_summaries USING gin (title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_meeting_summaries_embedding_hnsw
    ON public.meeting_summaries USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;

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
            'meeting_summary_view', 'meeting_summary_create'
        )
    );

COMMIT;
