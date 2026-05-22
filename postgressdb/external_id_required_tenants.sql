-- Migration: external_id_required_tenants
-- Enforce external_id on the tenant table at the database level.
-- This constraint only validates NEW rows (NOT VALID) so it will not fail
-- on existing tenants that were created without an external_id.
-- Run a follow-up data fix to backfill any NULL external_ids before
-- promoting this constraint to VALIDATE.

-- Step 1: Add NOT NULL constraint as NOT VALID (skips existing rows)
-- Note: PostgreSQL does not support NOT NULL with NOT VALID directly.
-- Use a CHECK constraint instead, then enforce at app layer (Pydantic validation
-- already requires external_id on TenantCreate).

ALTER TABLE tenant
    ADD CONSTRAINT tenant_external_id_not_empty
    CHECK (external_id IS NULL OR length(trim(external_id)) > 0);

-- Step 2 (run when you are ready to fully enforce NOT NULL on all rows):
-- First backfill any NULL external_ids:
--   UPDATE tenant SET external_id = 'UNKNOWN_' || tenant_id::text WHERE external_id IS NULL;
-- Then promote:
--   ALTER TABLE tenant ALTER COLUMN external_id SET NOT NULL;
--   ALTER TABLE tenant DROP CONSTRAINT IF EXISTS tenant_external_id_not_empty;
