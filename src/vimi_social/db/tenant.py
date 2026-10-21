from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session

from vimi_social.domain.identity import TenantId


class TenantTransactionRequired(RuntimeError):
    pass


@contextmanager
def tenant_transaction(session: Session, tenant_id: TenantId) -> Iterator[Session]:
    """Own the top-level transaction and install transaction-local tenant context."""
    if session.in_transaction():
        raise TenantTransactionRequired(
            "tenant_transaction must own the top-level transaction; nesting is forbidden"
        )

    with session.begin():
        session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id.value)},
        )
        yield session
