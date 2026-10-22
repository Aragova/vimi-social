from pathlib import Path

import httpx
import pytest

from vimi_social.domain.publication import ProviderMutationKind
from vimi_social.publication.x_adapter import XDestinationAdapter


@pytest.mark.asyncio
async def test_x_destination_adapter_uses_v2_chunked_upload_then_creates_post(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/2/media/upload/initialize":
            return httpx.Response(200, json={"data": {"id": "media-1"}})
        if request.url.path == "/2/media/upload/media-1/append":
            return httpx.Response(204)
        if request.url.path == "/2/media/upload/media-1/finalize":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "id": "media-1",
                        "processing_info": {"state": "succeeded"},
                    }
                },
            )
        if request.url.path == "/2/tweets":
            return httpx.Response(201, json={"data": {"id": "post-1"}})
        raise AssertionError(f"unexpected X API request: {request.method} {request.url}")

    checkpointed: list[str] = []

    async def checkpoint(media_id: str) -> bool:
        checkpointed.append(media_id)
        return True

    video = tmp_path / "video.mp4"
    video.write_bytes(b"video-bytes")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = XDestinationAdapter(client=client)

    result = await adapter.publish_video(
        access_token="user-token",
        video_path=video,
        caption="hello",
        checkpoint_media=checkpoint,
    )

    assert result.kind is ProviderMutationKind.CONFIRMED
    assert result.remote_media_id == "media-1"
    assert result.remote_post_id == "post-1"
    assert checkpointed == ["media-1"]
    assert calls == [
        ("POST", "/2/media/upload/initialize"),
        ("POST", "/2/media/upload/media-1/append"),
        ("POST", "/2/media/upload/media-1/finalize"),
        ("POST", "/2/tweets"),
    ]
    await client.aclose()


@pytest.mark.asyncio
async def test_x_destination_adapter_marks_create_transport_failure_unknown(
    tmp_path: Path,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/2/media/upload/initialize":
            return httpx.Response(200, json={"data": {"id": "media-2"}})
        if request.url.path == "/2/media/upload/media-2/append":
            return httpx.Response(204)
        if request.url.path == "/2/media/upload/media-2/finalize":
            return httpx.Response(200, json={"data": {"id": "media-2"}})
        if request.url.path == "/2/tweets":
            raise httpx.ReadTimeout("ambiguous create timeout", request=request)
        raise AssertionError(f"unexpected X API request: {request.method} {request.url}")

    async def checkpoint(media_id: str) -> bool:
        return media_id == "media-2"

    video = tmp_path / "video.mp4"
    video.write_bytes(b"video-bytes")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = XDestinationAdapter(client=client)

    result = await adapter.publish_video(
        access_token="user-token",
        video_path=video,
        caption="hello",
        checkpoint_media=checkpoint,
    )

    assert result.kind is ProviderMutationKind.UNKNOWN
    assert result.remote_media_id == "media-2"
    assert result.remote_post_id is None
    assert result.failure_code == "X_PUBLICATION_TRANSPORT_AMBIGUOUS"
    await client.aclose()
