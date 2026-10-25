from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from apps.local_ai.visual import SiglipPreviewScorer

from vimi_social.media.secure_ingest.addressing import DestinationPolicy
from vimi_social.media.secure_ingest.errors import UnsafeAddressError
from vimi_social.media.secure_ingest.models import FetchTimeouts, ResolvedTarget


@dataclass
class FakeResolver:
    answers: Mapping[str, Sequence[str]]

    async def resolve(self, host: str, port: int) -> Sequence[str]:
        del port
        return self.answers.get(host, ())


@dataclass
class FakeResponse:
    status: int = 200
    headers: Mapping[str, str] = field(
        default_factory=lambda: {"Content-Type": "image/jpeg"}
    )
    chunks: Sequence[bytes] = (b"preview-bytes",)
    closed: bool = False

    async def iter_chunks(self, chunk_size: int) -> AsyncIterator[bytes]:
        del chunk_size
        for chunk in self.chunks:
            yield chunk

    async def close(self) -> None:
        self.closed = True


@dataclass
class FakeTransport:
    response: FakeResponse
    targets: list[ResolvedTarget] = field(default_factory=lambda: list[ResolvedTarget]())

    async def open(
        self,
        target: ResolvedTarget,
        *,
        timeouts: FetchTimeouts,
    ) -> FakeResponse:
        del timeouts
        self.targets.append(target)
        return self.response


@pytest.mark.asyncio
async def test_visual_preview_rejects_private_dns_before_transport(tmp_path: Path) -> None:
    transport = FakeTransport(FakeResponse())
    scorer = SiglipPreviewScorer(
        tmp_path,
        destination_policy=DestinationPolicy(
            FakeResolver({"pbs.twimg.com": ["8.8.8.8", "127.0.0.1"]})
        ),
        transport=transport,
    )

    with pytest.raises(UnsafeAddressError):
        await scorer._download_preview("https://pbs.twimg.com/media/example.jpg")

    assert transport.targets == []


@pytest.mark.asyncio
async def test_visual_preview_passes_validated_pinned_target_to_transport(
    tmp_path: Path,
) -> None:
    response = FakeResponse()
    transport = FakeTransport(response)
    scorer = SiglipPreviewScorer(
        tmp_path,
        destination_policy=DestinationPolicy(FakeResolver({"pbs.twimg.com": ["8.8.8.8"]})),
        transport=transport,
    )

    payload = await scorer._download_preview("https://pbs.twimg.com/media/example.jpg")

    assert payload == b"preview-bytes"
    assert len(transport.targets) == 1
    assert transport.targets[0].host == "pbs.twimg.com"
    assert transport.targets[0].addresses == ("8.8.8.8",)
    assert response.closed is True
