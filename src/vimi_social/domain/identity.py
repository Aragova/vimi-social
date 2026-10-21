from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


@dataclass(frozen=True, slots=True)
class TenantId:
    value: UUID


@dataclass(frozen=True, slots=True)
class OperationKey:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("operation_key cannot be empty")


class ActorType(StrEnum):
    USER = "USER"
    SYSTEM = "SYSTEM"
    SUPPORT = "SUPPORT"


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    tenant_id: TenantId
    actor_id: str
    actor_type: ActorType
    correlation_id: str
    operation_id: str
    origin: str
