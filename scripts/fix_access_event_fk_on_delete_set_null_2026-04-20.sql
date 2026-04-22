-- Fix access_event.tenant_id FK to ON DELETE SET NULL
-- The SQLAlchemy model already declares ondelete="SET NULL" but the live DB
-- constraint was created without it, causing DELETE /api/tenants/:id to fail
-- with a ForeignKeyViolation when the tenant has any access_event rows.
--
-- Run this once against the live database, then restart the app.

ALTER TABLE access_event
    DROP CONSTRAINT access_event_tenant_id_fkey;

ALTER TABLE access_event
    ADD CONSTRAINT access_event_tenant_id_fkey
        FOREIGN KEY (tenant_id)
        REFERENCES tenant(tenant_id)
        ON DELETE SET NULL;
