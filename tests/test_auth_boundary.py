import pytest
from fastapi import HTTPException

from vimi_social.auth.context import require_execution_context


def test_execution_context_fails_closed_until_trusted_resolver_is_wired() -> None:
    with pytest.raises(HTTPException) as captured:
        require_execution_context()
    assert captured.value.status_code == 503
    assert captured.value.detail == "trusted execution-context resolver is not configured"
