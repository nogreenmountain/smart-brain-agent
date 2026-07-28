BEGIN;

CREATE TABLE IF NOT EXISTS public.ai_monitor_devices (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL,
    user_id uuid,
    employee_id text NOT NULL,
    employee_name text NOT NULL,
    device_id text NOT NULL,
    device_name text,
    installer_version text,
    os text,
    components jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ai_monitor_devices_device_id_check CHECK (length(device_id) >= 3),
    CONSTRAINT ai_monitor_devices_components_check CHECK (jsonb_typeof(components) = 'object')
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_monitor_devices_identity
    ON public.ai_monitor_devices (project_id, employee_id, device_id);

CREATE INDEX IF NOT EXISTS idx_ai_monitor_devices_project_employee
    ON public.ai_monitor_devices (project_id, employee_id, last_seen_at DESC);

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
            'ai_chat_list',
            'ai_monitor_device_register',
            'ai_monitor_status'
        )
    );

COMMIT;
