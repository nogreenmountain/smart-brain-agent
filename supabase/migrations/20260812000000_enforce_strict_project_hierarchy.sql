BEGIN;

ALTER TABLE public.departments
DROP CONSTRAINT IF EXISTS departments_sort_order_key;

CREATE INDEX IF NOT EXISTS departments_parent_sort_order_idx
ON public.departments (parent_id, sort_order, id);

-- Keep stable IDs for the two long-lived roots, and use deterministic IDs for
-- every other existing or dynamically-created first-level category.
INSERT INTO public.departments (id, name, sort_order, parent_id, allows_projects)
VALUES
    ('research-direct', '直属分级', 11, 'research', true),
    ('team-management-direct', '直属分级', 21, 'team-management', true)
ON CONFLICT (id) DO UPDATE
SET name = EXCLUDED.name,
    sort_order = EXCLUDED.sort_order,
    parent_id = EXCLUDED.parent_id,
    allows_projects = EXCLUDED.allows_projects;

INSERT INTO public.departments (id, name, sort_order, parent_id, allows_projects)
SELECT
    'direct-' || substr(md5(root.id), 1, 32),
    '直属分级',
    COALESCE((
        SELECT max(sibling.sort_order) + 1
        FROM public.departments sibling
        WHERE sibling.parent_id = root.id
    ), 1),
    root.id,
    true
FROM public.departments root
WHERE root.parent_id IS NULL
  AND root.id NOT IN ('research', 'team-management')
  AND NOT EXISTS (
      SELECT 1
      FROM public.departments child
      WHERE child.parent_id = root.id
        AND lower(btrim(child.name)) IN ('直属分级', '直属项目')
  )
ON CONFLICT (id) DO UPDATE
SET name = EXCLUDED.name,
    parent_id = EXCLUDED.parent_id,
    allows_projects = true;

WITH root_direct AS (
    SELECT root.id AS root_id,
           COALESCE(
               CASE root.id
                   WHEN 'research' THEN 'research-direct'
                   WHEN 'team-management' THEN 'team-management-direct'
               END,
               'direct-' || substr(md5(root.id), 1, 32)
           ) AS direct_id
    FROM public.departments root
    WHERE root.parent_id IS NULL
)
UPDATE public.projects project
SET department_id = root_direct.direct_id
FROM root_direct
WHERE project.department_id = root_direct.root_id;

WITH root_direct AS (
    SELECT root.id AS root_id,
           COALESCE(
               CASE root.id
                   WHEN 'research' THEN 'research-direct'
                   WHEN 'team-management' THEN 'team-management-direct'
               END,
               'direct-' || substr(md5(root.id), 1, 32)
           ) AS direct_id
    FROM public.departments root
    WHERE root.parent_id IS NULL
)
UPDATE public.project_creation_requests request_row
SET department_id = root_direct.direct_id,
    updated_at = now()
FROM root_direct
WHERE request_row.department_id = root_direct.root_id;

WITH root_direct AS (
    SELECT root.id AS root_id,
           COALESCE(
               CASE root.id
                   WHEN 'research' THEN 'research-direct'
                   WHEN 'team-management' THEN 'team-management-direct'
               END,
               'direct-' || substr(md5(root.id), 1, 32)
           ) AS direct_id
    FROM public.departments root
    WHERE root.parent_id IS NULL
)
UPDATE public.project_material_intakes intake
SET department_id = root_direct.direct_id,
    updated_at = now()
FROM root_direct
WHERE intake.department_id = root_direct.root_id;

WITH root_direct AS (
    SELECT root.id AS root_id,
           COALESCE(
               CASE root.id
                   WHEN 'research' THEN 'research-direct'
                   WHEN 'team-management' THEN 'team-management-direct'
               END,
               'direct-' || substr(md5(root.id), 1, 32)
           ) AS direct_id
    FROM public.departments root
    WHERE root.parent_id IS NULL
)
UPDATE public.project_memory_drafts draft
SET department_id = root_direct.direct_id,
    updated_at = now()
FROM root_direct
WHERE draft.department_id = root_direct.root_id;

UPDATE public.documents document
SET department_id = project.department_id
FROM public.projects project
WHERE project.id = document.project_id
  AND document.department_id IS DISTINCT FROM project.department_id;

UPDATE public.departments
SET allows_projects = (parent_id IS NOT NULL);

ALTER TABLE public.projects
ALTER COLUMN department_id SET DEFAULT 'research-direct';

ALTER TABLE public.project_memory_drafts
ALTER COLUMN department_id SET DEFAULT 'research-direct';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.projects project
        JOIN public.departments department ON department.id = project.department_id
        WHERE department.parent_id IS NULL OR department.allows_projects = false
    ) THEN
        RAISE EXCEPTION 'all projects must belong to a second-level project category';
    END IF;
END $$;

COMMIT;
