from dataclasses import dataclass
from enum import StrEnum

from vimi_social.domain.identity import OperationKey, TenantId


class PublicationState(StrEnum):
    REQUESTED = "REQUESTED"
    RESERVED = "RESERVED"
    DISPATCHING = "DISPATCHING"
    PROVIDER_ACCEPTED = "PROVIDER_ACCEPTED"
    UNKNOWN = "UNKNOWN"
    CONFIRMED = "CONFIRMED"
    FAILED_SAFE = "FAILED_SAFE"
    FAILED_PERMANENT = "FAILED_PERMANENT"


@dataclass(frozen=True, slots=True)
class PublicationCommand:
    tenant_id: TenantId
    operation_key: OperationKey
    target_id: str
    metric: str
    quantity: int = 1

    def __post_init__(self) -> None:
        if not self.target_id.strip():
            raise ValueError("target_id must not be empty")
        if not self.metric.strip():
            raise ValueError("metric must not be empty")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
