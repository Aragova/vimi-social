from typing import Protocol

from vimi_social.source.models import CandidateContent, SourcePlatform, SourceSearchRequest


class SourceConnectorError(RuntimeError):
    pass


class SourceConnectorUnavailable(SourceConnectorError):
    pass


class SourceConnector(Protocol):
    @property
    def platform(self) -> SourcePlatform: ...

    async def search(self, request: SourceSearchRequest) -> tuple[CandidateContent, ...]: ...

    async def aclose(self) -> None: ...


class SourceConnectorRegistry:
    def __init__(self, connectors: tuple[SourceConnector, ...]) -> None:
        self._connectors = {connector.platform: connector for connector in connectors}
        if len(self._connectors) != len(connectors):
            raise ValueError("duplicate source connector platform")

    def get(self, platform: SourcePlatform) -> SourceConnector:
        try:
            return self._connectors[platform]
        except KeyError:
            raise SourceConnectorUnavailable(
                f"source connector is not configured for {platform.value}"
            ) from None

    async def aclose(self) -> None:
        for connector in self._connectors.values():
            await connector.aclose()
