from dataclasses import dataclass
from uuid import UUID

from vimi_social.domain.identity import OperationKey, TenantId


@dataclass(frozen=True, slots=True)
class ReservationRequest:
    tenant_id: TenantId
    operation_key: OperationKey
    metric: str
    quantity: int

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")


@dataclass(frozen=True, slots=True)
class ReservationResult:
    reservation_id: UUID
    joined_existing: bool
