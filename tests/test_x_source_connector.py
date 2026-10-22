import httpx
import pytest

from vimi_social.domain.source import AdultClassification, ScoutSearchRequest
from vimi_social.source.connectors import SourceConnectorRateLimited
from vimi_social.source.x_connector import XSourceConnector


@pytest.mark.asyncio
async def test_x_recent_search_normalizes_video_candidate_without_assuming_rights() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/2/tweets/search/recent"
        assert request.headers["Authorization"] == "Bearer test-token"
        assert "has:videos" in request.url.params["query"]
        assert request.url.params["max_results"] == "10"
        assert "variants" in request.url.params["media.fields"]
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "1234567890",
                        "text": "Fresh training clip #fitness",
                        "author_id": "42",
                        "created_at": "2026-10-21T12:00:00.000Z",
                        "lang": "en",
                        "possibly_sensitive": True,
                        "attachments": {"media_keys": ["7_99"]},
                        "public_metrics": {
                            "like_count": 100,
                            "reply_count": 4,
                            "retweet_count": 12,
                        },
                    }
                ],
                "includes": {
                    "media": [
                        {
                            "media_key": "7_99",
                            "type": "video",
                            "duration_ms": 15000,
                            "width": 1080,
                            "height": 1920,
                            "preview_image_url": "https://pbs.twimg.com/preview.jpg",
                            "variants": [
                                {
                                    "content_type": "application/x-mpegURL",
                                    "url": "https://video.twimg.com/master.m3u8",
                                },
                                {
                                    "content_type": "video/mp4",
                                    "bit_rate": 256000,
                                    "url": "https://video.twimg.com/low.mp4",
                                },
                                {
                                    "content_type": "video/mp4",
                                    "bit_rate": 2176000,
                                    "url": "https://video.twimg.com/high.mp4",
                                },
                            ],
                        }
                    ]
                },
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = XSourceConnector("test-token", client=http_client)

    candidates = await connector.search(
        ScoutSearchRequest(
            intent="fitness motivation",
            requested_sources=("x",),
            preferred_languages=("en",),
        )
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source == "x"
    assert candidate.source_id == "1234567890"
    assert candidate.source_url == "https://x.com/i/web/status/1234567890"
    assert candidate.media_type == "video"
    assert candidate.duration_ms == 15000
    assert candidate.engagement["like_count"] == 100
    assert candidate.adult_classification is AdultClassification.POSSIBLY_SENSITIVE
    assert candidate.provenance_hint == "PUBLIC_X_POST_REUSE_RIGHTS_NOT_ESTABLISHED"
    assert candidate.availability == "DISCOVERED_MEDIA_REFERENCE_AVAILABLE"
    assert candidate.connector_metadata["acquisition_url"] == "https://video.twimg.com/high.mp4"
    assert candidate.connector_metadata["acquisition_reference"] == "OFFICIAL_X_API_VIDEO_VARIANT"
    await http_client.aclose()


@pytest.mark.asyncio
async def test_x_recent_search_selects_video_when_photo_is_first_attachment() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "mixed-attachments",
                        "text": "Video post with a leading photo attachment",
                        "attachments": {"media_keys": ["3_photo", "7_video"]},
                    }
                ],
                "includes": {
                    "media": [
                        {
                            "media_key": "3_photo",
                            "type": "photo",
                            "width": 1200,
                            "height": 800,
                        },
                        {
                            "media_key": "7_video",
                            "type": "video",
                            "duration_ms": 23000,
                            "width": 1080,
                            "height": 1920,
                            "preview_image_url": "https://pbs.twimg.com/video-preview.jpg",
                            "variants": [
                                {
                                    "content_type": "video/mp4",
                                    "bit_rate": 832000,
                                    "url": "https://video.twimg.com/video.mp4",
                                }
                            ],
                        },
                    ]
                },
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = XSourceConnector("test-token", client=http_client)

    candidates = await connector.search(
        ScoutSearchRequest(
            intent="fitness",
            requested_sources=("x",),
            preferred_languages=(),
        )
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.media_type == "video"
    assert candidate.duration_ms == 23000
    assert candidate.connector_metadata["media_key"] == "7_video"
    assert candidate.connector_metadata["acquisition_url"] == "https://video.twimg.com/video.mp4"
    await http_client.aclose()


@pytest.mark.asyncio
async def test_x_rate_limit_is_typed_and_preserves_retry_hint() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "23"})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = XSourceConnector("test-token", client=http_client)

    with pytest.raises(SourceConnectorRateLimited) as error:
        await connector.search(
            ScoutSearchRequest(
                intent="fitness",
                requested_sources=("x",),
                preferred_languages=("en",),
            )
        )

    assert error.value.retry_after_seconds == 23
    await http_client.aclose()
