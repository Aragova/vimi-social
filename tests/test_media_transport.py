from collections.abc import AsyncIterator, Mapping
from typing import cast

import aiohttp
import pytest

from vimi_social.media.secure_ingest.errors import TransportError
from vimi_social.media.secure_ingest.transport import AiohttpResponseStream


class BrokenContent:
    async def iter_chunked(self, chunk_size: int) -> AsyncIterator[bytes]:
        del chunk_size
        yield b"prefix"
        raise aiohttp.ClientPayloadError("truncated response")


class FakeResponse:
    status = 200
    headers: Mapping[str, str] = {"Content-Type": "video/mp4"}
    content = BrokenContent()

    def release(self) -> None:
        return None


class FakeSession:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_response_body_client_error_is_normalized_to_transport_error() -> None:
    response = cast(aiohttp.ClientResponse, FakeResponse())
    session = cast(aiohttp.ClientSession, FakeSession())
    stream = AiohttpResponseStream(response, session)
    chunks: list[bytes] = []

    with pytest.raises(TransportError, match="response body failed"):
        async for chunk in stream.iter_chunks(16):
            chunks.append(chunk)

    assert chunks == [b"prefix"]
