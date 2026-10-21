"""Bootstrap tenant, publication, and usage authority tables."""

from collections.abc import Sequence

from alembic import op

revision: str = "0001_bootstrap"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute(
        """
        CREATE TABLE tenant (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            slug text NOT NULL UNIQUE,
            created_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE operation_identity (
            operation_key text PRIMARY KEY,
            tenant_id uuid NOT NULL REFERENCES tenant(id),
            created_at timestamptz NOT NULL DEFAULT now()
        );

        REVOKE ALL ON operation_identity FROM PUBLIC;

        CREATE FUNCTION claim_operation_key(p_tenant_id uuid, p_operation_key text)
        RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            bound_tenant uuid;
        BEGIN
            INSERT INTO public.operation_identity (operation_key, tenant_id)
            VALUES (p_operation_key, p_tenant_id)
            ON CONFLICT (operation_key) DO NOTHING;

            SELECT tenant_id INTO bound_tenant
            FROM public.operation_identity
            WHERE operation_key = p_operation_key;

            RETURN bound_tenant = p_tenant_id;
        END;
        $$;

        REVOKE ALL ON FUNCTION claim_operation_key(uuid, text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION claim_operation_key(uuid, text) TO vimi_app;

        CREATE TABLE publication_operation (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenant(id),
            operation_key text NOT NULL UNIQUE,
            target_id text NOT NULL,
            state text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CHECK (state IN (
                'REQUESTED','RESERVED','DISPATCHING','PROVIDER_ACCEPTED',
                'UNKNOWN','CONFIRMED','FAILED_SAFE','FAILED_PERMANENT'
            ))
        );

        CREATE TABLE usage_capacity (
            tenant_id uuid NOT NULL REFERENCES tenant(id),
            metric text NOT NULL,
            quota bigint NOT NULL CHECK (quota >= 0),
            reserved bigint NOT NULL DEFAULT 0 CHECK (reserved >= 0),
            committed bigint NOT NULL DEFAULT 0 CHECK (committed >= 0),
            PRIMARY KEY (tenant_id, metric),
            CHECK (reserved + committed <= quota)
        );

        CREATE TABLE usage_reservation (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenant(id),
            operation_key text NOT NULL UNIQUE,
            metric text NOT NULL,
            quantity bigint NOT NULL CHECK (quantity > 0),
            state text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CHECK (state IN ('RESERVED','COMMITTED','RELEASED','EXPIRED'))
        );

        CREATE TABLE usage_ledger (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenant(id),
            operation_key text NOT NULL,
            entry_kind text NOT NULL,
            metric text NOT NULL,
            quantity bigint NOT NULL,
            source_entry_id uuid NULL REFERENCES usage_ledger(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK (entry_kind IN ('CHARGE','ADJUSTMENT'))
        );

        CREATE UNIQUE INDEX usage_ledger_charge_once
        ON usage_ledger(operation_key)
        WHERE entry_kind = 'CHARGE';

        ALTER TABLE publication_operation ENABLE ROW LEVEL SECURITY;
        ALTER TABLE publication_operation FORCE ROW LEVEL SECURITY;
        ALTER TABLE usage_capacity ENABLE ROW LEVEL SECURITY;
        ALTER TABLE usage_capacity FORCE ROW LEVEL SECURITY;
        ALTER TABLE usage_reservation ENABLE ROW LEVEL SECURITY;
        ALTER TABLE usage_reservation FORCE ROW LEVEL SECURITY;
        ALTER TABLE usage_ledger ENABLE ROW LEVEL SECURITY;
        ALTER TABLE usage_ledger FORCE ROW LEVEL SECURITY;

        CREATE POLICY publication_tenant_isolation ON publication_operation
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
        CREATE POLICY usage_capacity_tenant_isolation ON usage_capacity
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
        CREATE POLICY usage_reservation_tenant_isolation ON usage_reservation
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
        CREATE POLICY usage_ledger_tenant_isolation ON usage_ledger
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

        GRANT SELECT, INSERT, UPDATE, DELETE ON publication_operation TO vimi_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON usage_capacity TO vimi_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON usage_reservation TO vimi_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON usage_ledger TO vimi_app;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS usage_ledger;
        DROP TABLE IF EXISTS usage_reservation;
        DROP TABLE IF EXISTS usage_capacity;
        DROP FUNCTION IF EXISTS claim_operation_key(uuid, text);
        DROP TABLE IF EXISTS publication_operation;
        DROP TABLE IF EXISTS operation_identity;
        DROP TABLE IF EXISTS tenant;
        """
    )
