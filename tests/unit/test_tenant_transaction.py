from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from vimi_social.db.tenant import NestedTenantTransactionError, tenant_transaction
from vimi_social.domain.identity import TenantId


def test_tenant_transaction_rejects_existing_transaction() -> None:
    session = Mock(spec=Session)
    session.in_transaction.return_value = True
    with pytest.raises(NestedTenantTransactionError):
        with tenant_transaction(session, TenantId(uuid4())):
            pass
