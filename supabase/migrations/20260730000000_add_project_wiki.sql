BEGIN;

CREATE TABLE IF NOT EXISTS public.project_wiki_compile_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    status text NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'failed')),
    trigger_type text NOT NULL
        CHECK (trigger_type IN ('manual', 'scheduled')),
    triggered_by_user_id uuid,
    model text NOT NULL,
    source_count integer NOT NULL DEFAULT 0 CHECK (source_count >= 0),
    candidate_count integer NOT NULL DEFAULT 0 CHECK (candidate_count >= 0),
    auto_applied_count integer NOT NULL DEFAULT 0 CHECK (auto_applied_count >= 0),
    pending_review_count integer NOT NULL DEFAULT 0 CHECK (pending_review_count >= 0),
    discarded_count integer NOT NULL DEFAULT 0 CHECK (discarded_count >= 0),
    error_message text,
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_project_wiki_runs_project_started
    ON public.project_wiki_compile_runs (project_id, started_at DESC);

CREATE TABLE IF NOT EXISTS public.project_wiki_pages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    page_key text NOT NULL,
    title text NOT NULL,
    page_type text NOT NULL CHECK (
        page_type IN (
            'fact', 'concept', 'procedure', 'troubleshooting', 'lesson',
            'decision', 'policy', 'architecture', 'requirement', 'note'
        )
    ),
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'archived')),
    summary text NOT NULL DEFAULT '',
    markdown_content text NOT NULL,
    usefulness numeric(4, 3) NOT NULL CHECK (usefulness >= 0 AND usefulness <= 1),
    confidence numeric(4, 3) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    current_version integer NOT NULL DEFAULT 1 CHECK (current_version > 0),
    document_id uuid REFERENCES public.documents(id) ON DELETE SET NULL,
    created_by_user_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, page_key)
);

CREATE INDEX IF NOT EXISTS idx_project_wiki_pages_project_updated
    ON public.project_wiki_pages (project_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_project_wiki_pages_type
    ON public.project_wiki_pages (project_id, page_type);

CREATE TABLE IF NOT EXISTS public.project_wiki_page_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    page_id uuid NOT NULL REFERENCES public.project_wiki_pages(id) ON DELETE CASCADE,
    version integer NOT NULL CHECK (version > 0),
    markdown_content text NOT NULL,
    summary text NOT NULL DEFAULT '',
    source_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    change_reason text NOT NULL,
    created_by_user_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (page_id, version)
);

CREATE INDEX IF NOT EXISTS idx_project_wiki_versions_page
    ON public.project_wiki_page_versions (page_id, version DESC);

CREATE TABLE IF NOT EXISTS public.project_wiki_page_sources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    page_id uuid NOT NULL REFERENCES public.project_wiki_pages(id) ON DELETE CASCADE,
    source_type text NOT NULL,
    source_id text NOT NULL,
    locator text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (page_id, source_type, source_id)
);

CREATE INDEX IF NOT EXISTS idx_project_wiki_sources_source
    ON public.project_wiki_page_sources (source_type, source_id);

CREATE TABLE IF NOT EXISTS public.project_wiki_links (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    from_page_id uuid NOT NULL REFERENCES public.project_wiki_pages(id) ON DELETE CASCADE,
    to_title text NOT NULL,
    relation text NOT NULL DEFAULT 'related',
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (from_page_id, to_title, relation)
);

CREATE INDEX IF NOT EXISTS idx_project_wiki_links_from
    ON public.project_wiki_links (from_page_id);

CREATE TABLE IF NOT EXISTS public.project_wiki_changes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid NOT NULL REFERENCES public.project_wiki_compile_runs(id) ON DELETE CASCADE,
    project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    page_key text NOT NULL,
    title text NOT NULL,
    page_type text NOT NULL,
    disposition text NOT NULL
        CHECK (disposition IN ('auto_apply', 'pending_review', 'discard')),
    reason_code text NOT NULL,
    status text NOT NULL
        CHECK (status IN ('pending_review', 'applied', 'rejected', 'discarded')),
    summary text NOT NULL DEFAULT '',
    proposed_markdown text NOT NULL,
    usefulness numeric(4, 3) NOT NULL CHECK (usefulness >= 0 AND usefulness <= 1),
    confidence numeric(4, 3) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    contradiction boolean NOT NULL DEFAULT false,
    source_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    link_titles jsonb NOT NULL DEFAULT '[]'::jsonb,
    page_id uuid REFERENCES public.project_wiki_pages(id) ON DELETE SET NULL,
    reviewed_by_user_id uuid,
    review_comment text,
    reviewed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_project_wiki_changes_project_status
    ON public.project_wiki_changes (project_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS public.project_wiki_processed_sources (
    project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    source_id text NOT NULL,
    source_type text NOT NULL,
    content_hash text NOT NULL,
    observed_at timestamptz NOT NULL,
    last_run_id uuid REFERENCES public.project_wiki_compile_runs(id) ON DELETE SET NULL,
    processed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, source_id)
);

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
            'project_wiki_review'
        )
    );

COMMIT;
