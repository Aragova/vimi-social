"""Add rights-gated media preparation, asset lineage, and media usage capacity."""

from collections.abc import Sequence

from alembic import op

revision: str = "0007_media_preparation_pipeline"
down_revision: str | None = "0006_scout_attempt_fence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE source_task_candidate
        ADD CONSTRAINT source_task_candidate_id_tenant_unique UNIQUE (id, tenant_id);

        CREATE TABLE media_preparation (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            candidate_id uuid NOT NULL,
            operation_key text NOT NULL UNIQUE,
            rights_basis text NOT NULL DEFAULT 'UNKNOWN',
            rights_confirmed_by_user_id uuid NULL,
            rights_confirmed_at timestamptz NULL,
            state text NOT NULL DEFAULT 'AWAITING_RIGHTS',
            acquisition_attempt_token uuid NULL,
            failure_code text NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (id, tenant_id),
            UNIQUE (candidate_id),
            FOREIGN KEY (candidate_id, tenant_id)
                REFERENCES source_task_candidate(id, tenant_id)
                ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, rights_confirmed_by_user_id)
                REFERENCES workspace_membership(tenant_id, user_id),
            CHECK (length(operation_key) BETWEEN 1 AND 200),
            CHECK (rights_basis IN (
                'UNKNOWN', 'USER_CONFIRMED', 'CONNECTOR_AUTHORIZED',
                'OWNED_SOURCE', 'LICENSED_SOURCE'
            )),
            CHECK (state IN (
                'AWAITING_RIGHTS', 'QUEUED', 'ACQUIRING',
                'READY', 'FAILED_SAFE', 'BLOCKED'
            )),
            CHECK (
                (state = 'ACQUIRING' AND acquisition_attempt_token IS NOT NULL)
                OR (state <> 'ACQUIRING' AND acquisition_attempt_token IS NULL)
            ),
            CHECK (
                (rights_basis = 'UNKNOWN' AND rights_confirmed_at IS NULL)
                OR rights_basis <> 'UNKNOWN'
            )
        );

        CREATE TABLE media_asset (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            candidate_id uuid NOT NULL,
            preparation_id uuid NOT NULL,
            sha256 text NOT NULL,
            storage_path text NOT NULL,
            size_bytes bigint NOT NULL CHECK (size_bytes > 0),
            media_format text NOT NULL,
            content_type text NOT NULL,
            final_url text NOT NULL,
            duration_ms bigint NULL CHECK (duration_ms IS NULL OR duration_ms >= 0),
            width integer NULL CHECK (width IS NULL OR width > 0),
            height integer NULL CHECK (height IS NULL OR height > 0),
            video_codec text NULL,
            audio_codec text NULL,
            container text NULL,
            frame_rate double precision NULL CHECK (frame_rate IS NULL OR frame_rate > 0),
            has_audio boolean NOT NULL,
            adult_classification text NOT NULL,
            explicitness_score double precision NULL,
            classifier_version text NOT NULL,
            classification_signals text[] NOT NULL DEFAULT '{}',
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (preparation_id),
            UNIQUE (id, tenant_id),
            FOREIGN KEY (candidate_id, tenant_id)
                REFERENCES source_task_candidate(id, tenant_id)
                ON DELETE RESTRICT,
            FOREIGN KEY (preparation_id, tenant_id)
                REFERENCES media_preparation(id, tenant_id)
                ON DELETE RESTRICT,
            CHECK (length(sha256) = 64),
            CHECK (adult_classification IN (
                'UNKNOWN', 'NO_ADULT_SIGNAL_DETECTED',
                'POSSIBLY_SENSITIVE', 'ADULT_EXPLICIT'
            )),
            CHECK (
                explicitness_score IS NULL
                OR (explicitness_score >= 0 AND explicitness_score <= 1)
            )
        );

        ALTER TABLE media_preparation ENABLE ROW LEVEL SECURITY;
        ALTER TABLE media_preparation FORCE ROW LEVEL SECURITY;
        ALTER TABLE media_asset ENABLE ROW LEVEL SECURITY;
        ALTER TABLE media_asset FORCE ROW LEVEL SECURITY;

        CREATE POLICY media_preparation_tenant_isolation
        ON media_preparation
            USING (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''))
            WITH CHECK (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''));

        CREATE POLICY media_asset_tenant_isolation
        ON media_asset
            USING (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''))
            WITH CHECK (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''));

        REVOKE ALL ON media_preparation, media_asset FROM PUBLIC;
        GRANT SELECT, INSERT, UPDATE ON media_preparation TO vimi_app;
        GRANT SELECT, INSERT ON media_asset TO vimi_app;

        CREATE FUNCTION provision_default_media_capacity()
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
            VALUES (NEW.id, 'video_second_processed', 600)
            ON CONFLICT (tenant_id, metric) DO NOTHING;
            PERFORM set_config('app.tenant_id', coalesce(v_previous_tenant, ''), true);
            RETURN NEW;
        END;
        $$;

        REVOKE ALL ON FUNCTION provision_default_media_capacity() FROM PUBLIC;

        CREATE TRIGGER tenant_provision_default_media_capacity
        AFTER INSERT ON public.tenant
        FOR EACH ROW EXECUTE FUNCTION provision_default_media_capacity();

        DO $$
        DECLARE
            v_tenant_id uuid;
            v_previous_tenant text;
        BEGIN
            v_previous_tenant := current_setting('app.tenant_id', true);
            FOR v_tenant_id IN SELECT id FROM public.tenant LOOP
                PERFORM set_config('app.tenant_id', v_tenant_id::text, true);
                INSERT INTO public.usage_capacity (tenant_id, metric, quota)
                VALUES (v_tenant_id, 'video_second_processed', 600)
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
        DROP TRIGGER IF EXISTS tenant_provision_default_media_capacity ON public.tenant;
        DROP FUNCTION IF EXISTS provision_default_media_capacity();
        DROP TABLE IF EXISTS media_asset;
        DROP TABLE IF EXISTS media_preparation;
        ALTER TABLE source_task_candidate
            DROP CONSTRAINT IF EXISTS source_task_candidate_id_tenant_unique;
        """
    )
