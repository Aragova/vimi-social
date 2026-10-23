from os import environ
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.identity import OperationKey, TenantId
from vimi_social.usage.models import ReservationRequest
from vimi_social.usage.repository import UsageRepository

DEFAULT_SCOUT_RUN_QUOTA = 10


def _database_dsn() -> str:
    dsn = environ.get("VIMI_TEST_DATABASE_DSN")
    if dsn is None:
        pytest.skip("PostgreSQL integration DSN is not configured")
    return dsn


def _admin_dsn() -> str:
    dsn = environ.get("VIMI_TEST_ADMIN_DSN")
    if dsn is None:
        pytest.skip("PostgreSQL admin integration DSN is not configured")
    if dsn.startswith("postgresql://"):
        return "postgresql+psycopg://" + dsn.removeprefix("postgresql://")
    return dsn


def test_new_telegram_workspace_gets_default_scout_capacity() -> None:
    engine = create_engine(_database_dsn())
    session_factory = sessionmaker[Session](
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )

    try:
        with session_factory() as session, session.begin():
            row = session.execute(
                text(
                    """
                    SELECT *
                    FROM resolve_or_create_telegram_context(
                        :telegram_user_id,
                        NULL,
                        'en'
                    )
                    """
                ),
                {"telegram_user_id": 930000201},
            ).mappings().one()

        tenant_raw = row["resolved_tenant_id"]
        assert isinstance(tenant_raw, UUID)
        tenant_id = TenantId(tenant_raw)

        with session_factory() as session, tenant_transaction(session, tenant_id):
            capacity = session.execute(
                text(
                    """
                    SELECT quota, reserved, committed
                    FROM usage_capacity
                    WHERE metric = 'scout_run'
                    """
                )
            ).one()

        assert capacity == (DEFAULT_SCOUT_RUN_QUOTA, 0, 0)
    finally:
        engine.dispose()


def test_superadmin_internal_workspace_bypasses_all_capacity_enforcement() -> None:
    engine = create_engine(_database_dsn())
    admin_engine = create_engine(_admin_dsn())
    session_factory = sessionmaker[Session](
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )
    usage = UsageRepository()

    try:
        with session_factory() as session, session.begin():
            row = session.execute(
                text(
                    """
                    SELECT *
                    FROM resolve_or_create_telegram_context(
                        :telegram_user_id,
                        NULL,
                        'en'
                    )
                    """
                ),
                {"telegram_user_id": 930000202},
            ).mappings().one()

        tenant_raw = row["resolved_tenant_id"]
        user_raw = row["resolved_user_id"]
        assert isinstance(tenant_raw, UUID)
        assert isinstance(user_raw, UUID)

        with admin_engine.begin() as connection:
            connection.execute(
                text("UPDATE app_user SET platform_role = 'SUPERADMIN' WHERE id = :user_id"),
                {"user_id": str(user_raw)},
            )
            connection.execute(
                text("UPDATE tenant SET usage_policy = 'UNLIMITED' WHERE id = :tenant_id"),
                {"tenant_id": str(tenant_raw)},
            )

        tenant_id = TenantId(tenant_raw)
        operation_key = OperationKey("test:superadmin-unlimited:commit")
        huge_quantity = DEFAULT_SCOUT_RUN_QUOTA + 10_000

        with session_factory() as session, tenant_transaction(session, tenant_id):
            result = usage.reserve(
                session,
                ReservationRequest(
                    tenant_id=tenant_id,
                    operation_key=operation_key,
                    metric="scout_run",
                    quantity=huge_quantity,
                ),
            )
            assert result.joined_existing is False

            before_commit = session.execute(
                text(
                    """
                    SELECT quota, reserved, committed
                    FROM usage_capacity
                    WHERE metric = 'scout_run'
                    """
                )
            ).one()
            assert before_commit == (DEFAULT_SCOUT_RUN_QUOTA, 0, 0)

            assert usage.commit(session, operation_key) is True

            reservation = session.execute(
                text(
                    """
                    SELECT state, capacity_exempt
                    FROM usage_reservation
                    WHERE operation_key = :operation_key
                    """
                ),
                {"operation_key": operation_key.value},
            ).one()
            assert reservation == ("COMMITTED", True)

            charge = session.execute(
                text(
                    """
                    SELECT quantity
                    FROM usage_ledger
                    WHERE operation_key = :operation_key
                      AND entry_kind = 'CHARGE'
                    """
                ),
                {"operation_key": operation_key.value},
            ).scalar_one()
            assert charge == huge_quantity

            after_commit = session.execute(
                text(
                    """
                    SELECT quota, reserved, committed
                    FROM usage_capacity
                    WHERE metric = 'scout_run'
                    """
                )
            ).one()
            assert after_commit == (DEFAULT_SCOUT_RUN_QUOTA, 0, 0)
    finally:
        admin_engine.dispose()
        engine.dispose()
