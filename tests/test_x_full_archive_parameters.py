import httpx
import pytest

from vimi_social.domain.source import ScoutSearchRequest
from vimi_social.source.x_connector import XSourceConnector


def _page(
    post_id: int,
    *,
    next_token: str | None = None,
) -> dict[str, object]:
    media_key = f"7_{post_id}"
    payload: dict[str, object] = {
        "data": [
            {
                "id": str(post_id),
                "text": f"archive video {post_id}",
                "attachments": {"media_keys": [media_key]},
            }
        ],
        "includes": {
            "media": [
                {
                    "media_key": media_key,
                    "type": "video",
                    "preview_image_url": f"https://pbs.twimg.com/{post_id}.jpg",
                    "variants": [
                        {
                            "content_type": "video/mp4",
                            "bit_rate": 256000,
                            "url": f"https://video.twimg.com/{post_id}.mp4",
                        }
                    ],
                }
            ]
        },
    }
    if next_token is not None:
        payload["meta"] = {"next_token": next_token}
    return payload


@pytest.mark.asyncio
async def test_x_full_archive_sets_complete_history_window_and_relevance_order() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_page(1))

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = XSourceConnector("test-token", client=http_client, search_scope="all")

    candidates = await connector.search(
        ScoutSearchRequest(
            intent="night bangkok",
            requested_sources=("x",),
            preferred_languages=("en",),
            max_results=10,
        )
    )

    assert len(candidates) == 1
    assert len(requests) == 1
    request = requests[0]
    assert request.url.path == "/2/tweets/search/all"
    assert request.url.params["start_time"] == "2006-03-21T00:00:00Z"
    assert request.url.params["sort_order"] == "relevancy"
    await http_client.aclose()


@pytest.mark.asyncio
async def test_x_full_archive_continuation_preserves_archive_parameters() -> None:
    requests: list[httpx.Request] = []
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        requests.append(request)
        if calls == 1:
            return httpx.Response(200, json=_page(1, next_token="archive-page-2"))
        return httpx.Response(200, json=_page(2))

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = XSourceConnector("test-token", client=http_client, search_scope="all")

    candidates = await connector.search(
        ScoutSearchRequest(
            intent="night bangkok",
            requested_sources=("x",),
            preferred_languages=("en",),
            max_results=20,
            search_scope="all",
        )
    )

    assert len(candidates) == 2
    assert len(requests) == 2
    for request in requests:
        assert request.url.params["start_time"] == "2006-03-21T00:00:00Z"
        assert request.url.params["sort_order"] == "relevancy"
    assert requests[1].url.params["next_token"] == "archive-page-2"
    await http_client.aclose()


@pytest.mark.asyncio
async def test_x_recent_search_does_not_send_full_archive_parameters() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_page(1))

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = XSourceConnector("test-token", client=http_client, search_scope="recent")

    candidates = await connector.search(
        ScoutSearchRequest(
            intent="night bangkok",
            requested_sources=("x",),
            preferred_languages=("en",),
            max_results=10,
        )
    )

    assert len(candidates) == 1
    assert len(requests) == 1
    request = requests[0]
    assert request.url.path == "/2/tweets/search/recent"
    assert "start_time" not in request.url.params
    assert "sort_order" not in request.url.params
    await http_client.aclose()
