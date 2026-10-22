import math
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class FetchTimeouts:
    connect_seconds: float = 5.0
    read_seconds: float = 10.0
    total_seconds: float = 30.0

    def __post_init__(self) -> None:
        for name, value in (
            ("connect_seconds", self.connect_seconds),
            ("read_seconds", self.read_seconds),
            ("total_seconds", self.total_seconds),
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a finite positive value")


@dataclass(frozen=True, slots=True)
class FetchLimits:
    max_bytes: int = 64 * 1024 * 1024
    max_redirects: int = 4
    chunk_size: int = 64 * 1024
    timeouts: FetchTimeouts = FetchTimeouts()

    def __post_init__(self) -> None:
        if self.max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if self.max_redirects < 0:
            raise ValueError("max_redirects cannot be negative")
        if self.chunk_size <= 0:
            raise ValueError("chunk_size must be positive")


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    url: str
    scheme: str
    host: str
    port: int
    addresses: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MediaFormat:
    name: str
    extension: str
    allowed_content_types: frozenset[str]


@dataclass(frozen=True, slots=True)
class FetchResult:
    path: Path
    sha256: str
    size_bytes: int
    media_format: str
    content_type: str
    final_url: str
    redirect_count: int


class ResponseStream(Protocol):
    @property
    def status(self) -> int: ...

    @property
    def headers(self) -> Mapping[str, str]: ...

    def iter_chunks(self, chunk_size: int) -> AsyncIterator[bytes]: ...

    async def close(self) -> None: ...


class OneHopTransport(Protocol):
    async def open(
        self,
        target: ResolvedTarget,
        *,
        timeouts: FetchTimeouts,
    ) -> ResponseStream: ...
