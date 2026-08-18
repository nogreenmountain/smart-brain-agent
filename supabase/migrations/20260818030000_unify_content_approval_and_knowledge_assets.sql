BEGIN;

CREATE TABLE IF NOT EXISTS public.project_memory_submissions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    submission_type text NOT NULL
        CHECK (submission_type IN ('meeting_summary', 'project_repository')),
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    filename text,
    format text,
    mime_type text,
    size_bytes bigint CHECK (size_bytes IS NULL OR size_bytes > 0),
    content_hash text,
    raw_content bytea,
    status text NOT NULL DEFAULT 'pending_review'
        CHECK (status IN ('pending_review', 'approved', 'rejected')),
    approved_resource_id uuid,
    created_by_user_id uuid,
    reviewed_by_user_id uuid,
    review_comment text,
    reviewed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        (submission_type = 'meeting_summary'
         AND filename IS NOT NULL AND format IS NOT NULL
         AND size_bytes IS NOT NULL AND content_hash IS NOT NULL
         AND (status <> 'pending_review' OR raw_content IS NOT NULL))
        OR
        (submission_type = 'project_repository'
         AND filename IS NULL AND format IS NULL
         AND size_bytes IS NULL AND content_hash IS NULL
         AND raw_content IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_project_memory_submissions_project_status
    ON public.project_memory_submissions (project_id, status, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_project_memory_pending_repository_submission
    ON public.project_memory_submissions (project_id)
    WHERE submission_type = 'project_repository'
      AND status = 'pending_review';

ALTER TABLE public.project_memory_drafts
    ADD COLUMN IF NOT EXISTS submission_id uuid
        REFERENCES public.project_memory_submissions(id) ON DELETE SET NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_project_memory_drafts_submission
    ON public.project_memory_drafts (submission_id)
    WHERE submission_id IS NOT NULL;

ALTER TABLE public.meeting_summaries
    ADD COLUMN IF NOT EXISTS approval_draft_id uuid
        REFERENCES public.project_memory_drafts(id) ON DELETE SET NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_meeting_summaries_approval_draft
    ON public.meeting_summaries (approval_draft_id)
    WHERE approval_draft_id IS NOT NULL;

COMMIT;
