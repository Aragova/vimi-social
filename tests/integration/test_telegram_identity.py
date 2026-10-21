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


def test_application_role_cannot_bypass_identity_resolver_with_direct_table_reads() -> None:
    engine = create_engine(_database_dsn())
    try:
        with pytest.raises(DBAPIError) as error:
            with Session(engine) as session, session.begin():
                session.execute(text("SELECT * FROM telegram_identity")).all()
        assert getattr(error.value.orig, "sqlstate", None) == "42501"
    finally:
        engine.dispose()


def test_telegram_update_claim_is_leased_and_idempotent() -> None:
    engine = create_engine(_database_dsn())
    try:
        with Session(engine) as session, session.begin():
            first = session.execute(
                text("SELECT claim_telegram_update(:update_id, :user_id)"),
                {"update_id": 810000001, "user_id": 910000002},
            ).scalar_one()
        assert first == "CLAIMED"

        with Session(engine) as session, session.begin():
            duplicate = session.execute(
                text("SELECT claim_telegram_update(:update_id, :user_id)"),
                {"update_id": 810000001, "user_id": 910000002},
            ).scalar_one()
        assert duplicate == "BUSY"

        with Session(engine) as session, session.begin():
            session.execute(
                text("SELECT complete_telegram_update(:update_id)"),
                {"update_id": 810000001},
            )

        with Session(engine) as session, session.begin():
            completed = session.execute(
                text("SELECT claim_telegram_update(:update_id, :user_id)"),
                {"update_id": 810000001, "user_id": 910000002},
            ).scalar_one()
        assert completed == "PROCESSED"
    finally:
        engine.dispose()
