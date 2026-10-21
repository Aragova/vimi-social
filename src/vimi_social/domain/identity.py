from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class TenantId:
    value: UUID

    @classmethod
    def parse(cls, raw: str) -> "TenantId":
        return cls(UUID(raw))


@dataclass(frozen=True, slots=True)
class OperationKey:
    """Stable logical identity for one externally visible operation."""

    value: str

    def __post_init__(self) -> None:
        normalized = self.value.strip()
        if not normalized:
            raise ValueError("operation_key must not be empty")
        if len(normalized) > 200:
            raise ValueError("operation_key exceeds 200 characters")
        object.__setattr__(self, "value", normalized)
