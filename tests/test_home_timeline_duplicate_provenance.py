from dataclasses import replace

import pytest

from vimi_social.domain.source import (
    AdultClassification,
    CandidateContent,
    ScoutSearchRequest,
)
from vimi_social.source.connectors import SourceConnectorRegistry, SourceSearchCandidates
from vimi_social.source.home_timeline import HomeTimelineSeedRegistry


def _candidate(
    source_id: str,
    *,
    duration_ms: int,
    origin: str | None = None,
) -> CandidateContent:
    metadata: dict[str, object] = {
        "acquisition_url": f"https://video.example/{source_id}.mp4",
        "language": "en",
    }
    if origin is not None:
        metadata["x_candidate_origin"] = origin
    return CandidateContent(
        id=None,
        source="x",
        source_id=source_id,
        source_url=f"https://x.com/i/web/status/{source_id}",
        author="author",
        published_at=None,
        media_type="video",
        duration_ms=duration_ms,
        width=1920,
        height=1080,
        title="gay porn twink young scene",
        caption="gay porn twink young scene",
        tags=(),
        engagement={"like_count": 10},
        adult_classification=AdultClassification.UNKNOWN,
        explicitness_score=None,
        provenance_hint="PUBLIC_X_POST_REUSE_RIGHTS_NOT_ESTABLISHED",
        availability="DISCOVERED_METADATA_ONLY",
        connector_metadata=metadata,
    )


class _DuplicateProvider:
    source_name = "x"

    async def search(self, request: ScoutSearchRequest) -> tuple[CandidateContent, ...]:
        del request
        provider = _candidate("shared", duration_ms=120_000)
        metadata = dict(provider.connector_metadata)
        metadata["x_search_scope"] = "all"
        metadata["x_search_query"] = "(gay twink) has:videos"
        provider = replace(provider, connector_metadata=metadata)
        return SourceSearchCandidates((provider,), next_token="provider-next")


@pytest.mark.asyncio
async def test_exact_provider_duplicate_preserves_home_timeline_provenance() -> None:
    seed = _candidate(
        "shared",
        duration_ms=1_080_000,
        origin="home_timeline",
    )
    registry = HomeTimelineSeedRegistry(
        SourceConnectorRegistry((_DuplicateProvider(),)),
        seed_getter=lambda: (seed,),
    )
    connector = registry.route(("x",))[0]
    request = ScoutSearchRequest(
        intent="gay porn twink young",
        requested_sources=("x",),
        preferred_languages=("en",),
        query_variants=("gay porn twink young",),
        max_results=30,
    )

    result = await connector.search(request)

    assert isinstance(result, SourceSearchCandidates)
    assert result.next_token == "provider-next"
    assert len(result) == 1
    candidate = result[0]
    assert candidate.source_id == "shared"
    assert candidate.duration_ms == 1_080_000
    assert candidate.connector_metadata["x_candidate_origin"] == "home_timeline"
    assert candidate.connector_metadata["x_search_scope"] == "all"
    assert candidate.connector_metadata["x_search_query"] == "(gay twink) has:videos"
