"""Add platform superadmin identity and unlimited internal usage policy."""

from collections.abc import Sequence

from alembic import op

revision: str = "0011_superadmin_unlimited_usage"
down_revision: str | None = "0010_published_post_capacity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE public.app_user
            ADD COLUMN platform_role text NOT NULL DEFAULT 'USER',
            ADD CONSTRAINT app_user_platform_role_check
                CHECK (platform_role IN ('USER', 'SUPERADMIN'));

        ALTER TABLE public.tenant
            ADD COLUMN usage_policy text NOT NULL DEFAULT 'METERED',
            ADD CONSTRAINT tenant_usage_policy_check
                CHECK (usage_policy IN ('METERED', 'UNLIMITED'));

        ALTER TABLE public.usage_reservation
            ADD COLUMN capacity_exempt boolean NOT NULL DEFAULT false;

        CREATE FUNCTION public.tenant_usage_is_unlimited(p_tenant_id uuid)
        RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            v_current_tenant text;
            v_usage_policy text;
        BEGIN
            v_current_tenant := nullif(current_setting('app.tenant_id', true), '');
            IF v_current_tenant IS NULL OR v_current_tenant::uuid <> p_tenant_id THEN
                RAISE EXCEPTION 'tenant usage policy lookup outside active tenant context'
                    USING ERRCODE = '42501';
            END IF;

            SELECT t.usage_policy
            INTO v_usage_policy
            FROM public.tenant AS t
            WHERE t.id = p_tenant_id;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'tenant not found for usage policy lookup'
                    USING ERRCODE = '22023';
            END IF;

            RETURN v_usage_policy = 'UNLIMITED';
        END;
        $$;

        REVOKE ALL ON FUNCTION public.tenant_usage_is_unlimited(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION public.tenant_usage_is_unlimited(uuid) TO vimi_app;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        REVOKE EXECUTE ON FUNCTION public.tenant_usage_is_unlimited(uuid) FROM vimi_app;
        DROP FUNCTION IF EXISTS public.tenant_usage_is_unlimited(uuid);

        ALTER TABLE public.usage_reservation
            DROP COLUMN IF EXISTS capacity_exempt;

        ALTER TABLE public.tenant
            DROP CONSTRAINT IF EXISTS tenant_usage_policy_check,
            DROP COLUMN IF EXISTS usage_policy;

        ALTER TABLE public.app_user
            DROP CONSTRAINT IF EXISTS app_user_platform_role_check,
            DROP COLUMN IF EXISTS platform_role;
        """
    )
