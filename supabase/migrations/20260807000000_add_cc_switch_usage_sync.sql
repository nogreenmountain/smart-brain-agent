BEGIN;

CREATE TABLE IF NOT EXISTS public.cc_switch_usage_daily (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    employee_id text NOT NULL,
    employee_name text NOT NULL,
    device_id text NOT NULL,
    usage_date date NOT NULL,
    app_type text NOT NULL,
    provider_id text NOT NULL,
    model text NOT NULL,
    request_model text NOT NULL DEFAULT '',
    pricing_model text NOT NULL DEFAULT '',
    request_count bigint NOT NULL DEFAULT 0 CHECK (request_count >= 0),
    success_count bigint NOT NULL DEFAULT 0 CHECK (success_count >= 0),
    input_tokens bigint NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens bigint NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    cache_read_tokens bigint NOT NULL DEFAULT 0 CHECK (cache_read_tokens >= 0),
    cache_creation_tokens bigint NOT NULL DEFAULT 0 CHECK (cache_creation_tokens >= 0),
    total_tokens bigint NOT NULL DEFAULT 0 CHECK (total_tokens >= 0),
    total_cost_usd double precision NOT NULL DEFAULT 0 CHECK (total_cost_usd >= 0),
    input_token_semantics integer NOT NULL DEFAULT 0 CHECK (input_token_semantics >= 0),
    source_table text NOT NULL CHECK (source_table IN ('usage_daily_rollups', 'proxy_request_logs')),
    synced_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT cc_switch_usage_daily_identity_key UNIQUE (
        user_id, device_id, usage_date, app_type,
        provider_id, model, request_model, pricing_model
    )
);

CREATE INDEX IF NOT EXISTS cc_switch_usage_daily_employee_date_idx
    ON public.cc_switch_usage_daily (employee_id, usage_date);

CREATE INDEX IF NOT EXISTS cc_switch_usage_daily_user_date_idx
    ON public.cc_switch_usage_daily (user_id, usage_date);

CREATE TABLE IF NOT EXISTS public.cc_switch_usage_sync_status (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    employee_id text NOT NULL,
    employee_name text NOT NULL,
    device_id text NOT NULL,
    trigger text NOT NULL CHECK (trigger IN ('automatic', 'manual')),
    request_id uuid,
    range_start date NOT NULL,
    range_end date NOT NULL,
    status text NOT NULL CHECK (status IN ('ok', 'not_running', 'error')),
    cc_switch_running boolean NOT NULL,
    source_table text CHECK (
        source_table IS NULL OR
        source_table IN ('usage_daily_rollups', 'proxy_request_logs')
    ),
    row_count integer NOT NULL DEFAULT 0 CHECK (row_count >= 0),
    request_count bigint NOT NULL DEFAULT 0 CHECK (request_count >= 0),
    total_tokens bigint NOT NULL DEFAULT 0 CHECK (total_tokens >= 0),
    attempted_at timestamptz NOT NULL,
    last_success_at timestamptz,
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT cc_switch_usage_sync_status_device_key UNIQUE (user_id, device_id)
);

CREATE INDEX IF NOT EXISTS cc_switch_usage_sync_status_request_idx
    ON public.cc_switch_usage_sync_status (user_id, request_id)
    WHERE request_id IS NOT NULL;

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
            'ai_usage_view', 'ai_usage_report', 'ai_usage_sync',
            'project_wiki_compile', 'project_wiki_view', 'project_wiki_review',
            'member_wiki_view', 'meeting_summary_view', 'meeting_summary_create',
            'update_profile', 'change_password'
        )
    );

COMMIT;
