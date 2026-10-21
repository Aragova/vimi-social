"""Add durable delayed retry for Telegram rate limits."""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_telegram_rate_limit_retry"
down_revision: str | None = "0002_telegram_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE telegram_outgoing_operation
            ADD COLUMN retry_after_at timestamptz NULL;

        ALTER TABLE telegram_outgoing_operation
            DROP CONSTRAINT IF EXISTS telegram_outgoing_operation_state_check;
        ALTER TABLE telegram_outgoing_operation
            ADD CONSTRAINT telegram_outgoing_operation_state_check
            CHECK (state IN (
                'READY', 'DISPATCHING', 'RETRY_WAIT',
                'CONFIRMED', 'UNKNOWN', 'FAILED_SAFE'
            ));

        CREATE FUNCTION defer_telegram_update(
            p_update_id bigint,
            p_retry_after_seconds integer
        )
        RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
            IF p_retry_after_seconds NOT BETWEEN 1 AND 86400 THEN
                RAISE EXCEPTION 'invalid Telegram retry delay'
                    USING ERRCODE = '22023';
            END IF;

            UPDATE public.telegram_update_receipt
            SET lease_until = clock_timestamp()
                + make_interval(secs => p_retry_after_seconds)
            WHERE update_id = p_update_id
              AND state = 'PROCESSING';

            IF NOT FOUND THEN
                RAISE EXCEPTION 'telegram update is not in PROCESSING state'
                    USING ERRCODE = '55000';
            END IF;
        END;
        $$;

        CREATE OR REPLACE FUNCTION begin_telegram_outgoing(p_operation_key text)
        RETURNS text
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            v_state text;
            v_retry_after_at timestamptz;
        BEGIN
            SELECT too.state, too.retry_after_at
            INTO v_state, v_retry_after_at
            FROM public.telegram_outgoing_operation AS too
            WHERE too.operation_key = p_operation_key
            FOR UPDATE;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'telegram outgoing operation not prepared'
                    USING ERRCODE = '55000';
            END IF;

            IF v_state = 'READY' THEN
                UPDATE public.telegram_outgoing_operation
                SET state = 'DISPATCHING',
                    retry_after_at = NULL,
                    updated_at = clock_timestamp()
                WHERE operation_key = p_operation_key;
                RETURN 'DISPATCH';
            END IF;

            IF v_state = 'RETRY_WAIT' THEN
                IF v_retry_after_at IS NULL OR v_retry_after_at > clock_timestamp() THEN
                    RETURN 'RETRY_WAIT';
                END IF;

                UPDATE public.telegram_outgoing_operation
                SET state = 'DISPATCHING',
                    retry_after_at = NULL,
                    updated_at = clock_timestamp()
                WHERE operation_key = p_operation_key;
                RETURN 'DISPATCH';
            END IF;

            IF v_state = 'DISPATCHING' THEN
                UPDATE public.telegram_outgoing_operation
                SET state = 'UNKNOWN', updated_at = clock_timestamp()
                WHERE operation_key = p_operation_key;
                RETURN 'UNKNOWN';
            END IF;

            RETURN v_state;
        END;
        $$;

        CREATE FUNCTION defer_telegram_outgoing(
            p_operation_key text,
            p_retry_after_seconds integer
        )
        RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            v_state text;
        BEGIN
            IF p_retry_after_seconds NOT BETWEEN 1 AND 86400 THEN
                RAISE EXCEPTION 'invalid Telegram retry delay'
                    USING ERRCODE = '22023';
            END IF;

            SELECT too.state
            INTO v_state
            FROM public.telegram_outgoing_operation AS too
            WHERE too.operation_key = p_operation_key
            FOR UPDATE;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'telegram outgoing operation not prepared'
                    USING ERRCODE = '55000';
            END IF;

            IF v_state = 'RETRY_WAIT' THEN
                RETURN;
            END IF;

            IF v_state <> 'DISPATCHING' THEN
                RAISE EXCEPTION 'telegram outgoing operation cannot defer from %', v_state
                    USING ERRCODE = '55000';
            END IF;

            UPDATE public.telegram_outgoing_operation
            SET state = 'RETRY_WAIT',
                retry_after_at = clock_timestamp()
                    + make_interval(secs => p_retry_after_seconds),
                updated_at = clock_timestamp()
            WHERE operation_key = p_operation_key;
        END;
        $$;

        REVOKE ALL ON FUNCTION defer_telegram_update(bigint, integer) FROM PUBLIC;
        REVOKE ALL ON FUNCTION defer_telegram_outgoing(text, integer) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION defer_telegram_update(bigint, integer) TO vimi_app;
        GRANT EXECUTE ON FUNCTION defer_telegram_outgoing(text, integer) TO vimi_app;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION IF EXISTS defer_telegram_outgoing(text, integer);
        DROP FUNCTION IF EXISTS defer_telegram_update(bigint, integer);

        UPDATE telegram_outgoing_operation
        SET state = 'UNKNOWN', retry_after_at = NULL
        WHERE state = 'RETRY_WAIT';

        CREATE OR REPLACE FUNCTION begin_telegram_outgoing(p_operation_key text)
        RETURNS text
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            v_state text;
        BEGIN
            SELECT too.state
            INTO v_state
            FROM public.telegram_outgoing_operation AS too
            WHERE too.operation_key = p_operation_key
            FOR UPDATE;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'telegram outgoing operation not prepared'
                    USING ERRCODE = '55000';
            END IF;

            IF v_state = 'READY' THEN
                UPDATE public.telegram_outgoing_operation
                SET state = 'DISPATCHING', updated_at = clock_timestamp()
                WHERE operation_key = p_operation_key;
                RETURN 'DISPATCH';
            END IF;

            IF v_state = 'DISPATCHING' THEN
                UPDATE public.telegram_outgoing_operation
                SET state = 'UNKNOWN', updated_at = clock_timestamp()
                WHERE operation_key = p_operation_key;
                RETURN 'UNKNOWN';
            END IF;

            RETURN v_state;
        END;
        $$;

        ALTER TABLE telegram_outgoing_operation
            DROP CONSTRAINT IF EXISTS telegram_outgoing_operation_state_check;
        ALTER TABLE telegram_outgoing_operation
            ADD CONSTRAINT telegram_outgoing_operation_state_check
            CHECK (state IN (
                'READY', 'DISPATCHING', 'CONFIRMED', 'UNKNOWN', 'FAILED_SAFE'
            ));
        ALTER TABLE telegram_outgoing_operation DROP COLUMN retry_after_at;
        """
    )
