from os import environ
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.identity import TenantId


DEFAULT_SCOUT_RUN_QUOTA = 10


def _database_dsn() -> str:
    dsn = environ.get("VIMI_TEST_DATABASE_DSN")
    if dsn is None:
        pytest.skip("PostgreSQL integration DSN is not configured")
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
