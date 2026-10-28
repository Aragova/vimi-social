import json
import os
from pathlib import Path

import httpx
import pytest

from vimi_social.source.x_oauth_refresh import XOAuthTokenManager


@pytest.mark.asyncio
async def test_oauth_refresh_rotates_state_and_reuses_new_access_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url == "https://api.x.com/2/oauth2/token"
        assert request.headers["Authorization"].startswith("Basic ")
        body = request.content.decode()
        assert "grant_type=refresh_token" in body
        assert "refresh_token=old-refresh" in body
        return httpx.Response(
            200,
            json={
                "access_token": "fresh-access",
                "refresh_token": "rotated-refresh",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    state_path = tmp_path / "oauth" / "refresh-token"
    monkeypatch.setenv("VIMI_DEST_X_PRIMARY_TOKEN", "old-access")
    manager = XOAuthTokenManager(
        access_token="old-access",
        refresh_token="old-refresh",
        client_id="client-id",
        client_secret="client-secret",
        state_path=state_path,
        client=client,
    )

    refreshed = await manager.refresh_after_rejection("old-access")

    assert refreshed == "fresh-access"
    assert manager.current_access_token() == "fresh-access"
    state = json.loads(state_path.read_text())
    assert state["refresh_token"] == "rotated-refresh"
    assert isinstance(state["authorization_id"], str)
    assert state["authorization_id"]
    assert state_path.stat().st_mode & 0o777 == 0o600
    assert os.environ["VIMI_DEST_X_PRIMARY_TOKEN"] == "fresh-access"

    reused = await manager.refresh_after_rejection("old-access")

    assert reused == "fresh-access"
    assert calls == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_oauth_refresh_ignores_persisted_state_from_previous_authorization(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "oauth" / "refresh-token"

    def old_handler(request: httpx.Request) -> httpx.Response:
        assert "refresh_token=old-refresh" in request.content.decode()
        return httpx.Response(
            200,
            json={
                "access_token": "old-fresh-access",
                "refresh_token": "old-rotated-refresh",
            },
        )

    old_client = httpx.AsyncClient(transport=httpx.MockTransport(old_handler))
    old_manager = XOAuthTokenManager(
        access_token="old-access",
        refresh_token="old-refresh",
        client_id="client-id",
        client_secret="client-secret",
        state_path=state_path,
        client=old_client,
    )
    await old_manager.refresh_now()
    await old_client.aclose()

    seen_refresh_tokens: list[str] = []

    def new_handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        seen_refresh_tokens.append(body)
        return httpx.Response(
            200,
            json={
                "access_token": "new-fresh-access",
                "refresh_token": "new-rotated-refresh",
            },
        )

    new_client = httpx.AsyncClient(transport=httpx.MockTransport(new_handler))
    new_manager = XOAuthTokenManager(
        access_token="new-access",
        refresh_token="new-refresh",
        client_id="client-id",
        client_secret="client-secret",
        state_path=state_path,
        client=new_client,
    )

    refreshed = await new_manager.refresh_now()

    assert refreshed == "new-fresh-access"
    assert len(seen_refresh_tokens) == 1
    assert "refresh_token=new-refresh" in seen_refresh_tokens[0]
    assert "old-rotated-refresh" not in seen_refresh_tokens[0]
    state = json.loads(state_path.read_text())
    assert state["refresh_token"] == "new-rotated-refresh"
    await new_client.aclose()


def test_oauth_refresh_manager_requires_complete_refresh_credentials(tmp_path: Path) -> None:
    manager = XOAuthTokenManager(
        access_token="access",
        refresh_token="",
        client_id="client-id",
        client_secret="client-secret",
        state_path=tmp_path / "refresh-token",
    )

    assert manager.enabled is False
