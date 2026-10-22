"""Fence Scout activity attempts so ambiguous retries cannot duplicate paid searches."""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_scout_attempt_fence"
down_revision: str | None = "0005_scout_usage_capacity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE source_task
        ADD COLUMN scout_attempt_token uuid NULL;

        CREATE INDEX source_task_scout_attempt_token_idx
        ON source_task (scout_attempt_token)
        WHERE scout_attempt_token IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS source_task_scout_attempt_token_idx;
        ALTER TABLE source_task DROP COLUMN IF EXISTS scout_attempt_token;
        """
    )
