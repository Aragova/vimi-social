from uuid import uuid4

import pytest

from vimi_social.domain.identity import OperationKey, TenantId
from vimi_social.usage.models import ReservationRequest


def test_reservation_request_requires_positive_quantity() -> None:
    with pytest.raises(ValueError, match="quantity must be positive"):
        ReservationRequest(
            tenant_id=TenantId(uuid4()),
            operation_key=OperationKey("op-1"),
            metric="publication",
            quantity=0,
        )
