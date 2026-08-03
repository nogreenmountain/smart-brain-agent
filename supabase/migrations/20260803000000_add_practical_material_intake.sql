BEGIN;

CREATE TABLE IF NOT EXISTS public.project_material_intakes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    department_id text NOT NULL REFERENCES public.departments(id),
    status text NOT NULL DEFAULT 'preview_ready'
        CHECK (status IN (
            'preview_ready', 'processing', 'pending_review',
            'approved', 'rejected', 'failed'
        )),
    preview_summary text NOT NULL DEFAULT '',
    preview_model text,
    preview_used_fallback boolean NOT NULL DEFAULT false,
    created_by_user_id uuid,
    confirmed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_project_material_intakes_project_status
    ON public.project_material_intakes (project_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS public.project_material_intake_files (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    intake_id uuid NOT NULL REFERENCES public.project_material_intakes(id) ON DELETE CASCADE,
    filename text NOT NULL,
    format text NOT NULL,
    size_bytes bigint NOT NULL CHECK (size_bytes > 0),
    content_hash text NOT NULL,
    raw_content bytea NOT NULL,
    extracted_text text NOT NULL,
    recommendation text NOT NULL CHECK (
        recommendation IN ('keep', 'review', 'duplicate', 'sensitive', 'low_value')
    ),
    included boolean NOT NULL DEFAULT true,
    reason text NOT NULL DEFAULT '',
    issues jsonb NOT NULL DEFAULT '[]'::jsonb,
    document_id uuid REFERENCES public.documents(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (intake_id, filename)
);

CREATE INDEX IF NOT EXISTS idx_project_material_intake_files_hash
    ON public.project_material_intake_files (content_hash);

ALTER TABLE public.project_memory_drafts
    ADD COLUMN IF NOT EXISTS intake_id uuid
        REFERENCES public.project_material_intakes(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS curated_markdown_content text,
    ADD COLUMN IF NOT EXISTS skill_candidates jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS generation_model text,
    ADD COLUMN IF NOT EXISTS generation_used_fallback boolean NOT NULL DEFAULT false;

CREATE UNIQUE INDEX IF NOT EXISTS uq_project_memory_drafts_intake
    ON public.project_memory_drafts (intake_id)
    WHERE intake_id IS NOT NULL;

ALTER TABLE public.project_memory_draft_sources
    ADD COLUMN IF NOT EXISTS content_hash text;

ALTER TABLE public.project_material_documents
    ADD COLUMN IF NOT EXISTS content_hash text,
    ADD COLUMN IF NOT EXISTS original_file_id uuid
        REFERENCES public.project_material_intake_files(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_project_material_documents_hash
    ON public.project_material_documents (project_id, content_hash)
    WHERE content_hash IS NOT NULL;

COMMIT;
