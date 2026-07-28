BEGIN;

CREATE TABLE IF NOT EXISTS public.departments (
    id text PRIMARY KEY CHECK (id IN ('research', 'marketing', 'business')),
    name text NOT NULL UNIQUE,
    sort_order integer NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO public.departments (id, name, sort_order)
VALUES
    ('research', '研发', 1),
    ('marketing', '市场', 2),
    ('business', '业务', 3)
ON CONFLICT (id) DO UPDATE
SET name = excluded.name,
    sort_order = excluded.sort_order;

ALTER TABLE public.projects
    ADD COLUMN IF NOT EXISTS department_id text REFERENCES public.departments(id);

UPDATE public.projects
SET department_id = 'research'
WHERE department_id IS NULL;

ALTER TABLE public.projects
    ALTER COLUMN department_id SET DEFAULT 'research',
    ALTER COLUMN department_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_projects_department_id
    ON public.projects (department_id);

CREATE TABLE IF NOT EXISTS public.project_repositories (
    project_id uuid PRIMARY KEY REFERENCES public.projects(id) ON DELETE CASCADE,
    git_url text NOT NULL CHECK (git_url ~* '^https?://'),
    git_branch text NOT NULL DEFAULT 'main',
    created_by_user_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.project_memory_drafts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    department_id text NOT NULL REFERENCES public.departments(id),
    title text NOT NULL,
    status text NOT NULL DEFAULT 'pending_review'
        CHECK (status IN ('pending_review', 'approved', 'rejected')),
    template_version text NOT NULL DEFAULT 'project-memory-v1',
    markdown_content text NOT NULL,
    source_count integer NOT NULL DEFAULT 0 CHECK (source_count >= 0),
    approved_document_id uuid REFERENCES public.documents(id) ON DELETE SET NULL,
    created_by_user_id uuid,
    reviewed_by_user_id uuid,
    review_comment text,
    reviewed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_project_memory_drafts_project_status
    ON public.project_memory_drafts (project_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_project_memory_drafts_department
    ON public.project_memory_drafts (department_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.project_memory_draft_sources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id uuid NOT NULL REFERENCES public.project_memory_drafts(id) ON DELETE CASCADE,
    filename text NOT NULL,
    format text NOT NULL CHECK (format IN ('pdf', 'md', 'txt', 'html', 'docx', 'pptx')),
    extracted_text text NOT NULL,
    size_bytes bigint NOT NULL CHECK (size_bytes > 0),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_project_memory_draft_sources_draft
    ON public.project_memory_draft_sources (draft_id);

CREATE TABLE IF NOT EXISTS public.project_memory_reviews (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_id uuid NOT NULL REFERENCES public.project_memory_drafts(id) ON DELETE CASCADE,
    reviewer_user_id uuid,
    decision text NOT NULL CHECK (decision IN ('approve', 'reject')),
    comment text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_project_memory_reviews_draft
    ON public.project_memory_reviews (draft_id, created_at DESC);

ALTER TABLE public.documents
    ADD COLUMN IF NOT EXISTS department_id text REFERENCES public.departments(id),
    ADD COLUMN IF NOT EXISTS memory_type text,
    ADD COLUMN IF NOT EXISTS memory_draft_id uuid REFERENCES public.project_memory_drafts(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS template_version text;

ALTER TABLE public.audit_logs DROP CONSTRAINT IF EXISTS audit_logs_action_check;
ALTER TABLE public.audit_logs ADD CONSTRAINT audit_logs_action_check CHECK (
    action = ANY (ARRAY[
        'upload',
        'search',
        'answer',
        'login',
        'logout',
        'delete_document',
        'add_member',
        'remove_member',
        'create_project',
        'workday_summary',
        'workday_enroll',
        'ai_chat_ingest',
        'ai_chat_list',
        'ai_monitor_device_register',
        'ai_monitor_status',
        'project_memory_repository_upsert',
        'project_memory_draft_create',
        'project_memory_review'
    ])
);

COMMIT;
