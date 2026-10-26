import httpx
import pytest

from vimi_social.domain.source import ScoutSearchRequest
from vimi_social.source.x_connector import XSourceConnector


def _page(start: int, count: int, *, next_token: str | None = None) -> dict[str, object]:
    data: list[dict[str, object]] = []
    media: list[dict[str, object]] = []
    for index in range(start, start + count):
        media_key = f"7_{index}"
        data.append(
            {
                "id": str(index),
                "text": f"gay twink video {index}",
                "attachments": {"media_keys": [media_key]},
            }
        )
        media.append(
            {
                "media_key": media_key,
                "type": "video",
                "preview_image_url": f"https://pbs.twimg.com/{index}.jpg",
                "variants": [
                    {
                        "content_type": "video/mp4",
                        "bit_rate": 256000,
                        "url": f"https://video.twimg.com/{index}.mp4",
                    }
                ],
            }
        )
    payload: dict[str, object] = {"data": data, "includes": {"media": media}}
    if next_token is not None:
        payload["meta"] = {"next_token": next_token}
    return payload


@pytest.mark.asyncio
async def test_x_recent_search_follows_next_token_until_requested_pool_is_filled() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        token = request.url.params.get("next_token")
        if token is None:
            return httpx.Response(200, json=_page(1, 10, next_token="page-2"))
        assert token == "page-2"
        return httpx.Response(200, json=_page(11, 10))

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = XSourceConnector("test-token", client=http_client)

    candidates = await connector.search(
        ScoutSearchRequest(
            intent="gay twink porno",
            requested_sources=("x",),
            preferred_languages=("en",),
            max_results=15,
        )
    )

    assert len(candidates) == 15
    assert [candidate.source_id for candidate in candidates] == [str(i) for i in range(1, 16)]
    assert len(requests) == 2
    assert requests[1].url.params["next_token"] == "page-2"
    await http_client.aclose()


@pytest.mark.asyncio
async def test_x_recent_search_stops_on_repeated_pagination_token() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_page(calls * 10, 10, next_token="same-token"))

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = XSourceConnector("test-token", client=http_client)

    candidates = await connector.search(
        ScoutSearchRequest(
            intent="video",
            requested_sources=("x",),
            preferred_languages=("en",),
            max_results=50,
        )
    )

    assert len(candidates) == 20
    assert calls == 2
    await http_client.aclose()
