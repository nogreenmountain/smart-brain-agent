BEGIN;

CREATE TABLE IF NOT EXISTS public.cc_switch_attribution_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    target_user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    target_employee_id text NOT NULL,
    target_employee_name text NOT NULL,
    device_id text,
    stop_mode text NOT NULL CHECK (stop_mode IN ('default_19', 'custom', 'manual_only')),
    stop_reason text CHECK (
        stop_reason IS NULL OR stop_reason IN (
            'manual', 'scheduled', 'replaced_by_next_user',
            'admin_forced', 'safety_timeout'
        )
    ),
    status text NOT NULL DEFAULT 'starting' CHECK (
        status IN (
            'starting', 'active', 'finalizing', 'pending_sync',
            'finalized', 'cancelled', 'expired'
        )
    ),
    activation_token_hash text NOT NULL,
    activation_expires_at timestamptz NOT NULL,
    requested_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    scheduled_stop_at timestamptz NOT NULL,
    actual_stop_at timestamptz,
    start_watermark text,
    request_count bigint NOT NULL DEFAULT 0 CHECK (request_count >= 0),
    input_tokens bigint NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens bigint NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    cache_read_tokens bigint NOT NULL DEFAULT 0 CHECK (cache_read_tokens >= 0),
    cache_creation_tokens bigint NOT NULL DEFAULT 0 CHECK (cache_creation_tokens >= 0),
    total_tokens bigint NOT NULL DEFAULT 0 CHECK (total_tokens >= 0),
    total_cost_usd double precision NOT NULL DEFAULT 0 CHECK (total_cost_usd >= 0),
    finalized_at timestamptz,
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_cc_switch_attribution_active_device
    ON public.cc_switch_attribution_sessions (device_id)
    WHERE device_id IS NOT NULL
      AND status IN ('active', 'finalizing', 'pending_sync');

CREATE INDEX IF NOT EXISTS idx_cc_switch_attribution_target
    ON public.cc_switch_attribution_sessions (
        target_user_id, requested_at DESC
    );

CREATE INDEX IF NOT EXISTS idx_cc_switch_attribution_schedule
    ON public.cc_switch_attribution_sessions (scheduled_stop_at)
    WHERE status = 'active';

CREATE TABLE IF NOT EXISTS public.cc_switch_attributed_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id uuid NOT NULL
        REFERENCES public.cc_switch_attribution_sessions(id) ON DELETE CASCADE,
    project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    target_user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    target_employee_id text NOT NULL,
    target_employee_name text NOT NULL,
    device_id text NOT NULL,
    request_id text NOT NULL,
    requested_at timestamptz NOT NULL,
    usage_date date NOT NULL,
    app_type text NOT NULL,
    provider_id text NOT NULL,
    model text NOT NULL,
    request_model text NOT NULL DEFAULT '',
    pricing_model text NOT NULL DEFAULT '',
    status_code integer NOT NULL DEFAULT 0,
    input_tokens bigint NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens bigint NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    cache_read_tokens bigint NOT NULL DEFAULT 0 CHECK (cache_read_tokens >= 0),
    cache_creation_tokens bigint NOT NULL DEFAULT 0 CHECK (cache_creation_tokens >= 0),
    total_tokens bigint NOT NULL DEFAULT 0 CHECK (total_tokens >= 0),
    total_cost_usd double precision NOT NULL DEFAULT 0 CHECK (total_cost_usd >= 0),
    input_token_semantics integer NOT NULL DEFAULT 0 CHECK (input_token_semantics >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT cc_switch_attributed_request_identity UNIQUE (device_id, request_id)
);

CREATE INDEX IF NOT EXISTS idx_cc_switch_attributed_member_date
    ON public.cc_switch_attributed_requests (target_employee_id, usage_date);

CREATE INDEX IF NOT EXISTS idx_cc_switch_attributed_session
    ON public.cc_switch_attributed_requests (session_id, requested_at);

ALTER TABLE public.audit_logs
    DROP CONSTRAINT IF EXISTS audit_logs_action_check;

ALTER TABLE public.audit_logs
ADD CONSTRAINT audit_logs_action_check CHECK (action = ANY (ARRAY[
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
    'update_profile', 'change_password', 'create_department',
    'update_department', 'delete_department', 'rename_member_username',
    'request_project_creation', 'review_project_creation',
    'create_team_member', 'deactivate_team_member', 'reactivate_team_member',
    'rename_team_member_username', 'reset_team_member_password',
    'project_department_migration', 'ai_shared_session_start',
    'ai_shared_session_schedule', 'ai_shared_session_stop',
    'ai_shared_session_finalize'
]));

COMMIT;
