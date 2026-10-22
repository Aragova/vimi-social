"""Add durable scene analysis and variant planning state."""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_scene_analysis_variant_planning"
down_revision: str | None = "0007_media_preparation_pipeline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE media_analysis (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            asset_id uuid NOT NULL,
            preparation_id uuid NOT NULL,
            operation_key text NOT NULL UNIQUE,
            state text NOT NULL DEFAULT 'QUEUED',
            analysis_attempt_token uuid NULL,
            detector_version text NULL,
            ranker_version text NULL,
            failure_code text NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (id, tenant_id),
            UNIQUE (asset_id),
            FOREIGN KEY (asset_id, tenant_id)
                REFERENCES media_asset(id, tenant_id)
                ON DELETE RESTRICT,
            FOREIGN KEY (preparation_id, tenant_id)
                REFERENCES media_preparation(id, tenant_id)
                ON DELETE RESTRICT,
            CHECK (length(operation_key) BETWEEN 1 AND 200),
            CHECK (state IN ('QUEUED', 'ANALYZING', 'READY', 'FAILED_SAFE')),
            CHECK (
                (state = 'ANALYZING' AND analysis_attempt_token IS NOT NULL)
                OR (state <> 'ANALYZING' AND analysis_attempt_token IS NULL)
            )
        );

        CREATE TABLE media_scene (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            analysis_id uuid NOT NULL,
            asset_id uuid NOT NULL,
            ordinal integer NOT NULL CHECK (ordinal >= 0),
            start_ms bigint NOT NULL CHECK (start_ms >= 0),
            end_ms bigint NOT NULL,
            rank_score double precision NOT NULL CHECK (rank_score >= 0 AND rank_score <= 1),
            adult_classification text NOT NULL,
            explicitness_score double precision NULL,
            classification_basis text NOT NULL,
            classification_signals text[] NOT NULL DEFAULT '{}',
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (id, tenant_id),
            UNIQUE (analysis_id, ordinal),
            FOREIGN KEY (analysis_id, tenant_id)
                REFERENCES media_analysis(id, tenant_id)
                ON DELETE CASCADE,
            FOREIGN KEY (asset_id, tenant_id)
                REFERENCES media_asset(id, tenant_id)
                ON DELETE RESTRICT,
            CHECK (end_ms > start_ms),
            CHECK (adult_classification IN (
                'UNKNOWN', 'NO_ADULT_SIGNAL_DETECTED',
                'POSSIBLY_SENSITIVE', 'ADULT_EXPLICIT'
            )),
            CHECK (
                explicitness_score IS NULL
                OR (explicitness_score >= 0 AND explicitness_score <= 1)
            ),
            CHECK (classification_basis = 'ASSET_LEVEL_INHERITED')
        );

        CREATE TABLE variant_plan (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            analysis_id uuid NOT NULL,
            asset_id uuid NOT NULL,
            destination text NOT NULL,
            decision text NOT NULL,
            capability_version text NOT NULL,
            policy_version text NOT NULL,
            planner_version text NOT NULL,
            render_strategy text NULL,
            expected_duration_ms bigint NULL CHECK (
                expected_duration_ms IS NULL OR expected_duration_ms >= 0
            ),
            requires_sensitive_label boolean NOT NULL DEFAULT false,
            reason_codes text[] NOT NULL DEFAULT '{}',
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (id, tenant_id),
            UNIQUE (analysis_id, destination),
            FOREIGN KEY (analysis_id, tenant_id)
                REFERENCES media_analysis(id, tenant_id)
                ON DELETE CASCADE,
            FOREIGN KEY (asset_id, tenant_id)
                REFERENCES media_asset(id, tenant_id)
                ON DELETE RESTRICT,
            CHECK (length(destination) BETWEEN 1 AND 64),
            CHECK (decision IN (
                'DIRECT_ALLOWED', 'ADAPTATION_REQUIRED',
                'MANUAL_REVIEW_REQUIRED', 'BLOCKED'
            )),
            CHECK (render_strategy IS NULL OR render_strategy IN ('PASSTHROUGH', 'CLIP_SEQUENCE')),
            CHECK (
                (decision = 'BLOCKED' AND render_strategy IS NULL AND expected_duration_ms IS NULL)
                OR (
                    decision IN ('DIRECT_ALLOWED', 'ADAPTATION_REQUIRED', 'MANUAL_REVIEW_REQUIRED')
                    AND render_strategy IS NOT NULL
                    AND expected_duration_ms IS NOT NULL
                )
            )
        );

        CREATE TABLE variant_plan_segment (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            plan_id uuid NOT NULL,
            scene_id uuid NOT NULL,
            sequence_index integer NOT NULL CHECK (sequence_index >= 0),
            start_ms bigint NOT NULL CHECK (start_ms >= 0),
            end_ms bigint NOT NULL,
            rank_score double precision NOT NULL CHECK (rank_score >= 0 AND rank_score <= 1),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (plan_id, sequence_index),
            FOREIGN KEY (plan_id, tenant_id)
                REFERENCES variant_plan(id, tenant_id)
                ON DELETE CASCADE,
            FOREIGN KEY (scene_id, tenant_id)
                REFERENCES media_scene(id, tenant_id)
                ON DELETE RESTRICT,
            CHECK (end_ms > start_ms)
        );

        ALTER TABLE media_analysis ENABLE ROW LEVEL SECURITY;
        ALTER TABLE media_analysis FORCE ROW LEVEL SECURITY;
        ALTER TABLE media_scene ENABLE ROW LEVEL SECURITY;
        ALTER TABLE media_scene FORCE ROW LEVEL SECURITY;
        ALTER TABLE variant_plan ENABLE ROW LEVEL SECURITY;
        ALTER TABLE variant_plan FORCE ROW LEVEL SECURITY;
        ALTER TABLE variant_plan_segment ENABLE ROW LEVEL SECURITY;
        ALTER TABLE variant_plan_segment FORCE ROW LEVEL SECURITY;

        CREATE POLICY media_analysis_tenant_isolation ON media_analysis
            USING (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''))
            WITH CHECK (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''));
        CREATE POLICY media_scene_tenant_isolation ON media_scene
            USING (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''))
            WITH CHECK (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''));
        CREATE POLICY variant_plan_tenant_isolation ON variant_plan
            USING (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''))
            WITH CHECK (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''));
        CREATE POLICY variant_plan_segment_tenant_isolation ON variant_plan_segment
            USING (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''))
            WITH CHECK (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''));

        REVOKE ALL ON media_analysis, media_scene, variant_plan, variant_plan_segment FROM PUBLIC;
        GRANT SELECT, INSERT, UPDATE ON media_analysis TO vimi_app;
        GRANT SELECT, INSERT ON media_scene, variant_plan, variant_plan_segment TO vimi_app;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS variant_plan_segment;
        DROP TABLE IF EXISTS variant_plan;
        DROP TABLE IF EXISTS media_scene;
        DROP TABLE IF EXISTS media_analysis;
        """
    )
