BEGIN;

CREATE TABLE IF NOT EXISTS public.ai_daily_work_logs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id text NOT NULL,
    employee_name text NOT NULL,
    work_date date NOT NULL,
    timezone text NOT NULL DEFAULT 'Asia/Shanghai',
    status text NOT NULL,
    report_markdown text,
    work_items jsonb NOT NULL DEFAULT '[]'::jsonb,
    source_session_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    source_count integer NOT NULL DEFAULT 0,
    model text NOT NULL,
    generated_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ai_daily_work_logs_employee_date_key UNIQUE (employee_id, work_date),
    CONSTRAINT ai_daily_work_logs_status_check CHECK (status IN ('ready', 'empty')),
    CONSTRAINT ai_daily_work_logs_timezone_check CHECK (timezone = 'Asia/Shanghai'),
    CONSTRAINT ai_daily_work_logs_source_count_check CHECK (source_count >= 0),
    CONSTRAINT ai_daily_work_logs_report_check CHECK (
        (status = 'ready' AND report_markdown IS NOT NULL AND jsonb_array_length(work_items) > 0)
        OR (status = 'empty' AND report_markdown IS NULL AND jsonb_array_length(work_items) = 0)
    )
);

CREATE INDEX IF NOT EXISTS idx_ai_daily_work_logs_employee_date
    ON public.ai_daily_work_logs (employee_id, work_date DESC);

COMMIT;
