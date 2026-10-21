from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from vimi_social.usage.models import ReservationRequest, ReservationResult


class UsageCapacityExceeded(RuntimeError):
    pass


class OperationBindingConflict(RuntimeError):
    pass


class UsageRepository:
    def reserve(self, session: Session, request: ReservationRequest) -> ReservationResult:
        binding_matches = session.execute(
            text("SELECT claim_operation_key(:tenant_id, :operation_key)"),
            {
                "tenant_id": str(request.tenant_id.value),
                "operation_key": request.operation_key.value,
            },
        ).scalar_one()
        if not binding_matches:
            raise OperationBindingConflict("operation_key is bound to a different tenant")

        existing = session.execute(
            text(
                """
                SELECT id, tenant_id, metric, quantity
                FROM usage_reservation
                WHERE operation_key = :operation_key
                FOR UPDATE
                """
            ),
            {"operation_key": request.operation_key.value},
        ).mappings().one_or_none()
        if existing is not None:
            if (
                existing["tenant_id"] != request.tenant_id.value
                or existing["metric"] != request.metric
                or existing["quantity"] != request.quantity
            ):
                raise OperationBindingConflict("operation_key already has a different binding")
            return ReservationResult(UUID(str(existing["id"])), joined_existing=True)

        capacity_updated = session.execute(
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
                "tenant_id": str(request.tenant_id.value),
                "metric": request.metric,
                "quantity": request.quantity,
            },
        ).scalar_one_or_none()
        if capacity_updated is None:
            raise UsageCapacityExceeded("tenant usage quota is exhausted")

        reservation_id = uuid4()
        session.execute(
            text(
                """
                INSERT INTO usage_reservation (
                    id, tenant_id, operation_key, metric, quantity, state
                ) VALUES (
                    :id, :tenant_id, :operation_key, :metric, :quantity, 'RESERVED'
                )
                """
            ),
            {
                "id": str(reservation_id),
                "tenant_id": str(request.tenant_id.value),
                "operation_key": request.operation_key.value,
                "metric": request.metric,
                "quantity": request.quantity,
            },
        )
        return ReservationResult(reservation_id, joined_existing=False)
