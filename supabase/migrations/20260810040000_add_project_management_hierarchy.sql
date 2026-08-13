BEGIN;

ALTER TABLE public.departments
ADD COLUMN IF NOT EXISTS parent_id text NULL;

ALTER TABLE public.departments
ADD COLUMN IF NOT EXISTS allows_projects boolean NOT NULL DEFAULT true;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.departments'::regclass
          AND conname = 'departments_parent_id_fkey'
    ) THEN
        ALTER TABLE public.departments
        ADD CONSTRAINT departments_parent_id_fkey
        FOREIGN KEY (parent_id) REFERENCES public.departments(id);
    END IF;
END $$;

ALTER TABLE public.departments
DROP CONSTRAINT IF EXISTS departments_name_key;

DROP INDEX IF EXISTS public.departments_root_name_unique_idx;
DROP INDEX IF EXISTS public.departments_child_name_unique_idx;

CREATE UNIQUE INDEX departments_root_name_unique_idx
ON public.departments (lower(btrim(name)))
WHERE parent_id IS NULL;

CREATE UNIQUE INDEX departments_child_name_unique_idx
ON public.departments (parent_id, lower(btrim(name)))
WHERE parent_id IS NOT NULL;

UPDATE public.departments
SET name = '研发支撑',
    parent_id = NULL,
    allows_projects = true,
    sort_order = 10
WHERE id = 'research';

UPDATE public.departments
SET name = '市场',
    parent_id = NULL,
    allows_projects = true,
    sort_order = 31
WHERE id = 'marketing';

UPDATE public.departments
SET name = '业务',
    parent_id = NULL,
    allows_projects = true,
    sort_order = 32
WHERE id = 'business';

INSERT INTO public.departments (id, name, sort_order, parent_id, allows_projects)
VALUES
    ('team-management', '团队管理', 20, NULL, true),
    ('industry', '产业侧', 30, NULL, false),
    ('education', '教学侧', 40, NULL, false),
    ('science', '科研侧', 50, NULL, false),
    ('education-market', '市场', 41, 'education', true),
    ('education-business', '业务', 42, 'education', true),
    ('science-market', '市场', 51, 'science', true),
    ('science-business', '业务', 52, 'science', true)
ON CONFLICT (id) DO UPDATE
SET name = excluded.name,
    sort_order = excluded.sort_order,
    parent_id = excluded.parent_id,
    allows_projects = excluded.allows_projects;

UPDATE public.departments
SET parent_id = 'industry'
WHERE id IN ('marketing', 'business');

ALTER TABLE public.departments
DROP CONSTRAINT IF EXISTS departments_parent_not_self_check;

ALTER TABLE public.departments
ADD CONSTRAINT departments_parent_not_self_check
CHECK (parent_id IS NULL OR parent_id <> id);

COMMIT;
