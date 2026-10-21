import httpx
import pytest

from vimi_social.source.connectors import SourceConnectorUnavailable
from vimi_social.source.models import MediaKind, SourcePlatform, SourceSearchRequest
from vimi_social.source.x import XRecentSearchConnector


@pytest.mark.asyncio
async def test_x_connector_returns_normalized_video_candidate() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("Authorization")
        captured["query"] = request.url.params.get("query")
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "123",
                        "text": "sample post",
                        "author_id": "u1",
                        "created_at": "2026-10-21T18:00:00Z",
                        "possibly_sensitive": True,
                        "attachments": {"media_keys": ["m1"]},
                    }
                ],
                "includes": {
                    "users": [{"id": "u1", "username": "creator"}],
                    "media": [{"media_key": "m1", "type": "video"}],
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = XRecentSearchConnector("secret-token", client=client)
    candidates = await connector.search(
        SourceSearchRequest(SourcePlatform.X, "gay fitness", 10)
    )

    assert captured["authorization"] == "Bearer secret-token"
    assert captured["query"] == "(gay fitness) has:videos -is:retweet"
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.external_id == "123"
    assert candidate.canonical_url == "https://x.com/creator/status/123"
    assert candidate.possibly_sensitive is True
    assert candidate.media_kind is MediaKind.VIDEO
    assert candidate.media_refs == ("m1",)
    await connector.aclose()


@pytest.mark.asyncio
async def test_x_connector_error_is_sanitized() -> None:
    token = "super-secret-x-token"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(402, text="payment required")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = XRecentSearchConnector(token, client=client)

    with pytest.raises(SourceConnectorUnavailable) as error:
        await connector.search(SourceSearchRequest(SourcePlatform.X, "test", 10))

    rendered = str(error.value)
    assert token not in rendered
    assert "api.x.com" not in rendered
    assert "402" in rendered
    await connector.aclose()
