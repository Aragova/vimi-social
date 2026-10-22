"""Add visual-classification, rendered-variant, and publication state."""

from collections.abc import Sequence

from alembic import op

revision: str = "0009_visual_render_publish"
down_revision: str | None = "0008_scene_variant_planning"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE media_scene
            DROP CONSTRAINT media_scene_classification_basis_check;
        ALTER TABLE media_scene
            ADD COLUMN classifier_version text NULL;
        ALTER TABLE media_scene
            ADD CONSTRAINT media_scene_classification_basis_check
            CHECK (classification_basis IN ('ASSET_LEVEL_INHERITED', 'VISUAL_MODERATION'));

        CREATE TABLE variant_artifact (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            plan_id uuid NOT NULL,
            asset_id uuid NOT NULL,
            operation_key text NOT NULL UNIQUE,
            state text NOT NULL DEFAULT 'QUEUED',
            render_attempt_token uuid NULL,
            sha256 text NULL,
            storage_path text NULL,
            size_bytes bigint NULL CHECK (size_bytes IS NULL OR size_bytes > 0),
            duration_ms bigint NULL CHECK (duration_ms IS NULL OR duration_ms > 0),
            failure_code text NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (id, tenant_id),
            UNIQUE (plan_id),
            FOREIGN KEY (plan_id, tenant_id)
                REFERENCES variant_plan(id, tenant_id)
                ON DELETE RESTRICT,
            FOREIGN KEY (asset_id, tenant_id)
                REFERENCES media_asset(id, tenant_id)
                ON DELETE RESTRICT,
            CHECK (length(operation_key) BETWEEN 1 AND 200),
            CHECK (state IN ('QUEUED', 'RENDERING', 'READY', 'FAILED_SAFE')),
            CHECK (
                (state = 'RENDERING' AND render_attempt_token IS NOT NULL)
                OR (state <> 'RENDERING' AND render_attempt_token IS NULL)
            ),
            CHECK (
                (state = 'READY' AND sha256 IS NOT NULL AND storage_path IS NOT NULL
                    AND size_bytes IS NOT NULL AND duration_ms IS NOT NULL)
                OR state <> 'READY'
            )
        );

        CREATE TABLE destination_account (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            platform text NOT NULL,
            external_account_id text NOT NULL,
            display_name text NULL,
            credential_ref text NOT NULL,
            state text NOT NULL DEFAULT 'ACTIVE',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (id, tenant_id),
            UNIQUE (tenant_id, platform, external_account_id),
            CHECK (length(platform) BETWEEN 1 AND 64),
            CHECK (length(external_account_id) BETWEEN 1 AND 200),
            CHECK (length(credential_ref) BETWEEN 1 AND 200),
            CHECK (state IN ('ACTIVE', 'DISABLED', 'REAUTH_REQUIRED'))
        );

        CREATE TABLE publication_operation (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            artifact_id uuid NOT NULL,
            destination_account_id uuid NOT NULL,
            operation_key text NOT NULL UNIQUE,
            state text NOT NULL DEFAULT 'AWAITING_APPROVAL',
            publish_attempt_token uuid NULL,
            caption text NOT NULL DEFAULT '',
            remote_media_id text NULL,
            remote_post_id text NULL,
            failure_code text NULL,
            approved_by_user_id uuid NULL,
            approved_at timestamptz NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (id, tenant_id),
            UNIQUE (artifact_id, destination_account_id),
            FOREIGN KEY (artifact_id, tenant_id)
                REFERENCES variant_artifact(id, tenant_id)
                ON DELETE RESTRICT,
            FOREIGN KEY (destination_account_id, tenant_id)
                REFERENCES destination_account(id, tenant_id)
                ON DELETE RESTRICT,
            FOREIGN KEY (tenant_id, approved_by_user_id)
                REFERENCES workspace_membership(tenant_id, user_id),
            CHECK (length(operation_key) BETWEEN 1 AND 200),
            CHECK (state IN (
                'AWAITING_APPROVAL', 'READY', 'DISPATCHING', 'CONFIRMED',
                'UNKNOWN', 'FAILED_SAFE', 'BLOCKED'
            )),
            CHECK (
                (state = 'DISPATCHING' AND publish_attempt_token IS NOT NULL)
                OR (state <> 'DISPATCHING' AND publish_attempt_token IS NULL)
            ),
            CHECK (state <> 'CONFIRMED' OR remote_post_id IS NOT NULL)
        );

        ALTER TABLE variant_artifact ENABLE ROW LEVEL SECURITY;
        ALTER TABLE variant_artifact FORCE ROW LEVEL SECURITY;
        ALTER TABLE destination_account ENABLE ROW LEVEL SECURITY;
        ALTER TABLE destination_account FORCE ROW LEVEL SECURITY;
        ALTER TABLE publication_operation ENABLE ROW LEVEL SECURITY;
        ALTER TABLE publication_operation FORCE ROW LEVEL SECURITY;

        CREATE POLICY variant_artifact_tenant_isolation ON variant_artifact
            USING (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''))
            WITH CHECK (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''));
        CREATE POLICY destination_account_tenant_isolation ON destination_account
            USING (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''))
            WITH CHECK (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''));
        CREATE POLICY publication_operation_tenant_isolation ON publication_operation
            USING (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''))
            WITH CHECK (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''));

        REVOKE ALL ON variant_artifact, destination_account, publication_operation FROM PUBLIC;
        GRANT SELECT, INSERT, UPDATE ON variant_artifact TO vimi_app;
        GRANT SELECT, INSERT, UPDATE ON destination_account TO vimi_app;
        GRANT SELECT, INSERT, UPDATE ON publication_operation TO vimi_app;
        GRANT UPDATE ON media_scene TO vimi_app;

        CREATE FUNCTION provision_default_render_capacity()
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
            VALUES (NEW.id, 'rendered_video_minute', 120)
            ON CONFLICT (tenant_id, metric) DO NOTHING;
            PERFORM set_config('app.tenant_id', coalesce(v_previous_tenant, ''), true);
            RETURN NEW;
        END;
        $$;
        REVOKE ALL ON FUNCTION provision_default_render_capacity() FROM PUBLIC;

        CREATE TRIGGER tenant_provision_default_render_capacity
        AFTER INSERT ON public.tenant
        FOR EACH ROW EXECUTE FUNCTION provision_default_render_capacity();

        DO $$
        DECLARE
            v_tenant_id uuid;
            v_previous_tenant text;
        BEGIN
            v_previous_tenant := current_setting('app.tenant_id', true);
            FOR v_tenant_id IN SELECT id FROM public.tenant LOOP
                PERFORM set_config('app.tenant_id', v_tenant_id::text, true);
                INSERT INTO public.usage_capacity (tenant_id, metric, quota)
                VALUES (v_tenant_id, 'rendered_video_minute', 120)
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
        DROP TRIGGER IF EXISTS tenant_provision_default_render_capacity ON public.tenant;
        DROP FUNCTION IF EXISTS provision_default_render_capacity();
        DROP TABLE IF EXISTS publication_operation;
        DROP TABLE IF EXISTS destination_account;
        DROP TABLE IF EXISTS variant_artifact;
        ALTER TABLE media_scene DROP CONSTRAINT IF EXISTS media_scene_classification_basis_check;
        ALTER TABLE media_scene DROP COLUMN IF EXISTS classifier_version;
        ALTER TABLE media_scene ADD CONSTRAINT media_scene_classification_basis_check
            CHECK (classification_basis = 'ASSET_LEVEL_INHERITED');
        """
    )
