from dataclasses import dataclass
from enum import StrEnum

from vimi_social.domain.identity import OperationKey, TenantId


class ReservationState(StrEnum):
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True, slots=True)
class ReservationRequest:
    tenant_id: TenantId
    operation_key: OperationKey
    metric: str
    quantity: int

    def __post_init__(self) -> None:
        if not self.metric.strip():
            raise ValueError("metric must not be empty")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
