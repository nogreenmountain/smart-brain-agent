BEGIN;

CREATE TABLE IF NOT EXISTS public.ai_chat_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL,
    user_id uuid,
    employee_id text NOT NULL,
    employee_name text NOT NULL,
    source text NOT NULL,
    external_conversation_id text,
    title text,
    task_id text NOT NULL DEFAULT 'unassigned',
    task_title text,
    model text,
    status text NOT NULL DEFAULT 'ok',
    started_at timestamptz NOT NULL DEFAULT now(),
    ended_at timestamptz,
    duration_ms bigint,
    prompt_tokens integer NOT NULL DEFAULT 0,
    completion_tokens integer NOT NULL DEFAULT 0,
    total_tokens integer NOT NULL DEFAULT 0,
    cost numeric(18, 9) NOT NULL DEFAULT 0,
    error_count integer NOT NULL DEFAULT 0,
    trace_id text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ai_chat_sessions_source_check CHECK (
        source IN (
            'cc_switch',
            'chatgpt_web',
            'chatgpt_desktop',
            'openai_compliance',
            'smartbrain'
        )
    ),
    CONSTRAINT ai_chat_sessions_status_check CHECK (
        status IN ('ok', 'error', 'partial')
    ),
    CONSTRAINT ai_chat_sessions_duration_check CHECK (
        duration_ms IS NULL OR duration_ms >= 0
    ),
    CONSTRAINT ai_chat_sessions_token_check CHECK (
        prompt_tokens >= 0
        AND completion_tokens >= 0
        AND total_tokens >= 0
    ),
    CONSTRAINT ai_chat_sessions_cost_check CHECK (cost >= 0),
    CONSTRAINT ai_chat_sessions_error_count_check CHECK (error_count >= 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_chat_session_external
    ON public.ai_chat_sessions (
        project_id,
        source,
        employee_id,
        external_conversation_id
    )
    WHERE external_conversation_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ai_chat_sessions_project_started
    ON public.ai_chat_sessions (project_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_ai_chat_sessions_employee_started
    ON public.ai_chat_sessions (employee_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_ai_chat_sessions_source_started
    ON public.ai_chat_sessions (source, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_ai_chat_sessions_task
    ON public.ai_chat_sessions (project_id, task_id);

CREATE TABLE IF NOT EXISTS public.ai_chat_messages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id uuid NOT NULL,
    sequence_index integer NOT NULL,
    role text NOT NULL,
    external_message_id text,
    content text NOT NULL,
    token_count integer,
    message_created_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ai_chat_messages_role_check CHECK (
        role IN ('user', 'assistant', 'system', 'tool')
    ),
    CONSTRAINT ai_chat_messages_sequence_check CHECK (sequence_index >= 0),
    CONSTRAINT ai_chat_messages_token_check CHECK (
        token_count IS NULL OR token_count >= 0
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_chat_message_sequence
    ON public.ai_chat_messages (session_id, sequence_index);

CREATE INDEX IF NOT EXISTS idx_ai_chat_messages_session
    ON public.ai_chat_messages (session_id, sequence_index);

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
            'workday_summary',
            'workday_enroll',
            'ai_chat_ingest',
            'ai_chat_list'
        )
    );

COMMIT;
