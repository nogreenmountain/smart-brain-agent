BEGIN;

ALTER TABLE public.project_material_intakes
    DROP CONSTRAINT IF EXISTS project_material_intakes_status_check;

ALTER TABLE public.project_material_intakes
    ADD CONSTRAINT project_material_intakes_status_check
    CHECK (status IN (
        'uploading', 'preview_ready', 'processing', 'pending_review',
        'approved', 'rejected', 'failed'
    ));

ALTER TABLE public.project_material_intakes
    ADD COLUMN IF NOT EXISTS client_upload_id uuid,
    ADD COLUMN IF NOT EXISTS upload_completed_at timestamptz;

CREATE UNIQUE INDEX IF NOT EXISTS uq_project_material_intakes_client_upload
    ON public.project_material_intakes (project_id, created_by_user_id, client_upload_id)
    WHERE client_upload_id IS NOT NULL;

ALTER TABLE public.project_material_intake_files
    ADD COLUMN IF NOT EXISTS storage_key text,
    ADD COLUMN IF NOT EXISTS uploaded_bytes bigint NOT NULL DEFAULT 0
        CHECK (uploaded_bytes >= 0 AND uploaded_bytes <= size_bytes);

UPDATE public.project_material_intake_files
SET uploaded_bytes = size_bytes
WHERE uploaded_bytes = 0
  AND octet_length(raw_content) = size_bytes;

CREATE UNIQUE INDEX IF NOT EXISTS uq_project_material_intake_files_storage_key
    ON public.project_material_intake_files (storage_key)
    WHERE storage_key IS NOT NULL;

-- Project roles reuse the existing shared enum so organization login and
-- membership semantics remain untouched. Project membership now exposes only
-- owner (总负责人), admin (项目负责人), and developer (项目成员).
UPDATE public.project_members
SET role = 'developer'::public.org_roles
WHERE role = 'business_user'::public.org_roles;

COMMIT;
