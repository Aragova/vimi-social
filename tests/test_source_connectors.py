from vimi_social.domain.source import CandidateContent, ScoutSearchRequest
from vimi_social.source.connectors import (
    SourceConnectorRegistry,
    SourceConnectorUnavailable,
)


class FakeConnector:
    source_name = "x"

    async def search(self, request: ScoutSearchRequest) -> tuple[CandidateContent, ...]:
        del request
        return ()


def test_registry_routes_requested_specialized_connector() -> None:
    connector = FakeConnector()
    registry = SourceConnectorRegistry([connector])

    assert registry.route(("x",)) == (connector,)


def test_registry_fails_closed_for_unavailable_requested_source() -> None:
    registry = SourceConnectorRegistry([FakeConnector()])

    try:
        registry.route(("telegram",))
    except SourceConnectorUnavailable as error:
        assert "telegram" in str(error)
    else:
        raise AssertionError("registry must not silently substitute a different source")
