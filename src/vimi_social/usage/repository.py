from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from vimi_social.domain.identity import OperationKey
from vimi_social.usage.models import ReservationRequest


class CapacityExceeded(RuntimeError):
    pass


class OperationBindingConflict(RuntimeError):
    pass


class ReservationStateConflict(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ReservationResult:
    reservation_id: str
    joined_existing: bool


class UsageRepository:
    """PostgreSQL-backed commercial usage authority.

    Reservation creation follows the Architecture 1.0 / PoC E ordering:
    establish the unique operation-key reservation first, then reserve capacity.
    A concurrent duplicate blocks on the unique constraint and joins the winner
    instead of incrementing tenant capacity a second time.

    The caller must execute methods inside the tenant-owned transaction.
    """

    def reserve(self, session: Session, request: ReservationRequest) -> ReservationResult:
        params = {
            "tenant_id": str(request.tenant_id.value),
            "operation_key": request.operation_key.value,
            "metric": request.metric,
            "quantity": request.quantity,
        }

        reservation_id = session.execute(
            text(
                """
                INSERT INTO usage_reservation (
                    tenant_id, operation_key, metric, quantity, state
                ) VALUES (
                    :tenant_id, :operation_key, :metric, :quantity, 'RESERVED'
                )
                ON CONFLICT (operation_key) DO NOTHING
                RETURNING id::text
                """
            ),
            params,
        ).scalar_one_or_none()

        if reservation_id is None:
            existing = session.execute(
                text(
                    """
                    SELECT id::text, tenant_id::text, metric, quantity
                    FROM usage_reservation
                    WHERE operation_key = :operation_key
                    FOR SHARE
                    """
                ),
                {"operation_key": request.operation_key.value},
            ).mappings().one_or_none()

            if existing is None:
                raise OperationBindingConflict(
                    "operation_key is unavailable in the current tenant context"
                )

            expected = (
                str(request.tenant_id.value),
                request.metric,
                request.quantity,
            )
            actual = (existing["tenant_id"], existing["metric"], existing["quantity"])
            if actual != expected:
                raise OperationBindingConflict("operation_key is bound to different usage data")
            return ReservationResult(reservation_id=existing["id"], joined_existing=True)

        capacity = session.execute(
            text(
                """
                UPDATE usage_capacity
                SET reserved = reserved + :quantity
                WHERE tenant_id = :tenant_id
                  AND metric = :metric
                  AND reserved + committed + :quantity <= quota
                RETURNING tenant_id
                """
            ),
            params,
        ).first()
        if capacity is None:
            raise CapacityExceeded("insufficient tenant usage capacity")

        return ReservationResult(reservation_id=reservation_id, joined_existing=False)

    def commit(self, session: Session, operation_key: OperationKey) -> bool:
        """Commit one reserved logical operation exactly once.

        Returns True when this call performs the RESERVED -> COMMITTED transition,
        or False when the same operation had already been committed.
        """
        reservation = session.execute(
            text(
                """
                SELECT id::text, tenant_id::text, metric, quantity, state
                FROM usage_reservation
                WHERE operation_key = :operation_key
                FOR UPDATE
                """
            ),
            {"operation_key": operation_key.value},
        ).mappings().one_or_none()
        if reservation is None:
            raise OperationBindingConflict(
                "usage reservation is unavailable in the current tenant context"
            )

        state = reservation["state"]
        if state == "COMMITTED":
            return False
        if state != "RESERVED":
            raise ReservationStateConflict(
                f"cannot commit usage reservation from state {state}"
            )

        capacity = session.execute(
            text(
                """
                UPDATE usage_capacity
                SET reserved = reserved - :quantity,
                    committed = committed + :quantity
                WHERE tenant_id::text = :tenant_id
                  AND metric = :metric
                  AND reserved >= :quantity
                RETURNING tenant_id
                """
            ),
            {
                "tenant_id": reservation["tenant_id"],
                "metric": reservation["metric"],
                "quantity": reservation["quantity"],
            },
        ).first()
        if capacity is None:
            raise ReservationStateConflict("usage capacity counters are inconsistent")

        session.execute(
            text(
                """
                INSERT INTO usage_ledger (
                    tenant_id, operation_key, entry_kind, metric, quantity
                )
                VALUES (
                    CAST(:tenant_id AS uuid),
                    :operation_key,
                    'CHARGE',
                    :metric,
                    :quantity
                )
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "tenant_id": reservation["tenant_id"],
                "operation_key": operation_key.value,
                "metric": reservation["metric"],
                "quantity": reservation["quantity"],
            },
        )

        updated_id = session.execute(
            text(
                """
                UPDATE usage_reservation
                SET state = 'COMMITTED',
                    updated_at = clock_timestamp()
                WHERE id::text = :reservation_id
                  AND state = 'RESERVED'
                RETURNING id::text
                """
            ),
            {"reservation_id": reservation["id"]},
        ).scalar_one_or_none()
        if updated_id is None:
            raise ReservationStateConflict("usage reservation changed during commit")
        return True

    def release(self, session: Session, operation_key: OperationKey) -> bool:
        """Release reserved capacity for work proven not to have started."""
        reservation = session.execute(
            text(
                """
                SELECT id::text, tenant_id::text, metric, quantity, state
                FROM usage_reservation
                WHERE operation_key = :operation_key
                FOR UPDATE
                """
            ),
            {"operation_key": operation_key.value},
        ).mappings().one_or_none()
        if reservation is None:
            raise OperationBindingConflict(
                "usage reservation is unavailable in the current tenant context"
            )

        state = reservation["state"]
        if state in {"RELEASED", "EXPIRED"}:
            return False
        if state != "RESERVED":
            raise ReservationStateConflict(
                f"cannot release usage reservation from state {state}"
            )

        capacity = session.execute(
            text(
                """
                UPDATE usage_capacity
                SET reserved = reserved - :quantity
                WHERE tenant_id::text = :tenant_id
                  AND metric = :metric
                  AND reserved >= :quantity
                RETURNING tenant_id
                """
            ),
            {
                "tenant_id": reservation["tenant_id"],
                "metric": reservation["metric"],
                "quantity": reservation["quantity"],
            },
        ).first()
        if capacity is None:
            raise ReservationStateConflict("usage capacity counters are inconsistent")

        updated_id = session.execute(
            text(
                """
                UPDATE usage_reservation
                SET state = 'RELEASED',
                    updated_at = clock_timestamp()
                WHERE id::text = :reservation_id
                  AND state = 'RESERVED'
                RETURNING id::text
                """
            ),
            {"reservation_id": reservation["id"]},
        ).scalar_one_or_none()
        if updated_id is None:
            raise ReservationStateConflict("usage reservation changed during release")
        return True
