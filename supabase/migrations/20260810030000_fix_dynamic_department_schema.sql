BEGIN;

ALTER TABLE public.departments
ADD COLUMN IF NOT EXISTS created_by_user_id uuid NULL
REFERENCES public.users(id) ON DELETE SET NULL;

ALTER TABLE public.departments
ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();

ALTER TABLE public.departments
DROP CONSTRAINT IF EXISTS departments_id_check;

ALTER TABLE public.departments
ADD CONSTRAINT departments_id_check
CHECK (id ~ '^[a-z][a-z0-9_-]{1,39}$');

ALTER TABLE public.departments
DROP CONSTRAINT IF EXISTS departments_name_check;

ALTER TABLE public.departments
ADD CONSTRAINT departments_name_check
CHECK (char_length(btrim(name)) BETWEEN 1 AND 80);

COMMIT;
