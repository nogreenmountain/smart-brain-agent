CREATE EXTENSION IF NOT EXISTS pgcrypto;

BEGIN;

INSERT INTO public.departments (id, name, sort_order)
VALUES
    ('research', '研发', 1),
    ('marketing', '市场', 2),
    ('business', '业务', 3)
ON CONFLICT (id) DO UPDATE
SET name = EXCLUDED.name,
    sort_order = EXCLUDED.sort_order;

INSERT INTO public.orgs (id, name, prem_status)
VALUES (
    'd93e743e-f8bb-48cb-ae05-a74c6ae26620',
    'Default Organization',
    'pro'
)
ON CONFLICT (id) DO UPDATE
SET name = EXCLUDED.name,
    prem_status = EXCLUDED.prem_status;

INSERT INTO public.projects (
    id,
    org_id,
    api_key,
    name,
    environment,
    department_id,
    completed_at
)
VALUES (
    'f9505558-d67d-462f-b77e-6b9550458a2b',
    'd93e743e-f8bb-48cb-ae05-a74c6ae26620',
    'f9505558-d67d-462f-b77e-6b9550458a2c',
    '默认研发项目',
    'development',
    'research',
    NULL
)
ON CONFLICT (id) DO UPDATE
SET name = EXCLUDED.name,
    department_id = EXCLUDED.department_id,
    completed_at = EXCLUDED.completed_at;

CREATE TEMP TABLE smartbrain_seed_users (
    user_id uuid PRIMARY KEY,
    email text NOT NULL,
    password text NOT NULL,
    full_name text NOT NULL,
    org_role org_roles NOT NULL,
    project_role org_roles NOT NULL
) ON COMMIT DROP;

INSERT INTO smartbrain_seed_users
VALUES
    ('15bac7bf-d5c9-4968-a534-7ea2b016584c', 'hanshangbo@local.dev', '12345678', 'hanshangbo', 'owner', 'owner'),
    ('10000000-0000-4000-8000-000000000001', 'test1@local.dev', '123456', 'test1', 'business_user', 'developer'),
    ('10000000-0000-4000-8000-000000000002', 'test2@local.dev', '123456', 'test2', 'business_user', 'developer'),
    ('10000000-0000-4000-8000-000000000003', 'test3@local.dev', '123456', 'test3', 'business_user', 'developer'),
    ('10000000-0000-4000-8000-000000000004', 'test4@local.dev', '123456', 'test4', 'business_user', 'developer'),
    ('10000000-0000-4000-8000-000000000005', 'test5@local.dev', '123456', 'test5', 'business_user', 'developer'),
    ('10000000-0000-4000-8000-000000000006', 'test6@local.dev', '123456', 'test6', 'business_user', 'developer'),
    ('10000000-0000-4000-8000-000000000007', 'test7@local.dev', '123456', 'test7', 'business_user', 'developer'),
    ('10000000-0000-4000-8000-000000000008', 'test8@local.dev', '123456', 'test8', 'business_user', 'developer'),
    ('10000000-0000-4000-8000-000000000009', 'test9@local.dev', '123456', 'test9', 'business_user', 'developer'),
    ('10000000-0000-4000-8000-000000000010', 'test10@local.dev', '123456', 'test10', 'business_user', 'developer'),
    ('10000000-0000-4000-8000-000000000011', 'test11@local.dev', '123456', 'test11', 'business_user', 'developer'),
    ('10000000-0000-4000-8000-000000000012', 'test12@local.dev', '123456', 'test12', 'business_user', 'developer');

DELETE FROM auth.users au
USING smartbrain_seed_users su
WHERE lower(au.email) = lower(su.email)
  AND au.id <> su.user_id;

INSERT INTO auth.users (
    instance_id,
    id,
    aud,
    role,
    email,
    encrypted_password,
    email_confirmed_at,
    confirmation_token,
    recovery_token,
    email_change_token_new,
    email_change,
    email_change_token_current,
    email_change_confirm_status,
    reauthentication_token,
    raw_app_meta_data,
    raw_user_meta_data,
    is_super_admin,
    created_at,
    updated_at,
    is_sso_user,
    is_anonymous
)
SELECT
    '00000000-0000-0000-0000-000000000000',
    user_id,
    'authenticated',
    'authenticated',
    email,
    crypt(password, gen_salt('bf')),
    now(),
    '',
    '',
    '',
    '',
    '',
    0,
    '',
    '{"provider":"email","providers":["email"]}'::jsonb,
    jsonb_build_object('full_name', full_name),
    NULL,
    now(),
    now(),
    FALSE,
    FALSE
FROM smartbrain_seed_users
ON CONFLICT (id) DO UPDATE
SET email = EXCLUDED.email,
    encrypted_password = EXCLUDED.encrypted_password,
    raw_user_meta_data = EXCLUDED.raw_user_meta_data,
    updated_at = now();

INSERT INTO auth.identities (
    provider_id,
    user_id,
    identity_data,
    provider,
    last_sign_in_at,
    created_at,
    updated_at
)
SELECT
    user_id::text,
    user_id,
    jsonb_build_object(
        'sub', user_id::text,
        'email', email,
        'email_verified', true,
        'phone_verified', false
    ),
    'email',
    now(),
    now(),
    now()
FROM smartbrain_seed_users
ON CONFLICT (provider_id, provider) DO UPDATE
SET identity_data = EXCLUDED.identity_data,
    updated_at = now();

INSERT INTO public.users (id, email, full_name)
SELECT user_id, email, full_name
FROM smartbrain_seed_users
ON CONFLICT (id) DO UPDATE
SET email = EXCLUDED.email,
    full_name = EXCLUDED.full_name;

INSERT INTO public.user_orgs (user_id, org_id, user_email, role, is_paid)
SELECT
    user_id,
    'd93e743e-f8bb-48cb-ae05-a74c6ae26620',
    email,
    org_role,
    true
FROM smartbrain_seed_users
ON CONFLICT (user_id, org_id) DO UPDATE
SET user_email = EXCLUDED.user_email,
    role = EXCLUDED.role,
    is_paid = EXCLUDED.is_paid;

INSERT INTO public.project_members (project_id, user_id, role)
SELECT
    'f9505558-d67d-462f-b77e-6b9550458a2b',
    user_id,
    project_role
FROM smartbrain_seed_users
ON CONFLICT (project_id, user_id) DO UPDATE
SET role = EXCLUDED.role;

COMMIT;
