from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from vimi_social.media.secure_ingest.addressing import DestinationPolicy
from vimi_social.media.secure_ingest.errors import (
    ContentValidationError,
    DownloadLimitError,
    RedirectPolicyError,
    UnsafeAddressError,
)
from vimi_social.media.secure_ingest.fetcher import SecureMediaFetcher
from vimi_social.media.secure_ingest.models import FetchLimits, FetchTimeouts, ResolvedTarget

MP4_BYTES = b"\x00\x00\x00\x18ftypisom" + b"safe-video-payload"


@dataclass
class FakeResolver:
    answers: Mapping[str, Sequence[str]]
    calls: list[tuple[str, int]] = field(
        default_factory=lambda: list[tuple[str, int]]()
    )

    async def resolve(self, host: str, port: int) -> Sequence[str]:
        self.calls.append((host, port))
        return self.answers.get(host, ())


@dataclass
class ScriptedResponse:
    status: int
    headers: Mapping[str, str]
    chunks: Sequence[bytes] = ()
    closed: bool = False

    async def iter_chunks(self, chunk_size: int) -> AsyncIterator[bytes]:
        del chunk_size
        for chunk in self.chunks:
            yield chunk

    async def close(self) -> None:
        self.closed = True


@dataclass
class ScriptedTransport:
    responses: dict[str, list[ScriptedResponse]]
    targets: list[ResolvedTarget] = field(default_factory=lambda: list[ResolvedTarget]())

    async def open(
        self,
        target: ResolvedTarget,
        *,
        timeouts: FetchTimeouts,
    ) -> ScriptedResponse:
        del timeouts
        self.targets.append(target)
        queue = self.responses.get(target.url)
        if not queue:
            raise AssertionError(f"no scripted response for {target.url}")
        return queue.pop(0)


def _ok_mp4() -> ScriptedResponse:
    return ScriptedResponse(
        status=200,
        headers={"Content-Type": "video/mp4", "Content-Length": str(len(MP4_BYTES))},
        chunks=[MP4_BYTES],
    )


@pytest.mark.asyncio
async def test_secure_ingest_pins_public_resolution_and_promotes_by_digest(
    tmp_path: Path,
) -> None:
    resolver = FakeResolver({"video.example": ["8.8.8.8"]})
    response = _ok_mp4()
    transport = ScriptedTransport({"https://video.example/file.mp4": [response]})
    fetcher = SecureMediaFetcher(DestinationPolicy(resolver), transport)

    result = await fetcher.fetch("https://video.example/file.mp4", tmp_path)

    assert result.media_format == "mp4"
    assert result.content_type == "video/mp4"
    assert result.size_bytes == len(MP4_BYTES)
    assert result.path.name == f"{result.sha256}.mp4"
    assert result.path.read_bytes() == MP4_BYTES
    assert transport.targets[0].addresses == ("8.8.8.8",)
    assert response.closed is True
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.asyncio
async def test_secure_ingest_rejects_mixed_public_private_dns_before_transport(
    tmp_path: Path,
) -> None:
    resolver = FakeResolver({"video.example": ["8.8.8.8", "127.0.0.1"]})
    transport = ScriptedTransport({})
    fetcher = SecureMediaFetcher(DestinationPolicy(resolver), transport)

    with pytest.raises(UnsafeAddressError):
        await fetcher.fetch("https://video.example/file.mp4", tmp_path)

    assert transport.targets == []


@pytest.mark.asyncio
async def test_secure_ingest_revalidates_redirects_and_rejects_https_downgrade(
    tmp_path: Path,
) -> None:
    resolver = FakeResolver({"a.example": ["8.8.8.8"], "b.example": ["1.1.1.1"]})
    response = ScriptedResponse(
        status=302,
        headers={"Location": "http://b.example/video.mp4"},
    )
    transport = ScriptedTransport({"https://a.example/start": [response]})
    fetcher = SecureMediaFetcher(DestinationPolicy(resolver), transport)

    with pytest.raises(RedirectPolicyError, match="downgrade"):
        await fetcher.fetch("https://a.example/start", tmp_path)

    assert resolver.calls == [("a.example", 443)]
    assert len(transport.targets) == 1
    assert response.closed is True


@pytest.mark.asyncio
async def test_secure_ingest_stops_when_stream_exceeds_byte_limit(tmp_path: Path) -> None:
    resolver = FakeResolver({"video.example": ["8.8.8.8"]})
    response = ScriptedResponse(
        status=200,
        headers={"Content-Type": "video/mp4"},
        chunks=[MP4_BYTES[:10], MP4_BYTES[10:]],
    )
    transport = ScriptedTransport({"https://video.example/file.mp4": [response]})
    fetcher = SecureMediaFetcher(
        DestinationPolicy(resolver),
        transport,
        limits=FetchLimits(max_bytes=12),
    )

    with pytest.raises(DownloadLimitError):
        await fetcher.fetch("https://video.example/file.mp4", tmp_path)

    assert not list(tmp_path.glob("*.part"))
    assert response.closed is True


@pytest.mark.asyncio
async def test_secure_ingest_rejects_declared_type_that_disagrees_with_signature(
    tmp_path: Path,
) -> None:
    resolver = FakeResolver({"video.example": ["8.8.8.8"]})
    response = ScriptedResponse(
        status=200,
        headers={"Content-Type": "image/png", "Content-Length": str(len(MP4_BYTES))},
        chunks=[MP4_BYTES],
    )
    transport = ScriptedTransport({"https://video.example/file": [response]})
    fetcher = SecureMediaFetcher(DestinationPolicy(resolver), transport)

    with pytest.raises(ContentValidationError, match="does not match"):
        await fetcher.fetch("https://video.example/file", tmp_path)

    assert not list(tmp_path.glob("*.part"))
