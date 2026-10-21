from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from vimi_social.usage.models import ReservationRequest


class CapacityExceeded(RuntimeError):
    pass


class OperationBindingConflict(RuntimeError):
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

    The caller must execute this method inside the tenant-owned transaction so a
    CapacityExceeded exception rolls back the newly inserted reservation row.
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
                # Fail closed without revealing whether an RLS-hidden row caused the
                # global operation-key conflict.
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
