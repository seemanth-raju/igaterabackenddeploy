ALTER TABLE public.company
    ADD COLUMN IF NOT EXISTS max_users integer,
    ADD COLUMN IF NOT EXISTS max_devices integer;

ALTER TABLE public.company
    DROP CONSTRAINT IF EXISTS company_max_users_nonnegative;

ALTER TABLE public.company
    DROP CONSTRAINT IF EXISTS company_max_devices_nonnegative;

ALTER TABLE public.company
    ADD CONSTRAINT company_max_users_nonnegative
    CHECK (max_users IS NULL OR max_users >= 0);

ALTER TABLE public.company
    ADD CONSTRAINT company_max_devices_nonnegative
    CHECK (max_devices IS NULL OR max_devices >= 0);
