"""Provision default published-post capacity."""

from collections.abc import Sequence

from alembic import op

revision: str = "0010_published_post_capacity"
down_revision: str | None = "0009_visual_render_publish"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION provision_default_publish_capacity()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            v_previous_tenant text;
        BEGIN
            v_previous_tenant := current_setting('app.tenant_id', true);
            PERFORM set_config('app.tenant_id', NEW.id::text, true);
            INSERT INTO public.usage_capacity (tenant_id, metric, quota)
            VALUES (NEW.id, 'published_post', 1000)
            ON CONFLICT (tenant_id, metric) DO NOTHING;
            PERFORM set_config('app.tenant_id', coalesce(v_previous_tenant, ''), true);
            RETURN NEW;
        END;
        $$;
        REVOKE ALL ON FUNCTION provision_default_publish_capacity() FROM PUBLIC;

        CREATE TRIGGER tenant_provision_default_publish_capacity
        AFTER INSERT ON public.tenant
        FOR EACH ROW EXECUTE FUNCTION provision_default_publish_capacity();

        DO $$
        DECLARE
            v_tenant_id uuid;
            v_previous_tenant text;
        BEGIN
            v_previous_tenant := current_setting('app.tenant_id', true);
            FOR v_tenant_id IN SELECT id FROM public.tenant LOOP
                PERFORM set_config('app.tenant_id', v_tenant_id::text, true);
                INSERT INTO public.usage_capacity (tenant_id, metric, quota)
                VALUES (v_tenant_id, 'published_post', 1000)
                ON CONFLICT (tenant_id, metric) DO NOTHING;
            END LOOP;
            PERFORM set_config('app.tenant_id', coalesce(v_previous_tenant, ''), true);
        END;
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS tenant_provision_default_publish_capacity ON public.tenant;
        DROP FUNCTION IF EXISTS provision_default_publish_capacity();
        """
    )
