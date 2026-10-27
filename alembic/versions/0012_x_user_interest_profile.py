"""Add tenant-isolated X user interest profiles for personalized Scout ranking."""

from collections.abc import Sequence

from alembic import op

revision: str = "0012_x_user_interest_profile"
down_revision: str | None = "0011_superadmin_unlimited_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE x_user_interest_profile (
            tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            user_id uuid NOT NULL,
            destination_account_id uuid NOT NULL,
            external_account_id text NOT NULL,
            term_weights jsonb NOT NULL DEFAULT '{}'::jsonb,
            hashtag_weights jsonb NOT NULL DEFAULT '{}'::jsonb,
            author_weights jsonb NOT NULL DEFAULT '{}'::jsonb,
            source_stats jsonb NOT NULL DEFAULT '{}'::jsonb,
            sample_size integer NOT NULL DEFAULT 0 CHECK (sample_size >= 0),
            generated_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, user_id),
            FOREIGN KEY (tenant_id, user_id)
                REFERENCES workspace_membership(tenant_id, user_id)
                ON DELETE CASCADE,
            FOREIGN KEY (destination_account_id, tenant_id)
                REFERENCES destination_account(id, tenant_id)
                ON DELETE CASCADE,
            CHECK (length(external_account_id) BETWEEN 1 AND 200)
        );

        ALTER TABLE x_user_interest_profile ENABLE ROW LEVEL SECURITY;
        ALTER TABLE x_user_interest_profile FORCE ROW LEVEL SECURITY;

        CREATE POLICY x_user_interest_profile_tenant_isolation
        ON x_user_interest_profile
            USING (tenant_id::text = NULLIF(current_setting('app.tenant_id', true), ''))
            WITH CHECK (
                tenant_id::text = NULLIF(current_setting('app.tenant_id', true), '')
            );

        REVOKE ALL ON x_user_interest_profile FROM PUBLIC;
        GRANT SELECT, INSERT, UPDATE, DELETE ON x_user_interest_profile TO vimi_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS x_user_interest_profile;")
