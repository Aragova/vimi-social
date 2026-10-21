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
    """PostgreSQL-backed commercial usage authority."""

    def reserve(self, session: Session, request: ReservationRequest) -> ReservationResult:
        existing = session.execute(
            text(
                """
                SELECT id::text, tenant_id::text, metric, quantity
                FROM usage_reservation
                WHERE operation_key = :operation_key
                FOR UPDATE
                """
            ),
            {"operation_key": request.operation_key.value},
        ).mappings().one_or_none()

        if existing is not None:
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
            {
                "quantity": request.quantity,
                "tenant_id": str(request.tenant_id.value),
                "metric": request.metric,
            },
        ).first()
        if capacity is None:
            raise CapacityExceeded("insufficient tenant usage capacity")

        reservation_id = session.execute(
            text(
                """
                INSERT INTO usage_reservation (
                    tenant_id, operation_key, metric, quantity, state
                ) VALUES (
                    :tenant_id, :operation_key, :metric, :quantity, 'RESERVED'
                )
                RETURNING id::text
                """
            ),
            {
                "tenant_id": str(request.tenant_id.value),
                "operation_key": request.operation_key.value,
                "metric": request.metric,
                "quantity": request.quantity,
            },
        ).scalar_one()
        return ReservationResult(reservation_id=reservation_id, joined_existing=False)
