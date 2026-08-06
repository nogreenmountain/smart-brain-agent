BEGIN;

ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS ai_detail_visible_to_admin boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN public.users.ai_detail_visible_to_admin IS
    'When true, organization administrators may read this member''s detailed AI conversation records. Daily work logs remain administrator-visible regardless.';

COMMIT;
