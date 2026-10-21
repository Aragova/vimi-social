from uuid import uuid4

import pytest

from vimi_social.domain.identity import ActorType, ExecutionContext, OperationKey, TenantId


def test_operation_key_rejects_blank_values() -> None:
    with pytest.raises(ValueError):
        OperationKey("   ")


def test_execution_context_is_immutable() -> None:
    context = ExecutionContext(
        tenant_id=TenantId(uuid4()),
        actor_id="user-1",
        actor_type=ActorType.USER,
        correlation_id="corr-1",
        operation_id="op-1",
        origin="api",
    )
    with pytest.raises(AttributeError):
        context.actor_id = "other"  # type: ignore[misc]
