import httpx
import pytest

from vimi_social.source.x_user_context import (
    XUserContextClient,
    XUserContextReauthRequired,
    XUserContextUnavailable,
)


@pytest.mark.asyncio
async def test_user_context_collects_supported_interest_sources() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        payloads: dict[str, object] = {
            "/2/users/me": {"data": {"id": "me", "username": "tester"}},
            "/2/users/me/following": {
                "data": [
                    {
                        "id": "author-1",
                        "username": "creator",
                        "name": "Creator",
                        "description": "twink long videos",
                    }
                ]
            },
            "/2/users/me/liked_tweets": {
                "data": [
                    {"id": "like-1", "text": "liked #twink", "author_id": "author-2"}
                ]
            },
            "/2/users/me/bookmarks": {
                "data": [
                    {
                        "id": "bookmark-1",
                        "text": "saved long form #twink",
                        "author_id": "author-3",
                    }
                ]
            },
            "/2/users/me/followed_lists": {
                "data": [
                    {
                        "id": "list-1",
                        "name": "Twink video",
                        "description": "long-form creators",
                    }
                ]
            },
            "/2/users/me/list_memberships": {
                "data": [
                    {
                        "id": "list-1",
                        "name": "Twink video",
                        "description": "long-form creators",
                    }
                ]
            },
            "/2/lists/list-1/tweets": {
                "data": [
                    {
                        "id": "list-post-1",
                        "text": "list video #twink",
                        "author_id": "author-4",
                    }
                ]
            },
        }
        payload = payloads.get(path)
        if payload is None:
            return httpx.Response(404, json={"error": "missing"})
        return httpx.Response(200, json=payload)

    async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = XUserContextClient(client=async_client, list_sample_limit=1)
    try:
        snapshot = await client.fetch_snapshot("user-token")
    finally:
        await async_client.aclose()

    assert snapshot.user_id == "me"
    assert [item.id for item in snapshot.following] == ["author-1"]
    assert [item.id for item in snapshot.liked_posts] == ["like-1"]
    assert [item.id for item in snapshot.bookmarked_posts] == ["bookmark-1"]
    assert [item.id for item in snapshot.lists] == ["list-1"]
    assert [item.id for item in snapshot.list_posts] == ["list-post-1"]
    assert snapshot.unavailable_sources == ()


@pytest.mark.asyncio
async def test_home_timeline_returns_video_candidates_and_charges_posts_read() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/2/users/me/timelines/reverse_chronological"
        assert request.url.params["max_results"] == "50"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "video-post",
                        "text": "long form creator video",
                        "author_id": "author-1",
                        "created_at": "2026-10-27T12:00:00Z",
                        "lang": "en",
                        "attachments": {"media_keys": ["media-1"]},
                        "public_metrics": {"like_count": 42},
                    },
                    {
                        "id": "text-post",
                        "text": "no video here",
                        "author_id": "author-2",
                    },
                ],
                "includes": {
                    "media": [
                        {
                            "media_key": "media-1",
                            "type": "video",
                            "duration_ms": 600_000,
                            "width": 1920,
                            "height": 1080,
                            "preview_image_url": "https://img.example/preview.jpg",
                            "variants": [
                                {
                                    "content_type": "video/mp4",
                                    "bit_rate": 256_000,
                                    "url": "https://video.example/low.mp4",
                                },
                                {
                                    "content_type": "video/mp4",
                                    "bit_rate": 2_000_000,
                                    "url": "https://video.example/high.mp4",
                                },
                            ],
                        }
                    ]
                },
            },
        )

    async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = XUserContextClient(client=async_client)
    try:
        candidates, posts_read = await client.fetch_home_timeline_candidates(
            "user-token",
            "me",
            max_results=50,
        )
    finally:
        await async_client.aclose()

    assert posts_read == 2
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source_id == "video-post"
    assert candidate.duration_ms == 600_000
    assert candidate.engagement["like_count"] == 42
    assert candidate.connector_metadata["x_candidate_origin"] == "home_timeline"
    assert (
        candidate.connector_metadata["acquisition_url"]
        == "https://video.example/high.mp4"
    )


@pytest.mark.asyncio
async def test_optional_scope_failure_does_not_abort_whole_profile() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/2/users/me":
            return httpx.Response(200, json={"data": {"id": "me"}})
        if request.url.path == "/2/users/me/bookmarks":
            return httpx.Response(403, json={"error": "scope"})
        return httpx.Response(200, json={"data": []})

    async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = XUserContextClient(client=async_client)
    try:
        snapshot = await client.fetch_snapshot("user-token")
    finally:
        await async_client.aclose()

    assert snapshot.bookmarked_posts == ()
    assert "bookmarks" in snapshot.unavailable_sources


@pytest.mark.asyncio
async def test_transient_optional_source_failure_aborts_refresh() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/2/users/me":
            return httpx.Response(200, json={"data": {"id": "me"}})
        if request.url.path == "/2/users/me/liked_tweets":
            return httpx.Response(429, json={"error": "rate-limited"})
        return httpx.Response(200, json={"data": []})

    async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = XUserContextClient(client=async_client)
    try:
        with pytest.raises(XUserContextUnavailable):
            await client.fetch_snapshot("user-token")
    finally:
        await async_client.aclose()


@pytest.mark.asyncio
async def test_users_me_unauthorized_requires_reauthentication() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(401, json={"error": "expired"})

    async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = XUserContextClient(client=async_client)
    try:
        with pytest.raises(XUserContextReauthRequired):
            await client.fetch_snapshot("expired-token")
    finally:
        await async_client.aclose()
