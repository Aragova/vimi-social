"""Add visual classification, rendered variants, and destination publishing state."""

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

        -- `publication_operation` is the validated Architecture 1.0 authority
        -- created by 0001. Extend it rather than creating a competing lifecycle.
        ALTER TABLE publication_operation
            ADD CONSTRAINT publication_operation_id_tenant_unique UNIQUE (id, tenant_id);
        ALTER TABLE publication_operation
            ADD COLUMN artifact_id uuid NULL,
            ADD COLUMN destination_account_id uuid NULL,
            ADD COLUMN publish_attempt_token uuid NULL,
            ADD COLUMN caption text NOT NULL DEFAULT '',
            ADD COLUMN remote_media_id text NULL,
            ADD COLUMN remote_post_id text NULL,
            ADD COLUMN failure_code text NULL,
            ADD COLUMN approved_by_user_id uuid NULL,
            ADD COLUMN approved_at timestamptz NULL;

        ALTER TABLE publication_operation
            ADD CONSTRAINT publication_operation_artifact_tenant_fk
                FOREIGN KEY (artifact_id, tenant_id)
                REFERENCES variant_artifact(id, tenant_id)
                ON DELETE RESTRICT,
            ADD CONSTRAINT publication_operation_destination_tenant_fk
                FOREIGN KEY (destination_account_id, tenant_id)
                REFERENCES destination_account(id, tenant_id)
                ON DELETE RESTRICT,
            ADD CONSTRAINT publication_operation_approved_member_fk
                FOREIGN KEY (tenant_id, approved_by_user_id)
                REFERENCES workspace_membership(tenant_id, user_id),
            ADD CONSTRAINT publication_operation_artifact_destination_unique
                UNIQUE (artifact_id, destination_account_id);

        ALTER TABLE publication_operation
            DROP CONSTRAINT publication_operation_state_check;
        ALTER TABLE publication_operation
            ADD CONSTRAINT publication_operation_state_check CHECK (state IN (
                'REQUESTED','RESERVED','AWAITING_APPROVAL','READY','DISPATCHING',
                'PROVIDER_ACCEPTED','UNKNOWN','CONFIRMED','FAILED_SAFE',
                'FAILED_PERMANENT','BLOCKED'
            ));

        ALTER TABLE variant_artifact ENABLE ROW LEVEL SECURITY;
        ALTER TABLE variant_artifact FORCE ROW LEVEL SECURITY;
        ALTER TABLE destination_account ENABLE ROW LEVEL SECURITY;
        ALTER TABLE destination_account FORCE ROW LEVEL SECURITY;

        CREATE POLICY variant_artifact_tenant_isolation ON variant_artifact
            USING (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''))
            WITH CHECK (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''));
        CREATE POLICY destination_account_tenant_isolation ON destination_account
            USING (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''))
            WITH CHECK (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''));

        REVOKE ALL ON variant_artifact, destination_account FROM PUBLIC;
        GRANT SELECT, INSERT, UPDATE ON variant_artifact, destination_account TO vimi_app;
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

        ALTER TABLE publication_operation
            DROP CONSTRAINT IF EXISTS publication_operation_artifact_destination_unique,
            DROP CONSTRAINT IF EXISTS publication_operation_approved_member_fk,
            DROP CONSTRAINT IF EXISTS publication_operation_destination_tenant_fk,
            DROP CONSTRAINT IF EXISTS publication_operation_artifact_tenant_fk,
            DROP CONSTRAINT IF EXISTS publication_operation_id_tenant_unique;
        ALTER TABLE publication_operation
            DROP COLUMN IF EXISTS approved_at,
            DROP COLUMN IF EXISTS approved_by_user_id,
            DROP COLUMN IF EXISTS failure_code,
            DROP COLUMN IF EXISTS remote_post_id,
            DROP COLUMN IF EXISTS remote_media_id,
            DROP COLUMN IF EXISTS caption,
            DROP COLUMN IF EXISTS publish_attempt_token,
            DROP COLUMN IF EXISTS destination_account_id,
            DROP COLUMN IF EXISTS artifact_id;
        ALTER TABLE publication_operation
            DROP CONSTRAINT IF EXISTS publication_operation_state_check;
        ALTER TABLE publication_operation
            ADD CONSTRAINT publication_operation_state_check CHECK (state IN (
                'REQUESTED','RESERVED','DISPATCHING','PROVIDER_ACCEPTED',
                'UNKNOWN','CONFIRMED','FAILED_SAFE','FAILED_PERMANENT'
            ));

        DROP TABLE IF EXISTS destination_account;
        DROP TABLE IF EXISTS variant_artifact;
        ALTER TABLE media_scene DROP CONSTRAINT IF EXISTS media_scene_classification_basis_check;
        ALTER TABLE media_scene DROP COLUMN IF EXISTS classifier_version;
        ALTER TABLE media_scene ADD CONSTRAINT media_scene_classification_basis_check
            CHECK (classification_basis = 'ASSET_LEVEL_INHERITED');
        """
    )
