BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS public.member_wiki_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cutoff_at timestamptz NOT NULL,
    timezone text NOT NULL DEFAULT 'Asia/Shanghai',
    status text NOT NULL,
    model text NOT NULL,
    candidate_member_count integer NOT NULL DEFAULT 0,
    updated_member_count integer NOT NULL DEFAULT 0,
    empty_member_count integer NOT NULL DEFAULT 0,
    session_count integer NOT NULL DEFAULT 0,
    experience_count integer NOT NULL DEFAULT 0,
    failure_count integer NOT NULL DEFAULT 0,
    error_message text,
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    CONSTRAINT member_wiki_runs_timezone_check CHECK (timezone = 'Asia/Shanghai'),
    CONSTRAINT member_wiki_runs_status_check CHECK (status IN ('running', 'completed', 'failed')),
    CONSTRAINT member_wiki_runs_count_check CHECK (
        candidate_member_count >= 0 AND updated_member_count >= 0
        AND empty_member_count >= 0 AND session_count >= 0
        AND experience_count >= 0 AND failure_count >= 0
    )
);

CREATE INDEX IF NOT EXISTS idx_member_wiki_runs_started
    ON public.member_wiki_runs (started_at DESC);

CREATE TABLE IF NOT EXISTS public.member_wiki_experiences (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id text NOT NULL,
    employee_name text NOT NULL,
    experience_key text NOT NULL,
    title text NOT NULL,
    task_type text NOT NULL,
    outcome text NOT NULL,
    summary text NOT NULL DEFAULT '',
    structured_content jsonb NOT NULL,
    markdown_content text NOT NULL,
    tags text[] NOT NULL DEFAULT ARRAY[]::text[],
    tools text[] NOT NULL DEFAULT ARRAY[]::text[],
    confidence numeric(4, 3) NOT NULL DEFAULT 0,
    first_observed date NOT NULL,
    last_observed date NOT NULL,
    observation_count integer NOT NULL DEFAULT 1,
    source_session_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    source_trace_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    current_version integer NOT NULL DEFAULT 1,
    embedding vector(1024),
    embedding_model text,
    embedding_version text,
    status text NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT member_wiki_experiences_employee_key UNIQUE (employee_id, experience_key),
    CONSTRAINT member_wiki_experiences_key_check CHECK (
        experience_key ~ '^[a-z0-9][a-z0-9_-]{2,119}$'
    ),
    CONSTRAINT member_wiki_experiences_task_type_check CHECK (
        task_type IN (
            'development', 'debugging', 'deployment', 'configuration',
            'data_processing', 'documentation', 'testing', 'research',
            'operations', 'other'
        )
    ),
    CONSTRAINT member_wiki_experiences_outcome_check CHECK (
        outcome IN ('success', 'partial', 'failure')
    ),
    CONSTRAINT member_wiki_experiences_status_check CHECK (
        status IN ('active', 'stale')
    ),
    CONSTRAINT member_wiki_experiences_confidence_check CHECK (
        confidence >= 0 AND confidence <= 1
    ),
    CONSTRAINT member_wiki_experiences_observation_check CHECK (
        observation_count >= 1 AND last_observed >= first_observed
    ),
    CONSTRAINT member_wiki_experiences_version_check CHECK (current_version >= 1)
);

CREATE INDEX IF NOT EXISTS idx_member_wiki_experiences_member_updated
    ON public.member_wiki_experiences (employee_id, updated_at DESC)
    WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_member_wiki_experiences_member_type
    ON public.member_wiki_experiences (employee_id, task_type, outcome, last_observed DESC)
    WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_member_wiki_experiences_tags
    ON public.member_wiki_experiences USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_member_wiki_experiences_trgm
    ON public.member_wiki_experiences USING GIN (
        (title || ' ' || summary || ' ' || markdown_content) gin_trgm_ops
    );
CREATE INDEX IF NOT EXISTS idx_member_wiki_experiences_embedding
    ON public.member_wiki_experiences USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.member_wiki_experience_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    experience_id uuid NOT NULL REFERENCES public.member_wiki_experiences(id) ON DELETE CASCADE,
    version integer NOT NULL,
    run_id uuid REFERENCES public.member_wiki_runs(id) ON DELETE SET NULL,
    structured_content jsonb NOT NULL,
    markdown_content text NOT NULL,
    source_session_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT member_wiki_experience_versions_key UNIQUE (experience_id, version),
    CONSTRAINT member_wiki_experience_versions_version_check CHECK (version >= 1)
);

CREATE INDEX IF NOT EXISTS idx_member_wiki_versions_experience
    ON public.member_wiki_experience_versions (experience_id, version DESC);

CREATE TABLE IF NOT EXISTS public.member_wiki_experience_sources (
    experience_id uuid NOT NULL REFERENCES public.member_wiki_experiences(id) ON DELETE CASCADE,
    session_id uuid NOT NULL,
    trace_id text,
    observed_at timestamptz NOT NULL,
    source text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (experience_id, session_id)
);

CREATE INDEX IF NOT EXISTS idx_member_wiki_sources_session
    ON public.member_wiki_experience_sources (session_id);

CREATE TABLE IF NOT EXISTS public.member_wiki_processed_sessions (
    session_id uuid PRIMARY KEY,
    employee_id text NOT NULL,
    run_id uuid REFERENCES public.member_wiki_runs(id) ON DELETE SET NULL,
    observed_at timestamptz NOT NULL,
    experience_count integer NOT NULL DEFAULT 0,
    processed_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT member_wiki_processed_count_check CHECK (experience_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_member_wiki_processed_employee
    ON public.member_wiki_processed_sessions (employee_id, observed_at DESC);

ALTER TABLE public.audit_logs
    DROP CONSTRAINT IF EXISTS audit_logs_action_check;

ALTER TABLE public.audit_logs
    ADD CONSTRAINT audit_logs_action_check
    CHECK (
        action IN (
            'upload',
            'search',
            'answer',
            'login',
            'logout',
            'delete_document',
            'add_member',
            'remove_member',
            'create_project',
            'update_project',
            'delete_project',
            'reset_member_password',
            'workday_summary',
            'workday_enroll',
            'ai_chat_ingest',
            'ai_chat_list',
            'ai_monitor_device_register',
            'ai_monitor_status',
            'project_memory_repository_upsert',
            'project_memory_draft_create',
            'project_memory_review',
            'material_batch_upload',
            'knowledge_ledger_view',
            'ai_usage_view',
            'ai_usage_report',
            'project_wiki_compile',
            'project_wiki_view',
            'project_wiki_review',
            'member_wiki_view'
        )
    );

COMMIT;
