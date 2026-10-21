"""Add Telegram-first identity and durable ingress/outgoing state."""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_telegram_identity"
down_revision: str | None = "0001_bootstrap"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app_user (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE telegram_identity (
            telegram_user_id bigint PRIMARY KEY CHECK (telegram_user_id > 0),
            user_id uuid NOT NULL UNIQUE REFERENCES app_user(id) ON DELETE CASCADE,
            username text NULL,
            telegram_language_code text NULL,
            first_seen_at timestamptz NOT NULL DEFAULT now(),
            last_seen_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE workspace_membership (
            tenant_id uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            user_id uuid NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            role text NOT NULL,
            is_default boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, user_id),
            CHECK (role IN ('OWNER', 'MEMBER'))
        );

        CREATE UNIQUE INDEX workspace_membership_one_default
        ON workspace_membership(user_id)
        WHERE is_default;

        CREATE TABLE user_preferences (
            user_id uuid PRIMARY KEY REFERENCES app_user(id) ON DELETE CASCADE,
            locale text NOT NULL,
            timezone text NOT NULL DEFAULT 'UTC',
            region text NULL,
            preferred_content_languages text[] NOT NULL DEFAULT '{}',
            age_eligibility text NOT NULL DEFAULT 'UNKNOWN',
            updated_at timestamptz NOT NULL DEFAULT now(),
            CHECK (locale IN ('ru', 'en')),
            CHECK (region IS NULL OR region ~ '^[A-Z]{2}$'),
            CHECK (age_eligibility IN (
                'UNKNOWN', 'DECLARED_18_PLUS', 'VERIFIED_18_PLUS', 'RESTRICTED'
            ))
        );

        CREATE TABLE telegram_update_receipt (
            update_id bigint PRIMARY KEY CHECK (update_id >= 0),
            telegram_user_id bigint NULL,
            state text NOT NULL,
            attempts integer NOT NULL DEFAULT 1 CHECK (attempts > 0),
            lease_until timestamptz NULL,
            received_at timestamptz NOT NULL DEFAULT now(),
            processed_at timestamptz NULL,
            CHECK (state IN ('PROCESSING', 'PROCESSED'))
        );

        CREATE TABLE telegram_outgoing_operation (
            operation_key text PRIMARY KEY,
            update_id bigint NOT NULL REFERENCES telegram_update_receipt(update_id),
            chat_id bigint NOT NULL,
            action text NOT NULL,
            payload_sha256 text NOT NULL,
            state text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CHECK (length(operation_key) BETWEEN 1 AND 200),
            CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
            CHECK (state IN (
                'READY', 'DISPATCHING', 'CONFIRMED', 'UNKNOWN', 'FAILED_SAFE'
            ))
        );

        REVOKE ALL ON app_user, telegram_identity, workspace_membership,
            user_preferences, telegram_update_receipt, telegram_outgoing_operation
            FROM PUBLIC;
        REVOKE ALL ON app_user, telegram_identity, workspace_membership,
            user_preferences, telegram_update_receipt, telegram_outgoing_operation
            FROM vimi_app;

        CREATE FUNCTION resolve_or_create_telegram_context(
            p_telegram_user_id bigint,
            p_username text,
            p_language_code text
        )
        RETURNS TABLE (
            resolved_user_id uuid,
            resolved_tenant_id uuid,
            resolved_locale text,
            resolved_timezone text,
            resolved_region text,
            resolved_age_eligibility text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            v_user_id uuid;
            v_tenant_id uuid;
            v_locale text;
            v_timezone text;
            v_region text;
            v_age_eligibility text;
        BEGIN
            IF p_telegram_user_id <= 0 THEN
                RAISE EXCEPTION 'telegram user id must be positive'
                    USING ERRCODE = '22023';
            END IF;

            PERFORM pg_advisory_xact_lock(p_telegram_user_id);

            SELECT ti.user_id
            INTO v_user_id
            FROM public.telegram_identity AS ti
            WHERE ti.telegram_user_id = p_telegram_user_id;

            IF v_user_id IS NULL THEN
                INSERT INTO public.app_user DEFAULT VALUES
                RETURNING id INTO v_user_id;

                INSERT INTO public.tenant (slug)
                VALUES ('ws-' || replace(gen_random_uuid()::text, '-', ''))
                RETURNING id INTO v_tenant_id;

                INSERT INTO public.workspace_membership (
                    tenant_id, user_id, role, is_default
                )
                VALUES (v_tenant_id, v_user_id, 'OWNER', true);

                v_locale := CASE
                    WHEN lower(coalesce(p_language_code, '')) LIKE 'ru%' THEN 'ru'
                    ELSE 'en'
                END;

                INSERT INTO public.user_preferences (user_id, locale)
                VALUES (v_user_id, v_locale);

                INSERT INTO public.telegram_identity (
                    telegram_user_id,
                    user_id,
                    username,
                    telegram_language_code
                )
                VALUES (
                    p_telegram_user_id,
                    v_user_id,
                    p_username,
                    p_language_code
                );
            ELSE
                UPDATE public.telegram_identity
                SET username = p_username,
                    telegram_language_code = p_language_code,
                    last_seen_at = clock_timestamp()
                WHERE telegram_user_id = p_telegram_user_id;

                SELECT wm.tenant_id
                INTO v_tenant_id
                FROM public.workspace_membership AS wm
                WHERE wm.user_id = v_user_id
                ORDER BY wm.is_default DESC, wm.created_at ASC
                LIMIT 1;

                IF v_tenant_id IS NULL THEN
                    RAISE EXCEPTION 'telegram identity has no workspace membership'
                        USING ERRCODE = '55000';
                END IF;
            END IF;

            SELECT up.locale, up.timezone, up.region, up.age_eligibility
            INTO v_locale, v_timezone, v_region, v_age_eligibility
            FROM public.user_preferences AS up
            WHERE up.user_id = v_user_id;

            RETURN QUERY
            SELECT
                v_user_id,
                v_tenant_id,
                v_locale,
                v_timezone,
                v_region,
                v_age_eligibility;
        END;
        $$;

        CREATE FUNCTION claim_telegram_update(
            p_update_id bigint,
            p_telegram_user_id bigint
        )
        RETURNS text
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            v_state text;
            v_lease_until timestamptz;
        BEGIN
            IF p_update_id < 0 THEN
                RAISE EXCEPTION 'telegram update id must be non-negative'
                    USING ERRCODE = '22023';
            END IF;

            PERFORM pg_advisory_xact_lock(p_update_id);

            SELECT tur.state, tur.lease_until
            INTO v_state, v_lease_until
            FROM public.telegram_update_receipt AS tur
            WHERE tur.update_id = p_update_id;

            IF NOT FOUND THEN
                INSERT INTO public.telegram_update_receipt (
                    update_id,
                    telegram_user_id,
                    state,
                    lease_until
                )
                VALUES (
                    p_update_id,
                    p_telegram_user_id,
                    'PROCESSING',
                    clock_timestamp() + interval '2 minutes'
                );
                RETURN 'CLAIMED';
            END IF;

            IF v_state = 'PROCESSED' THEN
                RETURN 'PROCESSED';
            END IF;

            IF v_lease_until IS NOT NULL AND v_lease_until > clock_timestamp() THEN
                RETURN 'BUSY';
            END IF;

            UPDATE public.telegram_update_receipt
            SET telegram_user_id = p_telegram_user_id,
                state = 'PROCESSING',
                attempts = attempts + 1,
                lease_until = clock_timestamp() + interval '2 minutes'
            WHERE update_id = p_update_id;

            RETURN 'CLAIMED';
        END;
        $$;

        CREATE FUNCTION complete_telegram_update(p_update_id bigint)
        RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        BEGIN
            UPDATE public.telegram_update_receipt
            SET state = 'PROCESSED',
                lease_until = NULL,
                processed_at = clock_timestamp()
            WHERE update_id = p_update_id
              AND state = 'PROCESSING';

            IF NOT FOUND THEN
                RAISE EXCEPTION 'telegram update is not in PROCESSING state'
                    USING ERRCODE = '55000';
            END IF;
        END;
        $$;

        CREATE FUNCTION prepare_telegram_outgoing(
            p_operation_key text,
            p_update_id bigint,
            p_chat_id bigint,
            p_action text,
            p_payload_sha256 text
        )
        RETURNS text
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            v_update_id bigint;
            v_chat_id bigint;
            v_action text;
            v_payload_sha256 text;
            v_state text;
        BEGIN
            IF length(p_operation_key) NOT BETWEEN 1 AND 200 THEN
                RAISE EXCEPTION 'invalid telegram outgoing operation key'
                    USING ERRCODE = '22023';
            END IF;

            SELECT too.update_id, too.chat_id, too.action, too.payload_sha256, too.state
            INTO v_update_id, v_chat_id, v_action, v_payload_sha256, v_state
            FROM public.telegram_outgoing_operation AS too
            WHERE too.operation_key = p_operation_key
            FOR UPDATE;

            IF FOUND THEN
                IF v_update_id <> p_update_id
                    OR v_chat_id <> p_chat_id
                    OR v_action <> p_action
                    OR v_payload_sha256 <> p_payload_sha256 THEN
                    RAISE EXCEPTION 'telegram outgoing operation binding conflict'
                        USING ERRCODE = '23514';
                END IF;
                RETURN v_state;
            END IF;

            INSERT INTO public.telegram_outgoing_operation (
                operation_key,
                update_id,
                chat_id,
                action,
                payload_sha256,
                state
            )
            VALUES (
                p_operation_key,
                p_update_id,
                p_chat_id,
                p_action,
                p_payload_sha256,
                'READY'
            );
            RETURN 'READY';
        END;
        $$;

        CREATE FUNCTION begin_telegram_outgoing(p_operation_key text)
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

        CREATE FUNCTION finish_telegram_outgoing(
            p_operation_key text,
            p_state text
        )
        RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            v_state text;
        BEGIN
            IF p_state NOT IN ('CONFIRMED', 'UNKNOWN', 'FAILED_SAFE') THEN
                RAISE EXCEPTION 'invalid telegram outgoing final state'
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

            IF v_state = p_state THEN
                RETURN;
            END IF;

            IF v_state <> 'DISPATCHING' THEN
                RAISE EXCEPTION 'telegram outgoing operation cannot transition from %', v_state
                    USING ERRCODE = '55000';
            END IF;

            UPDATE public.telegram_outgoing_operation
            SET state = p_state, updated_at = clock_timestamp()
            WHERE operation_key = p_operation_key;
        END;
        $$;

        REVOKE ALL ON FUNCTION resolve_or_create_telegram_context(bigint, text, text)
            FROM PUBLIC;
        REVOKE ALL ON FUNCTION claim_telegram_update(bigint, bigint) FROM PUBLIC;
        REVOKE ALL ON FUNCTION complete_telegram_update(bigint) FROM PUBLIC;
        REVOKE ALL ON FUNCTION prepare_telegram_outgoing(text, bigint, bigint, text, text)
            FROM PUBLIC;
        REVOKE ALL ON FUNCTION begin_telegram_outgoing(text) FROM PUBLIC;
        REVOKE ALL ON FUNCTION finish_telegram_outgoing(text, text) FROM PUBLIC;

        GRANT EXECUTE ON FUNCTION resolve_or_create_telegram_context(bigint, text, text)
            TO vimi_app;
        GRANT EXECUTE ON FUNCTION claim_telegram_update(bigint, bigint) TO vimi_app;
        GRANT EXECUTE ON FUNCTION complete_telegram_update(bigint) TO vimi_app;
        GRANT EXECUTE ON FUNCTION prepare_telegram_outgoing(text, bigint, bigint, text, text)
            TO vimi_app;
        GRANT EXECUTE ON FUNCTION begin_telegram_outgoing(text) TO vimi_app;
        GRANT EXECUTE ON FUNCTION finish_telegram_outgoing(text, text) TO vimi_app;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION IF EXISTS finish_telegram_outgoing(text, text);
        DROP FUNCTION IF EXISTS begin_telegram_outgoing(text);
        DROP FUNCTION IF EXISTS prepare_telegram_outgoing(text, bigint, bigint, text, text);
        DROP FUNCTION IF EXISTS complete_telegram_update(bigint);
        DROP FUNCTION IF EXISTS claim_telegram_update(bigint, bigint);
        DROP FUNCTION IF EXISTS resolve_or_create_telegram_context(bigint, text, text);
        DROP TABLE IF EXISTS telegram_outgoing_operation;
        DROP TABLE IF EXISTS telegram_update_receipt;
        DROP TABLE IF EXISTS user_preferences;
        DROP TABLE IF EXISTS workspace_membership;
        DROP TABLE IF EXISTS telegram_identity;
        DROP TABLE IF EXISTS app_user;
        """
    )
