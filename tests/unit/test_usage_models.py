from uuid import uuid4

import pytest

from vimi_social.domain.identity import OperationKey, TenantId
from vimi_social.usage.models import ReservationRequest


def test_reservation_quantity_must_be_positive() -> None:
    with pytest.raises(ValueError):
        ReservationRequest(
            tenant_id=TenantId(uuid4()),
            operation_key=OperationKey("operation-1"),
            metric="publication",
            quantity=0,
        )
