import os
from uuid import UUID, uuid4

import psycopg
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from vimi_social.db.tenant import TenantTransactionRequired, tenant_transaction
from vimi_social.domain.identity import TenantId


def _database_dsns() -> tuple[str, str]:
    app_dsn = os.environ.get("VIMI_TEST_DATABASE_DSN")
    admin_dsn = os.environ.get("VIMI_TEST_ADMIN_DSN")
    if not app_dsn or not admin_dsn:
        pytest.skip("PostgreSQL integration DSNs are not configured")
    return app_dsn, admin_dsn


def _seed_tenants(admin_dsn: str, tenant_ids: tuple[UUID, UUID]) -> None:
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        for index, tenant_id in enumerate(tenant_ids):
            conn.execute(
                "INSERT INTO tenant (id, slug) VALUES (%s, %s)",
                (tenant_id, f"rls-test-{tenant_id}-{index}"),
            )


def test_application_role_is_production_like_and_not_owner() -> None:
    _, admin_dsn = _database_dsns()
    with psycopg.connect(admin_dsn) as conn:
        role = conn.execute(
            """
            SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls
            FROM pg_roles
            WHERE rolname = 'vimi_app'
            """
        ).fetchone()
        assert role == (False, False, False, False)

        membership = conn.execute(
            "SELECT pg_has_role('vimi_app', 'vimi_migration_owner', 'MEMBER')"
        ).fetchone()
        assert membership == (False,)

        owner = conn.execute(
            """
            SELECT pg_get_userbyid(c.relowner)
            FROM pg_class AS c
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname = 'publication_operation'
            """
        ).fetchone()
        assert owner == ("vimi_migration_owner",)

        ledger_privileges = conn.execute(
            """
            SELECT
                has_table_privilege('vimi_app', 'usage_ledger', 'SELECT'),
                has_table_privilege('vimi_app', 'usage_ledger', 'INSERT'),
                has_table_privilege('vimi_app', 'usage_ledger', 'UPDATE'),
                has_table_privilege('vimi_app', 'usage_ledger', 'DELETE')
            """
        ).fetchone()
        assert ledger_privileges == (True, True, False, False)


def test_rls_fails_closed_isolates_tenants_and_does_not_leak_pool_context() -> None:
    app_dsn, admin_dsn = _database_dsns()
    tenant_a = uuid4()
    tenant_b = uuid4()
    _seed_tenants(admin_dsn, (tenant_a, tenant_b))

    engine = create_engine(app_dsn, pool_size=1, max_overflow=0)
    operation_a = f"rls-a-{uuid4()}"
    operation_b = f"rls-b-{uuid4()}"

    try:
        with Session(engine) as session, tenant_transaction(session, TenantId(tenant_a)):
            session.execute(
                text(
                    """
                    INSERT INTO publication_operation
                        (tenant_id, operation_key, target_id, state)
                    VALUES (:tenant_id, :operation_key, 'target-a', 'REQUESTED')
                    """
                ),
                {"tenant_id": str(tenant_a), "operation_key": operation_a},
            )

        with Session(engine) as session, tenant_transaction(session, TenantId(tenant_b)):
            session.execute(
                text(
                    """
                    INSERT INTO publication_operation
                        (tenant_id, operation_key, target_id, state)
                    VALUES (:tenant_id, :operation_key, 'target-b', 'REQUESTED')
                    """
                ),
                {"tenant_id": str(tenant_b), "operation_key": operation_b},
            )

        with Session(engine) as session, session.begin():
            visible_without_context = session.execute(
                text("SELECT operation_key FROM publication_operation")
            ).scalars().all()
            assert visible_without_context == []

        with Session(engine) as session, tenant_transaction(session, TenantId(tenant_a)):
            visible_a = session.execute(
                text("SELECT operation_key FROM publication_operation")
            ).scalars().all()
            assert visible_a == [operation_a]

        # pool_size=1 forces this transaction to reuse the same pooled connection.
        # The transaction-local GUC from tenant A must have disappeared at commit.
        with Session(engine) as session, session.begin():
            visible_after_reuse = session.execute(
                text("SELECT operation_key FROM publication_operation")
            ).scalars().all()
            assert visible_after_reuse == []

        with Session(engine) as session, tenant_transaction(session, TenantId(tenant_b)):
            visible_b = session.execute(
                text("SELECT operation_key FROM publication_operation")
            ).scalars().all()
            assert visible_b == [operation_b]

        with (
            Session(engine) as session,
            session.begin(),
            pytest.raises(TenantTransactionRequired),
            tenant_transaction(session, TenantId(tenant_a)),
        ):
            pass
    finally:
        engine.dispose()


def test_usage_ledger_is_append_only_for_application_role() -> None:
    app_dsn, admin_dsn = _database_dsns()
    tenant_id = uuid4()
    _seed_tenants(admin_dsn, (tenant_id, uuid4()))
    operation_key = f"ledger-{uuid4()}"
    engine = create_engine(app_dsn)

    try:
        with Session(engine) as session, tenant_transaction(session, TenantId(tenant_id)):
            session.execute(
                text(
                    """
                    INSERT INTO usage_ledger
                        (tenant_id, operation_key, entry_kind, metric, quantity)
                    VALUES (:tenant_id, :operation_key, 'CHARGE', 'publication', 1)
                    """
                ),
                {"tenant_id": str(tenant_id), "operation_key": operation_key},
            )

        with pytest.raises(DBAPIError) as update_error:
            with Session(engine) as session, tenant_transaction(session, TenantId(tenant_id)):
                session.execute(
                    text(
                        """
                        UPDATE usage_ledger
                        SET quantity = 99
                        WHERE operation_key = :operation_key
                        """
                    ),
                    {"operation_key": operation_key},
                )
        assert getattr(update_error.value.orig, "sqlstate", None) == "42501"

        with pytest.raises(DBAPIError) as delete_error:
            with Session(engine) as session, tenant_transaction(session, TenantId(tenant_id)):
                session.execute(
                    text("DELETE FROM usage_ledger WHERE operation_key = :operation_key"),
                    {"operation_key": operation_key},
                )
        assert getattr(delete_error.value.orig, "sqlstate", None) == "42501"

        with Session(engine) as session, tenant_transaction(session, TenantId(tenant_id)):
            persisted = session.execute(
                text(
                    """
                    SELECT entry_kind, metric, quantity
                    FROM usage_ledger
                    WHERE operation_key = :operation_key
                    """
                ),
                {"operation_key": operation_key},
            ).one()
            assert persisted == ("CHARGE", "publication", 1)
    finally:
        engine.dispose()
