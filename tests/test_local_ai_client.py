import httpx
import pytest

from vimi_social.ai.client import LocalAiClient
from vimi_social.domain.source import AdultClassification, CandidateContent
from vimi_social.source.semantic import SemanticRelevanceUnavailable


def _candidate(source_id: str, caption: str | None) -> CandidateContent:
    return CandidateContent(
        id=None,
        source="x",
        source_id=source_id,
        source_url=f"https://x.com/i/web/status/{source_id}",
        author=None,
        published_at=None,
        media_type="video",
        duration_ms=None,
        width=None,
        height=None,
        title=caption,
        caption=caption,
        tags=(),
        engagement={},
        adult_classification=AdultClassification.UNKNOWN,
        explicitness_score=None,
        provenance_hint="PUBLIC_X_POST_REUSE_RIGHTS_NOT_ESTABLISHED",
        availability="DISCOVERED_METADATA_ONLY",
        connector_metadata={},
    )


@pytest.mark.asyncio
async def test_local_ai_translation_uses_internal_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/translate"
        return httpx.Response(200, json={"text": "Bangkok at night"})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = LocalAiClient("http://local-ai:8090", client=http_client)

    result = await client.translate_to_english("ночной Бангкок")

    assert result == "Bangkok at night"
    await http_client.aclose()


@pytest.mark.asyncio
async def test_local_ai_semantic_scores_preserve_candidate_alignment() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/semantic-score"
        return httpx.Response(200, json={"scores": [0.81, 0.12]})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = LocalAiClient("http://local-ai:8090", client=http_client)
    candidates = (
        _candidate("good", "Bangkok skyline and traffic at night"),
        _candidate("empty", None),
        _candidate("noise", "Seoul conference keynote"),
    )

    scores = await client.score_candidates(("Bangkok at night",), candidates)

    assert scores == (0.81, 0.0, 0.12)
    await http_client.aclose()


@pytest.mark.asyncio
async def test_local_ai_semantic_failure_is_explicit_for_fail_open_scout() -> None:
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(503))
    )
    client = LocalAiClient("http://local-ai:8090", client=http_client)

    with pytest.raises(SemanticRelevanceUnavailable):
        await client.score_candidates(
            ("Bangkok at night",),
            (_candidate("candidate", "Bangkok skyline"),),
        )

    await http_client.aclose()
