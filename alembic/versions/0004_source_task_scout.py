"""Add durable AI Search source tasks, conversation state, and candidates."""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_source_task_scout"
down_revision: str | None = "0003_telegram_rate_limit_retry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE telegram_conversation_state (
            tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            user_id uuid NOT NULL,
            chat_id bigint NOT NULL,
            state text NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, user_id, chat_id),
            FOREIGN KEY (tenant_id, user_id)
                REFERENCES workspace_membership(tenant_id, user_id)
                ON DELETE CASCADE,
            CHECK (state IN ('AWAITING_AI_SEARCH_INTENT'))
        );

        CREATE TABLE source_task (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            actor_user_id uuid NOT NULL,
            operation_key text NOT NULL UNIQUE,
            execution_token uuid NOT NULL DEFAULT gen_random_uuid() UNIQUE,
            source_mode text NOT NULL,
            user_intent text NOT NULL,
            requested_sources text[] NOT NULL DEFAULT '{}',
            preferred_languages text[] NOT NULL DEFAULT '{}',
            state text NOT NULL,
            failure_code text NULL,
            telegram_update_id bigint NULL REFERENCES telegram_update_receipt(update_id),
            telegram_message_id bigint NULL,
            telegram_chat_id bigint NULL,
            locale text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (id, tenant_id),
            FOREIGN KEY (tenant_id, actor_user_id)
                REFERENCES workspace_membership(tenant_id, user_id),
            CHECK (length(operation_key) BETWEEN 1 AND 200),
            CHECK (length(btrim(user_intent)) BETWEEN 1 AND 4000),
            CHECK (source_mode IN ('AI_SEARCH', 'MANUAL_UPLOAD', 'SOURCE_FEED')),
            CHECK (state IN ('QUEUED', 'SCOUTING', 'COMPLETED', 'FAILED_SAFE', 'UNKNOWN')),
            CHECK (locale IN ('ru', 'en'))
        );

        CREATE TABLE source_task_candidate (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            source_task_id uuid NOT NULL,
            source text NOT NULL,
            source_id text NOT NULL,
            source_url text NOT NULL,
            author text NULL,
            published_at timestamptz NULL,
            media_type text NOT NULL,
            duration_ms bigint NULL CHECK (duration_ms IS NULL OR duration_ms >= 0),
            width integer NULL CHECK (width IS NULL OR width >= 0),
            height integer NULL CHECK (height IS NULL OR height >= 0),
            title text NULL,
            caption text NULL,
            tags text[] NOT NULL DEFAULT '{}',
            engagement jsonb NOT NULL DEFAULT '{}'::jsonb,
            adult_classification text NOT NULL,
            explicitness_score double precision NULL,
            provenance_hint text NOT NULL,
            availability text NOT NULL,
            connector_metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            selected_at timestamptz NULL,
            selected_by_user_id uuid NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (source_task_id, source, source_id),
            FOREIGN KEY (source_task_id, tenant_id)
                REFERENCES source_task(id, tenant_id)
                ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, selected_by_user_id)
                REFERENCES workspace_membership(tenant_id, user_id),
            CHECK (adult_classification IN ('UNKNOWN', 'POSSIBLY_SENSITIVE')),
            CHECK (
                explicitness_score IS NULL
                OR (explicitness_score >= 0 AND explicitness_score <= 1)
            )
        );

        ALTER TABLE telegram_conversation_state ENABLE ROW LEVEL SECURITY;
        ALTER TABLE telegram_conversation_state FORCE ROW LEVEL SECURITY;
        ALTER TABLE source_task ENABLE ROW LEVEL SECURITY;
        ALTER TABLE source_task FORCE ROW LEVEL SECURITY;
        ALTER TABLE source_task_candidate ENABLE ROW LEVEL SECURITY;
        ALTER TABLE source_task_candidate FORCE ROW LEVEL SECURITY;

        CREATE POLICY telegram_conversation_tenant_isolation
        ON telegram_conversation_state
            USING (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''))
            WITH CHECK (
                tenant_id::text = NULLIF(current_setting('app.tenant_id', true), '')
            );

        CREATE POLICY source_task_tenant_isolation
        ON source_task
            USING (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''))
            WITH CHECK (
                tenant_id::text = NULLIF(current_setting('app.tenant_id', true), '')
            );

        CREATE POLICY source_task_candidate_tenant_isolation
        ON source_task_candidate
            USING (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''))
            WITH CHECK (
                tenant_id::text = NULLIF(current_setting('app.tenant_id', true), '')
            );

        REVOKE ALL ON telegram_conversation_state, source_task, source_task_candidate
            FROM PUBLIC;
        GRANT SELECT, INSERT, UPDATE, DELETE
            ON telegram_conversation_state, source_task, source_task_candidate
            TO vimi_app;

        CREATE FUNCTION resolve_source_task_tenant(
            p_operation_key text,
            p_execution_token uuid
        )
        RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            v_tenant_id uuid;
        BEGIN
            IF length(p_operation_key) NOT BETWEEN 1 AND 200 THEN
                RAISE EXCEPTION 'invalid source task operation key'
                    USING ERRCODE = '22023';
            END IF;

            SELECT st.tenant_id
            INTO v_tenant_id
            FROM public.source_task AS st
            WHERE st.operation_key = p_operation_key
              AND st.execution_token = p_execution_token;

            RETURN v_tenant_id;
        END;
        $$;

        REVOKE ALL ON FUNCTION resolve_source_task_tenant(text, uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION resolve_source_task_tenant(text, uuid) TO vimi_app;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION IF EXISTS resolve_source_task_tenant(text, uuid);
        DROP TABLE IF EXISTS source_task_candidate;
        DROP TABLE IF EXISTS source_task;
        DROP TABLE IF EXISTS telegram_conversation_state;
        """
    )
