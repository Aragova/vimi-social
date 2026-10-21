from typing import Annotated

from fastapi import Header, HTTPException, status

from vimi_social.domain.identity import ExecutionContext


async def require_execution_context(
    authorization: Annotated[str | None, Header()] = None,
) -> ExecutionContext:
    """Production boundary for authenticated tenant execution context.

    Architecture 1.0 does not allow callers to choose an authoritative tenant ID.
    The managed IdP + membership resolver will create ``ExecutionContext`` here.
    Until that integration exists, protected endpoints fail closed instead of trusting
    an ``X-Tenant-Id`` style bootstrap header.
    """
    if not authorization:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")

    raise HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "managed identity resolver is not configured yet",
    )
