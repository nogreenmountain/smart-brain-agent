BEGIN;

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
            'workday_summary'
        )
    );

COMMIT;
