BEGIN;

ALTER TABLE public.meeting_summaries
    ADD COLUMN IF NOT EXISTS participant_user_ids uuid[] NOT NULL DEFAULT ARRAY[]::uuid[];

CREATE TABLE IF NOT EXISTS public.meeting_summary_files (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_summary_id uuid NOT NULL UNIQUE
        REFERENCES public.meeting_summaries(id) ON DELETE CASCADE,
    filename text NOT NULL CHECK (char_length(filename) BETWEEN 1 AND 255),
    format text NOT NULL CHECK (char_length(format) BETWEEN 1 AND 32),
    mime_type text,
    size_bytes bigint NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 20971520),
    content_hash text NOT NULL CHECK (char_length(content_hash) = 64),
    raw_content bytea NOT NULL,
    extracted_text text NOT NULL CHECK (char_length(extracted_text) > 0),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_meeting_summary_files_content_hash
    ON public.meeting_summary_files (content_hash);

COMMIT;
