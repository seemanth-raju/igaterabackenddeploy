import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from database.base import Base
from database.models import DeviceCommand, DeviceConfig, TenantGroup

log = logging.getLogger(__name__)

REQUIRED_SCHEMA: dict[str, set[str]] = {
    "company": {
        "company_id",
        "name",
        "domain",
        "max_users",
        "max_devices",
        "is_active",
        "created_at",
        "updated_at",
    },
    "app_user": {
        "user_id",
        "company_id",
        "role",
        "username",
        "full_name",
        "password_hash",
        "is_active",
    },
    "auth_token": {
        "token_id",
        "user_id",
        "access_token",
        "refresh_token",
        "expires_at",
        "revoked",
    },
    "site": {
        "site_id",
        "company_id",
        "name",
        "timezone",
        "address",
        "created_at",
    },
    "device": {
        "device_id",
        "company_id",
        "site_id",
        "device_serial_number",
        "vendor",
        "model_name",
        "ip_address",
        "mac_address",
        "api_username",
        "api_password_encrypted",
        "api_port",
        "use_https",
        "is_active",
        "communication_mode",
        "push_token_hash",
        "status",
        "last_heartbeat",
        "config",
        "created_at",
    },
    "device_command": {
        "command_id",
        "device_id",
        "cmd_id",
        "params",
        "status",
        "result",
        "correlation_id",
        "created_at",
        "sent_at",
        "completed_at",
        "error_message",
    },
    "device_config": {
        "config_entry_id",
        "device_id",
        "config_id",
        "params",
        "status",
        "correlation_id",
        "created_at",
        "sent_at",
        "completed_at",
        "error_message",
    },
    "tenant": {
        "tenant_id",
        "company_id",
        "group_id",
        "external_id",
        "full_name",
        "email",
        "phone",
        "is_active",
        "global_access_from",
        "global_access_till",
        "is_access_enabled",
        "access_timezone",
        "tenant_type",
        "created_at",
    },
    "tenant_group": {
        "group_id",
        "company_id",
        "parent_group_id",
        "name",
        "code",
        "email",
        "short_name",
        "description",
        "is_default",
        "is_active",
        "created_at",
        "updated_at",
    },
}


DEVICE_RUNTIME_PATCHES = (
    "ALTER TABLE public.device ADD COLUMN IF NOT EXISTS is_active boolean DEFAULT true",
    "ALTER TABLE public.device ADD COLUMN IF NOT EXISTS communication_mode character varying(10) DEFAULT 'direct'",
    "ALTER TABLE public.device ADD COLUMN IF NOT EXISTS push_token_hash character varying(128)",
    "ALTER TABLE public.device ADD COLUMN IF NOT EXISTS last_heartbeat timestamp with time zone",
    "UPDATE public.device SET communication_mode = 'direct' WHERE communication_mode IS NULL",
)


DEVICE_REFERENCE_KEY_PATCHES = (
    """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'device'
              AND column_name = 'device_id'
        )
        AND NOT EXISTS (
            SELECT 1
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON kcu.constraint_schema = tc.constraint_schema
             AND kcu.constraint_name = tc.constraint_name
             AND kcu.table_schema = tc.table_schema
             AND kcu.table_name = tc.table_name
            WHERE tc.table_schema = 'public'
              AND tc.table_name = 'device'
              AND tc.constraint_type IN ('PRIMARY KEY', 'UNIQUE')
            GROUP BY tc.constraint_schema, tc.constraint_name
            HAVING array_agg(kcu.column_name::text ORDER BY kcu.ordinal_position) = ARRAY['device_id']
        ) THEN
            ALTER TABLE public.device
                ADD CONSTRAINT device_device_id_reference_key UNIQUE (device_id);
        END IF;
    END $$;
    """,
)


COMPANY_QUOTA_PATCHES = (
    "ALTER TABLE public.company ADD COLUMN IF NOT EXISTS max_users integer",
    "ALTER TABLE public.company ADD COLUMN IF NOT EXISTS max_devices integer",
    "ALTER TABLE public.company DROP CONSTRAINT IF EXISTS company_max_users_nonnegative",
    "ALTER TABLE public.company DROP CONSTRAINT IF EXISTS company_max_devices_nonnegative",
    "ALTER TABLE public.company ADD CONSTRAINT company_max_users_nonnegative CHECK (max_users IS NULL OR max_users >= 0)",
    "ALTER TABLE public.company ADD CONSTRAINT company_max_devices_nonnegative CHECK (max_devices IS NULL OR max_devices >= 0)",
)


DEVICE_COMMAND_PATCHES = (
    "ALTER TABLE public.device_command ADD COLUMN IF NOT EXISTS params jsonb DEFAULT '{}'::jsonb",
    "ALTER TABLE public.device_command ADD COLUMN IF NOT EXISTS status character varying(20) DEFAULT 'pending'",
    "ALTER TABLE public.device_command ADD COLUMN IF NOT EXISTS result jsonb DEFAULT '{}'::jsonb",
    "ALTER TABLE public.device_command ADD COLUMN IF NOT EXISTS correlation_id character varying(50)",
    "ALTER TABLE public.device_command ADD COLUMN IF NOT EXISTS created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP",
    "ALTER TABLE public.device_command ADD COLUMN IF NOT EXISTS sent_at timestamp with time zone",
    "ALTER TABLE public.device_command ADD COLUMN IF NOT EXISTS completed_at timestamp with time zone",
    "ALTER TABLE public.device_command ADD COLUMN IF NOT EXISTS error_message text",
)


DEVICE_CONFIG_PATCHES = (
    "ALTER TABLE public.device_config ADD COLUMN IF NOT EXISTS params jsonb DEFAULT '{}'::jsonb",
    "ALTER TABLE public.device_config ADD COLUMN IF NOT EXISTS status character varying(20) DEFAULT 'pending'",
    "ALTER TABLE public.device_config ADD COLUMN IF NOT EXISTS correlation_id character varying(50)",
    "ALTER TABLE public.device_config ADD COLUMN IF NOT EXISTS created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP",
    "ALTER TABLE public.device_config ADD COLUMN IF NOT EXISTS sent_at timestamp with time zone",
    "ALTER TABLE public.device_config ADD COLUMN IF NOT EXISTS completed_at timestamp with time zone",
    "ALTER TABLE public.device_config ADD COLUMN IF NOT EXISTS error_message text",
)


TENANT_GROUP_PATCHES = (
    "ALTER TABLE public.tenant ADD COLUMN IF NOT EXISTS group_id integer",
    "ALTER TABLE public.tenant DROP CONSTRAINT IF EXISTS tenant_group_id_fkey",
    "ALTER TABLE public.tenant ADD CONSTRAINT tenant_group_id_fkey FOREIGN KEY (group_id) REFERENCES public.tenant_group(group_id) ON DELETE SET NULL",
    """
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'tenant_group_membership'
        ) THEN
            WITH ranked AS (
                SELECT tenant_id, group_id,
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
    """,
)


ACCESS_EVENT_CASCADE_PATCHES = (
    "ALTER TABLE public.access_event DROP CONSTRAINT IF EXISTS access_event_company_id_fkey",
    "ALTER TABLE public.access_event ADD CONSTRAINT access_event_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.company(company_id) ON DELETE CASCADE NOT VALID",
    "ALTER TABLE public.access_event DROP CONSTRAINT IF EXISTS access_event_device_id_fkey",
    "ALTER TABLE public.access_event ADD CONSTRAINT access_event_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.device(device_id) ON DELETE CASCADE NOT VALID",
    "ALTER TABLE public.access_event DROP CONSTRAINT IF EXISTS access_event_tenant_id_fkey",
    "ALTER TABLE public.access_event ADD CONSTRAINT access_event_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(tenant_id) ON DELETE CASCADE NOT VALID",
)


ACCESS_VALIDATION_LOG_CASCADE_PATCHES = (
    "ALTER TABLE public.access_validation_log DROP CONSTRAINT IF EXISTS access_validation_log_access_event_id_fkey",
    "ALTER TABLE public.access_validation_log ADD CONSTRAINT access_validation_log_access_event_id_fkey FOREIGN KEY (access_event_id) REFERENCES public.access_event(event_id) ON DELETE CASCADE NOT VALID",
    "ALTER TABLE public.access_validation_log DROP CONSTRAINT IF EXISTS access_validation_log_device_id_fkey",
    "ALTER TABLE public.access_validation_log ADD CONSTRAINT access_validation_log_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.device(device_id) ON DELETE CASCADE NOT VALID",
    "ALTER TABLE public.access_validation_log DROP CONSTRAINT IF EXISTS access_validation_log_site_id_fkey",
    "ALTER TABLE public.access_validation_log ADD CONSTRAINT access_validation_log_site_id_fkey FOREIGN KEY (site_id) REFERENCES public.site(site_id) ON DELETE CASCADE NOT VALID",
    "ALTER TABLE public.access_validation_log DROP CONSTRAINT IF EXISTS access_validation_log_tenant_id_fkey",
    "ALTER TABLE public.access_validation_log ADD CONSTRAINT access_validation_log_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(tenant_id) ON DELETE CASCADE NOT VALID",
)


# Ensure all device child tables have ON DELETE CASCADE so that deleting a
# device does not fail with FK violations on databases that were created before
# these cascade rules were established.
DEVICE_CHILD_CASCADE_PATCHES = (
    "ALTER TABLE public.device_user_mapping DROP CONSTRAINT IF EXISTS matrix_device_user_mapping_device_id_fkey",
    "ALTER TABLE public.device_user_mapping ADD CONSTRAINT matrix_device_user_mapping_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.device(device_id) ON DELETE CASCADE NOT VALID",
    "ALTER TABLE public.device_assignment_log DROP CONSTRAINT IF EXISTS device_assignment_log_device_id_fkey",
    "ALTER TABLE public.device_assignment_log ADD CONSTRAINT device_assignment_log_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.device(device_id) ON DELETE CASCADE NOT VALID",
    "ALTER TABLE public.tenant_device_access DROP CONSTRAINT IF EXISTS tenant_device_access_device_id_fkey",
    "ALTER TABLE public.tenant_device_access ADD CONSTRAINT tenant_device_access_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.device(device_id) ON DELETE CASCADE NOT VALID",
    "ALTER TABLE public.device_sync_log DROP CONSTRAINT IF EXISTS device_sync_log_device_id_fkey",
    "ALTER TABLE public.device_sync_log ADD CONSTRAINT device_sync_log_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.device(device_id) ON DELETE CASCADE NOT VALID",
    "ALTER TABLE public.device_command DROP CONSTRAINT IF EXISTS device_command_device_id_fkey",
    "ALTER TABLE public.device_command ADD CONSTRAINT device_command_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.device(device_id) ON DELETE CASCADE NOT VALID",
    "ALTER TABLE public.device_config DROP CONSTRAINT IF EXISTS device_config_device_id_fkey",
    "ALTER TABLE public.device_config ADD CONSTRAINT device_config_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.device(device_id) ON DELETE CASCADE NOT VALID",
)


# The device_assignment_log CHECK constraint in older databases only allowed 5
# action values.  The ORM model and service layer use 3 more ('capture',
# 'extract_fingerprint', 'enroll_site'), causing every capture/site-enroll
# operation to fail with a constraint violation and roll back silently.
DEVICE_ASSIGNMENT_LOG_ACTION_PATCH = (
    "ALTER TABLE public.device_assignment_log DROP CONSTRAINT IF EXISTS device_assignment_log_action_check",
    "ALTER TABLE public.device_assignment_log ADD CONSTRAINT device_assignment_log_action_check CHECK (action IN ('assign','revoke','update','enroll','unenroll','capture','extract_fingerprint','enroll_site'))",
)


# Enforce referential integrity for device → site (the ORM model declares this
# FK but no DDL was ever emitted for existing databases).
DEVICE_SITE_FK_PATCH = (
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.table_constraints
            WHERE table_schema = 'public'
              AND table_name   = 'device'
              AND constraint_name = 'device_site_id_fkey'
        ) THEN
            ALTER TABLE public.device
                ADD CONSTRAINT device_site_id_fkey
                FOREIGN KEY (site_id) REFERENCES public.site(site_id) ON DELETE SET NULL NOT VALID;
        END IF;
    END $$;
    """,
)


# Unique indexes ensure the ORM upsert logic (filter + .first()) works correctly.
# We use CREATE UNIQUE INDEX IF NOT EXISTS so duplicate data from old bugs does
# not block the startup — duplicates should be cleaned manually if they exist.
TENANT_ACCESS_UNIQUE_PATCHES = (
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_indexes
            WHERE schemaname = 'public' AND indexname = 'uq_tenant_device_access'
        ) AND NOT EXISTS (
            SELECT tenant_id, device_id FROM public.tenant_device_access
            GROUP BY tenant_id, device_id HAVING count(*) > 1
        ) THEN
            CREATE UNIQUE INDEX uq_tenant_device_access
                ON public.tenant_device_access (tenant_id, device_id);
        END IF;
    END $$;
    """,
    """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_indexes
            WHERE schemaname = 'public' AND indexname = 'uq_tenant_site_access'
        ) AND NOT EXISTS (
            SELECT tenant_id, site_id FROM public.tenant_site_access
            GROUP BY tenant_id, site_id HAVING count(*) > 1
        ) THEN
            CREATE UNIQUE INDEX uq_tenant_site_access
                ON public.tenant_site_access (tenant_id, site_id);
        END IF;
    END $$;
    """,
)


RUNTIME_INDEX_PATCHES = (
    "CREATE INDEX IF NOT EXISTS idx_devcmd_device ON public.device_command USING btree (device_id)",
    "CREATE INDEX IF NOT EXISTS idx_devcmd_status ON public.device_command USING btree (status)",
    "CREATE INDEX IF NOT EXISTS idx_devcmd_device_pending ON public.device_command USING btree (device_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_devcmd_correlation ON public.device_command USING btree (correlation_id)",
    "CREATE INDEX IF NOT EXISTS idx_devcfg_device ON public.device_config USING btree (device_id)",
    "CREATE INDEX IF NOT EXISTS idx_devcfg_status ON public.device_config USING btree (status)",
    "CREATE INDEX IF NOT EXISTS idx_devcfg_device_pending ON public.device_config USING btree (device_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_devcfg_correlation ON public.device_config USING btree (correlation_id)",
    "CREATE INDEX IF NOT EXISTS ix_tenant_group_id ON public.tenant USING btree (group_id)",
)


def _apply_runtime_schema_patches(engine: Engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table("device", schema="public"):
        return

    with engine.begin() as conn:
        if inspector.has_table("company", schema="public"):
            for statement in COMPANY_QUOTA_PATCHES:
                conn.execute(text(statement))

        for statement in DEVICE_RUNTIME_PATCHES:
            conn.execute(text(statement))

        for statement in DEVICE_REFERENCE_KEY_PATCHES:
            conn.execute(text(statement))

        if inspector.has_table("device_command", schema="public"):
            for statement in DEVICE_COMMAND_PATCHES:
                conn.execute(text(statement))

        if inspector.has_table("device_config", schema="public"):
            for statement in DEVICE_CONFIG_PATCHES:
                conn.execute(text(statement))

        if inspector.has_table("tenant", schema="public") and inspector.has_table("tenant_group", schema="public"):
            for statement in TENANT_GROUP_PATCHES:
                conn.execute(text(statement))

        if (
            inspector.has_table("access_event", schema="public")
            and inspector.has_table("company", schema="public")
            and inspector.has_table("tenant", schema="public")
        ):
            for statement in ACCESS_EVENT_CASCADE_PATCHES:
                conn.execute(text(statement))

        if (
            inspector.has_table("access_validation_log", schema="public")
            and inspector.has_table("access_event", schema="public")
            and inspector.has_table("site", schema="public")
            and inspector.has_table("tenant", schema="public")
        ):
            for statement in ACCESS_VALIDATION_LOG_CASCADE_PATCHES:
                conn.execute(text(statement))

        if inspector.has_table("device", schema="public"):
            for statement in DEVICE_CHILD_CASCADE_PATCHES:
                conn.execute(text(statement))

            for statement in DEVICE_ASSIGNMENT_LOG_ACTION_PATCH:
                conn.execute(text(statement))

            if inspector.has_table("site", schema="public"):
                for statement in DEVICE_SITE_FK_PATCH:
                    conn.execute(text(statement))

        if (
            inspector.has_table("tenant_device_access", schema="public")
            and inspector.has_table("tenant_site_access", schema="public")
        ):
            for statement in TENANT_ACCESS_UNIQUE_PATCHES:
                conn.execute(text(statement))

    Base.metadata.create_all(
        bind=engine,
        tables=[
            DeviceCommand.__table__,
            DeviceConfig.__table__,
            TenantGroup.__table__,
        ],
        checkfirst=True,
    )

    # Re-check after create_all: tenant_group may have just been created,
    # meaning TENANT_GROUP_PATCHES (which adds tenant.group_id) was skipped
    # in the first block. Re-run them now so the column exists before the
    # index patches below try to reference it.
    inspector2 = inspect(engine)
    with engine.begin() as conn:
        if inspector2.has_table("tenant", schema="public") and inspector2.has_table("tenant_group", schema="public"):
            for statement in TENANT_GROUP_PATCHES:
                conn.execute(text(statement))

    with engine.begin() as conn:
        for statement in RUNTIME_INDEX_PATCHES:
            conn.execute(text(statement))

    log.info("Runtime schema compatibility patches applied")


def assert_required_schema(engine: Engine) -> None:
    _apply_runtime_schema_patches(engine)
    inspector = inspect(engine)
    missing_tables: list[str] = []
    missing_columns: list[str] = []

    for table_name, required_columns in REQUIRED_SCHEMA.items():
        if not inspector.has_table(table_name, schema="public"):
            missing_tables.append(table_name)
            continue

        db_columns = {column["name"] for column in inspector.get_columns(table_name, schema="public")}
        for column_name in sorted(required_columns - db_columns):
            missing_columns.append(f"public.{table_name}.{column_name}")

    if not missing_tables and not missing_columns:
        return

    parts: list[str] = ["Database schema validation failed."]
    if missing_tables:
        parts.append(f"Missing tables: {', '.join(f'public.{t}' for t in missing_tables)}")
    if missing_columns:
        parts.append(f"Missing columns: {', '.join(missing_columns)}")

    parts.append(
        "Run: psql \"$DATABASE_URL\" -f files/sql_file/init.sql"
    )
    raise RuntimeError(" ".join(parts))
