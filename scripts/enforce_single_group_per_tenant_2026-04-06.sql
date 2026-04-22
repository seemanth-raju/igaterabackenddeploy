BEGIN;

ALTER TABLE public.tenant
    ADD COLUMN IF NOT EXISTS group_id integer;

ALTER TABLE public.tenant
    DROP CONSTRAINT IF EXISTS tenant_group_id_fkey;

ALTER TABLE public.tenant
    ADD CONSTRAINT tenant_group_id_fkey
    FOREIGN KEY (group_id) REFERENCES public.tenant_group(group_id) ON DELETE SET NULL;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = 'tenant_group_membership'
    ) THEN
        WITH ranked AS (
            SELECT tenant_id,
                   group_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY tenant_id
                       ORDER BY created_at DESC NULLS LAST, membership_id DESC
                   ) AS rn
            FROM public.tenant_group_membership
        )
        UPDATE public.tenant AS tenant
        SET group_id = ranked.group_id
        FROM ranked
        WHERE tenant.tenant_id = ranked.tenant_id
          AND ranked.rn = 1
          AND tenant.group_id IS NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_tenant_group_id
    ON public.tenant USING btree (group_id);

DROP TABLE IF EXISTS public.tenant_group_membership CASCADE;

COMMIT;
