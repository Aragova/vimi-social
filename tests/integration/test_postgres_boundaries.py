import os
from uuid import UUID, uuid4

import psycopg
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from vimi_social.db.tenant import tenant_transaction
from vimi_social.domain.identity import OperationKey, TenantId
from vimi_social.usage.models import ReservationRequest
from vimi_social.usage.repository import OperationBindingConflict, UsageRepository


def _require_dsn(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        pytest.skip(f"{name} is not configured")
    return value


def _seed() -> tuple[UUID, UUID]:
    admin_dsn = _require_dsn("VIMI_TEST_ADMIN_DSN")
    tenant_a = uuid4()
    tenant_b = uuid4()
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenant (id, slug) VALUES (%s, %s), (%s, %s)",
                (tenant_a, f"a-{tenant_a}", tenant_b, f"b-{tenant_b}"),
            )
            cur.execute(
                """
                INSERT INTO publication_operation
                    (tenant_id, operation_key, target_id, state)
                VALUES (%s, %s, 'target-a', 'REQUESTED'),
                       (%s, %s, 'target-b', 'REQUESTED')
                """,
                (tenant_a, f"pub-a-{tenant_a}", tenant_b, f"pub-b-{tenant_b}"),
            )
            cur.execute(
                """
                INSERT INTO usage_capacity (tenant_id, metric, quota)
                VALUES (%s, 'publication', 5), (%s, 'publication', 5)
                """,
                (tenant_a, tenant_b),
            )
    return tenant_a, tenant_b


def _cleanup(*tenant_ids: UUID) -> None:
    admin_dsn = _require_dsn("VIMI_TEST_ADMIN_DSN")
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM usage_ledger WHERE tenant_id = ANY(%s)", (list(tenant_ids),))
            cur.execute(
                "DELETE FROM usage_reservation WHERE tenant_id = ANY(%s)",
                (list(tenant_ids),),
            )
            cur.execute("DELETE FROM usage_capacity WHERE tenant_id = ANY(%s)", (list(tenant_ids),))
            cur.execute(
                "DELETE FROM publication_operation WHERE tenant_id = ANY(%s)",
                (list(tenant_ids),),
            )
            cur.execute("DELETE FROM tenant WHERE id = ANY(%s)", (list(tenant_ids),))


def test_rls_blocks_cross_tenant_rows_without_where_clause() -> None:
    tenant_a, tenant_b = _seed()
    engine = create_engine(_require_dsn("VIMI_DATABASE_DSN"), pool_pre_ping=True)
    try:
        with Session(engine) as session:
            with tenant_transaction(session, TenantId(tenant_a)):
                targets = session.execute(
                    text("SELECT target_id FROM publication_operation ORDER BY target_id")
                ).scalars().all()
                assert targets == ["target-a"]

            with tenant_transaction(session, TenantId(tenant_b)):
                targets = session.execute(
                    text("SELECT target_id FROM publication_operation ORDER BY target_id")
                ).scalars().all()
                assert targets == ["target-b"]
    finally:
        engine.dispose()
        _cleanup(tenant_a, tenant_b)


def test_usage_reservation_is_idempotent_and_operation_binding_is_immutable() -> None:
    tenant_a, tenant_b = _seed()
    engine = create_engine(_require_dsn("VIMI_DATABASE_DSN"), pool_pre_ping=True)
    repo = UsageRepository()
    key = OperationKey(f"usage-{uuid4()}")
    try:
        with Session(engine) as session:
            with tenant_transaction(session, TenantId(tenant_a)):
                request = ReservationRequest(TenantId(tenant_a), key, "publication", 2)
                first = repo.reserve(session, request)
                second = repo.reserve(session, request)
                assert second.reservation_id == first.reservation_id
                assert second.joined_existing is True
                reserved = session.execute(
                    text(
                        "SELECT reserved FROM usage_capacity "
                        "WHERE tenant_id = :tenant_id AND metric = 'publication'"
                    ),
                    {"tenant_id": str(tenant_a)},
                ).scalar_one()
                assert reserved == 2

        with Session(engine) as session:
            with tenant_transaction(session, TenantId(tenant_b)):
                with pytest.raises(OperationBindingConflict):
                    repo.reserve(
                        session,
                        ReservationRequest(TenantId(tenant_b), key, "publication", 2),
                    )
    finally:
        engine.dispose()
        _cleanup(tenant_a, tenant_b)
