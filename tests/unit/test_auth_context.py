from fastapi import HTTPException
import pytest

from vimi_social.auth.context import require_execution_context


@pytest.mark.asyncio
async def test_identity_boundary_fails_closed_without_bearer_token() -> None:
    with pytest.raises(HTTPException) as error:
        await require_execution_context(None)
    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_identity_boundary_does_not_trust_bootstrap_tenant_headers() -> None:
    with pytest.raises(HTTPException) as error:
        await require_execution_context("Bearer not-yet-wired")
    assert error.value.status_code == 503
