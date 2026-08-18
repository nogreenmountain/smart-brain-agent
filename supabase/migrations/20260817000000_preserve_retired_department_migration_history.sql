-- Completed/failed category migrations are audit history.  A category may later
-- be retired, so retain its display-name snapshot while releasing the FK.
BEGIN;

ALTER TABLE public.project_department_migrations
    ADD COLUMN IF NOT EXISTS source_department_name text,
    ADD COLUMN IF NOT EXISTS target_department_name text;

UPDATE public.project_department_migrations migration
SET source_department_name = COALESCE(source.name, migration.source_department_id),
    target_department_name = COALESCE(target.name, migration.target_department_id)
FROM public.departments source,
     public.departments target
WHERE source.id = migration.source_department_id
  AND target.id = migration.target_department_id
  AND (
      migration.source_department_name IS NULL
      OR migration.target_department_name IS NULL
  );

ALTER TABLE public.project_department_migrations
    ALTER COLUMN source_department_name SET NOT NULL,
    ALTER COLUMN target_department_name SET NOT NULL,
    ALTER COLUMN source_department_id DROP NOT NULL,
    ALTER COLUMN target_department_id DROP NOT NULL;

ALTER TABLE public.project_department_migrations
    DROP CONSTRAINT IF EXISTS project_department_migrations_source_department_id_fkey,
    DROP CONSTRAINT IF EXISTS project_department_migrations_target_department_id_fkey;

ALTER TABLE public.project_department_migrations
    ADD CONSTRAINT project_department_migrations_source_department_id_fkey
        FOREIGN KEY (source_department_id)
        REFERENCES public.departments(id) ON DELETE SET NULL,
    ADD CONSTRAINT project_department_migrations_target_department_id_fkey
        FOREIGN KEY (target_department_id)
        REFERENCES public.departments(id) ON DELETE SET NULL;

COMMIT;
