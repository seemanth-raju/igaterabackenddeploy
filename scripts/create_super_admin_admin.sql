-- Create or reset the default super-admin user without dropping existing data.
-- Login:
--   username: admin
--   password: Admin@123

BEGIN;

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;

WITH existing_company AS (
    SELECT company_id
    FROM public.company
    ORDER BY created_at NULLS LAST, company_id::text
    LIMIT 1
),
created_company AS (
    INSERT INTO public.company (
        company_id,
        name,
        domain,
        is_active,
        created_at,
        updated_at
    )
    SELECT
        public.uuid_generate_v4(),
        'System Company',
        'system.local',
        true,
        CURRENT_TIMESTAMP,
        CURRENT_TIMESTAMP
    WHERE NOT EXISTS (SELECT 1 FROM existing_company)
    RETURNING company_id
),
target_company AS (
    SELECT company_id FROM existing_company
    UNION ALL
    SELECT company_id FROM created_company
    LIMIT 1
),
updated_admin AS (
    UPDATE public.app_user
    SET
        company_id = (SELECT company_id FROM target_company),
        role = 'super_admin',
        full_name = 'Super Admin',
        password_hash = '$2b$12$iuI8xvbvTj3DDaSsHoWv3OU1zUr5GuKPCvleSauRFq3e97QqOgV7e',
        is_active = true
    WHERE username = 'admin'
    RETURNING user_id
),
inserted_admin AS (
    INSERT INTO public.app_user (
        user_id,
        company_id,
        role,
        username,
        full_name,
        password_hash,
        is_active,
        created_at
    )
    SELECT
        public.uuid_generate_v4(),
        company_id,
        'super_admin',
        'admin',
        'Super Admin',
        '$2b$12$iuI8xvbvTj3DDaSsHoWv3OU1zUr5GuKPCvleSauRFq3e97QqOgV7e',
        true,
        CURRENT_TIMESTAMP
    FROM target_company
    WHERE NOT EXISTS (SELECT 1 FROM updated_admin)
    RETURNING user_id
),
touched_admin AS (
    SELECT user_id FROM updated_admin
    UNION ALL
    SELECT user_id FROM inserted_admin
)
UPDATE public.auth_token
SET revoked = true
WHERE user_id IN (SELECT user_id FROM touched_admin);

COMMIT;
