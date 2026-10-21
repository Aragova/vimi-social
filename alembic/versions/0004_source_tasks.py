"""Add durable AI-search source tasks and normalized candidates."""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_source_tasks"
down_revision: str | None = "0003_telegram_rate_limit_retry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE source_task (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            actor_user_id uuid NOT NULL REFERENCES app_user(id) ON DELETE RESTRICT,
            origin_key text NOT NULL UNIQUE,
            source_mode text NOT NULL,
            query_text text NOT NULL,
            requested_source text NULL,
            state text NOT NULL DEFAULT 'QUEUED',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CHECK (length(origin_key) BETWEEN 1 AND 200),
            CHECK (length(query_text) BETWEEN 1 AND 2000),
            CHECK (source_mode IN ('AI_SEARCH', 'MANUAL_UPLOAD', 'SOURCE_FEED')),
            CHECK (requested_source IS NULL OR requested_source IN (
                'X', 'TELEGRAM', 'REDDIT', 'WEB'
            )),
            CHECK (state IN (
                'QUEUED', 'DISCOVERING', 'CANDIDATES_READY',
                'FAILED_SAFE', 'BLOCKED'
            ))
        );

        CREATE INDEX source_task_tenant_state_idx
            ON source_task (tenant_id, state, created_at);

        CREATE TABLE telegram_intake_state (
            tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            user_id uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            state text NOT NULL,
            last_update_id bigint NOT NULL CHECK (last_update_id >= 0),
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, user_id),
            CHECK (state IN ('IDLE', 'AWAITING_AI_SEARCH_QUERY'))
        );

        CREATE TABLE source_candidate (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            source_task_id uuid NOT NULL REFERENCES source_task(id) ON DELETE CASCADE,
            source text NOT NULL,
            external_id text NOT NULL,
            canonical_url text NOT NULL,
            author_handle text NULL,
            text_body text NOT NULL DEFAULT '',
            published_at timestamptz NULL,
            possibly_sensitive boolean NOT NULL DEFAULT false,
            media_kind text NOT NULL,
            media_refs text[] NOT NULL DEFAULT '{}',
            created_at timestamptz NOT NULL DEFAULT now(),
            CHECK (source IN ('X', 'TELEGRAM', 'REDDIT', 'WEB')),
            CHECK (media_kind IN ('VIDEO', 'IMAGE', 'OTHER')),
            CHECK (length(external_id) BETWEEN 1 AND 300),
            CHECK (length(canonical_url) BETWEEN 1 AND 2000),
            UNIQUE (source_task_id, source, external_id)
        );

        CREATE INDEX source_candidate_task_idx
            ON source_candidate (tenant_id, source_task_id, created_at);

        ALTER TABLE source_task ENABLE ROW LEVEL SECURITY;
        ALTER TABLE source_task FORCE ROW LEVEL SECURITY;
        ALTER TABLE telegram_intake_state ENABLE ROW LEVEL SECURITY;
        ALTER TABLE telegram_intake_state FORCE ROW LEVEL SECURITY;
        ALTER TABLE source_candidate ENABLE ROW LEVEL SECURITY;
        ALTER TABLE source_candidate FORCE ROW LEVEL SECURITY;

        CREATE POLICY source_task_tenant_isolation ON source_task
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

        CREATE POLICY telegram_intake_state_tenant_isolation ON telegram_intake_state
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

        CREATE POLICY source_candidate_tenant_isolation ON source_candidate
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

        REVOKE ALL ON source_task, telegram_intake_state, source_candidate FROM PUBLIC;
        REVOKE ALL ON source_task, telegram_intake_state, source_candidate FROM vimi_app;

        GRANT SELECT, INSERT, UPDATE ON source_task TO vimi_app;
        GRANT SELECT, INSERT, UPDATE ON telegram_intake_state TO vimi_app;
        GRANT SELECT, INSERT ON source_candidate TO vimi_app;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS source_candidate;
        DROP TABLE IF EXISTS telegram_intake_state;
        DROP TABLE IF EXISTS source_task;
        """
    )
