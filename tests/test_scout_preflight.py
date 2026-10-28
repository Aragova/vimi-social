from vimi_social.domain.source import CandidateContent, ScoutSearchRequest
from vimi_social.source.connectors import SourceConnectorRegistry
from vimi_social.source.preflight import sources_available


class _XConnector:
    @property
    def source_name(self) -> str:
        return "x"

    async def search(self, request: ScoutSearchRequest) -> tuple[CandidateContent, ...]:
        del request
        return ()


def test_source_preflight_rejects_unavailable_source() -> None:
    registry = SourceConnectorRegistry((_XConnector(),))
    assert not sources_available(registry, ("reddit",))


def test_source_preflight_accepts_configured_source() -> None:
    registry = SourceConnectorRegistry((_XConnector(),))
    assert sources_available(registry, ("x",))


def test_source_preflight_fails_when_no_connectors_are_configured() -> None:
    assert not sources_available(SourceConnectorRegistry(), ())
