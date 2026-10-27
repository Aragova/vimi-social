from collections.abc import Iterable
from typing import Protocol

from vimi_social.domain.source import CandidateContent, ScoutSearchRequest


class SourceSearchCandidates(tuple[CandidateContent, ...]):
    """Tuple-compatible search result with provider pagination state."""

    next_token: str | None

    def __new__(
        cls,
        candidates: Iterable[CandidateContent] = (),
        *,
        next_token: str | None = None,
    ) -> "SourceSearchCandidates":
        result = super().__new__(cls, candidates)
        result.next_token = next_token
        return result


class SourceConnectorError(RuntimeError):
    pass


class SourceConnectorUnavailable(SourceConnectorError):
    pass


class SourceConnectorRejected(SourceConnectorError):
    pass


class SourceConnectorRateLimited(SourceConnectorError):
    def __init__(self, retry_after_seconds: int | None = None) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__("source connector rate limited request")


class SourceConnector(Protocol):
    @property
    def source_name(self) -> str: ...

    async def search(self, request: ScoutSearchRequest) -> tuple[CandidateContent, ...]: ...


class SourceConnectorRegistry:
    def __init__(self, connectors: Iterable[SourceConnector] = ()) -> None:
        self._connectors: dict[str, SourceConnector] = {}
        for connector in connectors:
            self.register(connector)

    def register(self, connector: SourceConnector) -> None:
        name = connector.source_name.strip().lower()
        if not name:
            raise ValueError("source connector name must not be empty")
        if name in self._connectors:
            raise ValueError(f"source connector {name!r} is already registered")
        self._connectors[name] = connector

    def route(self, requested_sources: tuple[str, ...]) -> tuple[SourceConnector, ...]:
        if requested_sources:
            names = tuple(dict.fromkeys(name.strip().lower() for name in requested_sources))
            missing = tuple(name for name in names if name not in self._connectors)
            if missing:
                raise SourceConnectorUnavailable(
                    f"requested source connector is unavailable: {', '.join(missing)}"
                )
            return tuple(self._connectors[name] for name in names)

        if not self._connectors:
            raise SourceConnectorUnavailable("no source connectors are configured")
        return tuple(self._connectors.values())
