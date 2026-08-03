BEGIN;

ALTER TABLE public.project_wiki_compile_runs
    DROP CONSTRAINT IF EXISTS project_wiki_compile_runs_trigger_type_check;
ALTER TABLE public.project_wiki_compile_runs
    ADD CONSTRAINT project_wiki_compile_runs_trigger_type_check
    CHECK (trigger_type IN ('manual', 'scheduled', 'mcp_proposal'));

ALTER TABLE public.project_wiki_pages
    ADD COLUMN IF NOT EXISTS memory_kind text NOT NULL DEFAULT 'reference',
    ADD COLUMN IF NOT EXISTS tags text[] NOT NULL DEFAULT ARRAY[]::text[],
    ADD COLUMN IF NOT EXISTS verification_status text NOT NULL DEFAULT 'generated',
    ADD COLUMN IF NOT EXISTS valid_from date,
    ADD COLUMN IF NOT EXISTS valid_until date,
    ADD COLUMN IF NOT EXISTS verified_by_user_id uuid,
    ADD COLUMN IF NOT EXISTS verified_at timestamptz;

ALTER TABLE public.project_wiki_pages
    DROP CONSTRAINT IF EXISTS project_wiki_pages_memory_kind_check;
ALTER TABLE public.project_wiki_pages
    ADD CONSTRAINT project_wiki_pages_memory_kind_check CHECK (
        memory_kind IN (
            'workflow_template', 'failure_case', 'success_case', 'strategy',
            'retrospective', 'decision_record', 'checklist', 'background',
            'timeline_event', 'reference'
        )
    );
ALTER TABLE public.project_wiki_pages
    DROP CONSTRAINT IF EXISTS project_wiki_pages_verification_status_check;
ALTER TABLE public.project_wiki_pages
    ADD CONSTRAINT project_wiki_pages_verification_status_check
    CHECK (verification_status IN ('generated', 'verified', 'stale'));

UPDATE public.project_wiki_pages
SET memory_kind = CASE page_type
    WHEN 'procedure' THEN 'workflow_template'
    WHEN 'troubleshooting' THEN 'failure_case'
    WHEN 'lesson' THEN 'retrospective'
    WHEN 'decision' THEN 'decision_record'
    WHEN 'policy' THEN 'strategy'
    WHEN 'architecture' THEN 'background'
    ELSE 'reference'
END
WHERE memory_kind = 'reference';

UPDATE public.project_wiki_pages p
SET verification_status = 'verified',
    verified_by_user_id = c.reviewed_by_user_id,
    verified_at = c.reviewed_at
FROM public.project_wiki_changes c
WHERE c.page_id = p.id AND c.status = 'applied'
  AND c.reviewed_by_user_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_project_wiki_pages_kind_updated
    ON public.project_wiki_pages (project_id, memory_kind, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_project_wiki_pages_tags
    ON public.project_wiki_pages USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_project_wiki_pages_content_search
    ON public.project_wiki_pages USING GIN (
        to_tsvector('simple',
            coalesce(title, '') || ' ' || coalesce(summary, '') || ' ' ||
            coalesce(markdown_content, '')
        )
    );

ALTER TABLE public.project_wiki_links
    ADD COLUMN IF NOT EXISTS to_page_id uuid REFERENCES public.project_wiki_pages(id) ON DELETE CASCADE;
UPDATE public.project_wiki_links l
SET to_page_id = target.id
FROM public.project_wiki_pages source
JOIN public.project_wiki_pages target ON target.project_id = source.project_id
WHERE source.id = l.from_page_id
  AND lower(target.title) = lower(l.to_title)
  AND l.to_page_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_project_wiki_links_to
    ON public.project_wiki_links (to_page_id);

ALTER TABLE public.project_wiki_changes
    ADD COLUMN IF NOT EXISTS memory_kind text NOT NULL DEFAULT 'reference',
    ADD COLUMN IF NOT EXISTS tags text[] NOT NULL DEFAULT ARRAY[]::text[],
    ADD COLUMN IF NOT EXISTS valid_from date,
    ADD COLUMN IF NOT EXISTS valid_until date;

UPDATE public.project_wiki_changes
SET memory_kind = CASE page_type
    WHEN 'procedure' THEN 'workflow_template'
    WHEN 'troubleshooting' THEN 'failure_case'
    WHEN 'lesson' THEN 'retrospective'
    WHEN 'decision' THEN 'decision_record'
    WHEN 'policy' THEN 'strategy'
    WHEN 'architecture' THEN 'background'
    ELSE 'reference'
END
WHERE memory_kind = 'reference';

CREATE TABLE IF NOT EXISTS public.wiki_mcp_tokens (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    name text NOT NULL,
    token_hash text NOT NULL UNIQUE,
    scopes text[] NOT NULL DEFAULT ARRAY['wiki:read']::text[],
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz,
    last_used_at timestamptz,
    revoked_at timestamptz,
    CHECK (char_length(name) BETWEEN 1 AND 100),
    CHECK (scopes <@ ARRAY['wiki:read', 'wiki:propose']::text[])
);
CREATE INDEX IF NOT EXISTS idx_wiki_mcp_tokens_user_created
    ON public.wiki_mcp_tokens (user_id, created_at DESC);

COMMIT;
