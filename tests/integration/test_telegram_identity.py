import os
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session


def _database_dsn() -> str:
    dsn = os.environ.get("VIMI_TEST_DATABASE_DSN")
    if dsn is None:
        pytest.skip("PostgreSQL integration DSN is not configured")
    return dsn


def _resolve(session: Session, telegram_user_id: int, language_code: str) -> dict[str, object]:
    row = session.execute(
        text(
            """
            SELECT *
            FROM resolve_or_create_telegram_context(
                :telegram_user_id,
                :username,
                :language_code
            )
            """
        ),
        {
            "telegram_user_id": telegram_user_id,
            "username": "integration_user",
            "language_code": language_code,
        },
    ).mappings().one()
    return dict(row)


def _claim_update(session: Session, update_id: int, user_id: int) -> str:
    raw = session.execute(
        text("SELECT claim_telegram_update(:update_id, :user_id)"),
        {"update_id": update_id, "user_id": user_id},
    ).scalar_one()
    assert isinstance(raw, str)
    return raw


def test_telegram_resolver_provisions_stable_workspace_and_preserves_locale_override() -> None:
    engine = create_engine(_database_dsn())
    try:
        with Session(engine) as session, session.begin():
            first = _resolve(session, 910000001, "ru-RU")

        assert isinstance(first["resolved_user_id"], UUID)
        assert isinstance(first["resolved_tenant_id"], UUID)
        assert first["resolved_locale"] == "ru"
        assert first["resolved_timezone"] == "UTC"
        assert first["resolved_region"] is None
        assert first["resolved_age_eligibility"] == "UNKNOWN"

        with Session(engine) as session, session.begin():
            second = _resolve(session, 910000001, "en")

        assert second["resolved_user_id"] == first["resolved_user_id"]
        assert second["resolved_tenant_id"] == first["resolved_tenant_id"]
        assert second["resolved_locale"] == "ru"
    finally:
        engine.dispose()


def test_application_role_cannot_read_identity_or_outgoing_tables_directly() -> None:
    engine = create_engine(_database_dsn())
    try:
        for table_name in ("telegram_identity", "telegram_outgoing_operation"):
            with (
                pytest.raises(DBAPIError) as error,
                Session(engine) as session,
                session.begin(),
            ):
                session.execute(text(f"SELECT * FROM {table_name}"))
            assert getattr(error.value.orig, "sqlstate", None) == "42501"
    finally:
        engine.dispose()


def test_telegram_update_claim_is_leased_and_idempotent() -> None:
    engine = create_engine(_database_dsn())
    try:
        with Session(engine) as session, session.begin():
            first = _claim_update(session, 810000001, 910000002)
        assert first == "CLAIMED"

        with Session(engine) as session, session.begin():
            duplicate = _claim_update(session, 810000001, 910000002)
        assert duplicate == "BUSY"

        with Session(engine) as session, session.begin():
            session.execute(
                text("SELECT complete_telegram_update(:update_id)"),
                {"update_id": 810000001},
            )

        with Session(engine) as session, session.begin():
            completed = _claim_update(session, 810000001, 910000002)
        assert completed == "PROCESSED"
    finally:
        engine.dispose()


def test_inflight_outgoing_operation_becomes_unknown_instead_of_redispatching() -> None:
    engine = create_engine(_database_dsn())
    update_id = 810000010
    operation_key = "telegram:update:810000010:start-main-menu"
    payload_hash = "a" * 64
    try:
        with Session(engine) as session, session.begin():
            assert _claim_update(session, update_id, 910000010) == "CLAIMED"
            prepared = session.execute(
                text(
                    """
                    SELECT prepare_telegram_outgoing(
                        :operation_key,
                        :update_id,
                        :chat_id,
                        :action,
                        :payload_hash
                    )
                    """
                ),
                {
                    "operation_key": operation_key,
                    "update_id": update_id,
                    "chat_id": 910000010,
                    "action": "start-main-menu",
                    "payload_hash": payload_hash,
                },
            ).scalar_one()
            assert prepared == "READY"
            dispatch = session.execute(
                text("SELECT begin_telegram_outgoing(:operation_key)"),
                {"operation_key": operation_key},
            ).scalar_one()
            assert dispatch == "DISPATCH"

        with Session(engine) as session, session.begin():
            recovered = session.execute(
                text("SELECT begin_telegram_outgoing(:operation_key)"),
                {"operation_key": operation_key},
            ).scalar_one()
            assert recovered == "UNKNOWN"

        with Session(engine) as session, session.begin():
            still_unknown = session.execute(
                text("SELECT begin_telegram_outgoing(:operation_key)"),
                {"operation_key": operation_key},
            ).scalar_one()
            assert still_unknown == "UNKNOWN"
    finally:
        engine.dispose()


def test_rate_limited_outgoing_is_deferred_without_losing_operation_identity() -> None:
    engine = create_engine(_database_dsn())
    update_id = 810000020
    operation_key = "telegram:update:810000020:start-main-menu"
    payload_hash = "b" * 64
    try:
        with Session(engine) as session, session.begin():
            assert _claim_update(session, update_id, 910000020) == "CLAIMED"
            session.execute(
                text(
                    """
                    SELECT prepare_telegram_outgoing(
                        :operation_key,
                        :update_id,
                        :chat_id,
                        :action,
                        :payload_hash
                    )
                    """
                ),
                {
                    "operation_key": operation_key,
                    "update_id": update_id,
                    "chat_id": 910000020,
                    "action": "start-main-menu",
                    "payload_hash": payload_hash,
                },
            )
            assert session.execute(
                text("SELECT begin_telegram_outgoing(:operation_key)"),
                {"operation_key": operation_key},
            ).scalar_one() == "DISPATCH"
            session.execute(
                text(
                    "SELECT defer_telegram_outgoing(:operation_key, :retry_after_seconds)"
                ),
                {"operation_key": operation_key, "retry_after_seconds": 30},
            )
            session.execute(
                text("SELECT defer_telegram_update(:update_id, :retry_after_seconds)"),
                {"update_id": update_id, "retry_after_seconds": 30},
            )

        with Session(engine) as session, session.begin():
            assert session.execute(
                text("SELECT begin_telegram_outgoing(:operation_key)"),
                {"operation_key": operation_key},
            ).scalar_one() == "RETRY_WAIT"
            assert _claim_update(session, update_id, 910000020) == "BUSY"
    finally:
        engine.dispose()
