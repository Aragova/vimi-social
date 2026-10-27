import httpx
import pytest

from vimi_social.domain.source import ScoutSearchRequest
from vimi_social.source.x_connector import XSourceConnector


@pytest.mark.asyncio
async def test_x_recall_variants_are_joined_with_or_not_implicit_and() -> None:
    seen_queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_queries.append(request.url.params["query"])
        return httpx.Response(200, json={"data": [], "includes": {"media": []}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = XSourceConnector("test-token", client=client, search_scope="all")

    await connector.search(
        ScoutSearchRequest(
            intent="Гей порно твинк молодые",
            requested_sources=("x",),
            preferred_languages=(),
            query_variants=("Gay", "porn", "twink", "young"),
            max_results=10,
            search_scope="all",
        )
    )

    assert seen_queries == [
        "((Gay) OR (porn) OR (twink) OR (young)) has:videos -is:retweet"
    ]
    await client.aclose()
