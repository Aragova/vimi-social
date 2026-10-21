from uuid import uuid4

import pytest

from vimi_social.domain.identity import OperationKey, TenantId
from vimi_social.domain.publication import PublicationCommand


def test_publication_command_requires_positive_quantity() -> None:
    with pytest.raises(ValueError, match="quantity must be positive"):
        PublicationCommand(
            tenant_id=TenantId(uuid4()),
            operation_key=OperationKey("op-1"),
            target_id="target-1",
            metric="publication",
            quantity=0,
        )
