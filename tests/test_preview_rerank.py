import json

import httpx
import pytest

from vimi_social.ai.client import LocalAiClient
from vimi_social.domain.source import AdultClassification, CandidateContent
from vimi_social.source.preview_rerank import select_preview_evidence_candidates


def _candidate(
    index: int,
    *,
    gate: float | None = 0.80,
    minimum: float | None = 0.48,
) -> CandidateContent:
    metadata: dict[str, object] = {
        "preview_image_url": f"https://images.example/{index}.jpg",
        "curator_rank": index + 1,
    }
    if gate is not None:
        metadata["curator_text_gate_score"] = gate
    if minimum is not None:
        metadata["curator_minimum_text_relevance_score"] = minimum
    return CandidateContent(
        id=None,
        source="x",
        source_id=str(index),
        source_url=f"https://x.com/i/web/status/{index}",
        author="author",
        published_at=None,
        media_type="video",
        duration_ms=20_000,
        width=1080,
        height=1920,
        title=f"candidate {index}",
        caption=f"candidate {index}",
        tags=(),
        engagement={},
        adult_classification=AdultClassification.UNKNOWN,
        explicitness_score=None,
        provenance_hint="PUBLIC_X_POST_REUSE_RIGHTS_NOT_ESTABLISHED",
        availability="DISCOVERED_MEDIA_REFERENCE_AVAILABLE",
        connector_metadata=metadata,
    )


def test_preview_selector_always_protects_first_telegram_page() -> None:
    candidates = tuple(_candidate(index) for index in range(16))

    selected = select_preview_evidence_candidates(candidates, limit=50)

    assert [candidate.source_id for candidate in selected] == [str(index) for index in range(10)]
    assert all(
        candidate.connector_metadata["preview_evidence_reason"] == "ranking_head"
        for candidate in selected
    )


def test_preview_selector_adds_only_uncertain_candidates_below_head() -> None:
    candidates = tuple(
        _candidate(
            index,
            gate={10: 0.53, 11: 0.59, 12: 0.61}.get(index, 0.80),
        )
        for index in range(13)
    )

    selected = select_preview_evidence_candidates(candidates, limit=50)

    assert [candidate.source_id for candidate in selected] == [
        *(str(index) for index in range(10)),
        "10",
        "11",
    ]
    assert selected[10].connector_metadata["preview_evidence_reason"] == "text_uncertain"
    assert selected[10].connector_metadata["preview_evidence_gate_margin"] == 0.05
    assert selected[11].connector_metadata["preview_evidence_gate_margin"] == 0.11


def test_preview_selector_treats_missing_gate_metadata_as_uncertain() -> None:
    candidates = tuple(
        _candidate(index, gate=None if index == 10 else 0.80)
        for index in range(11)
    )

    selected = select_preview_evidence_candidates(candidates, limit=50)

    assert selected[-1].source_id == "10"
    assert selected[-1].connector_metadata["preview_evidence_reason"] == "text_uncertain"


def test_preview_selector_honors_hard_limit() -> None:
    candidates = tuple(_candidate(index, gate=0.50) for index in range(30))

    selected = select_preview_evidence_candidates(candidates, limit=12)

    assert len(selected) == 12
    assert [candidate.source_id for candidate in selected] == [str(index) for index in range(12)]


@pytest.mark.asyncio
async def test_local_ai_routes_visual_and_ocr_only_to_adaptive_subset() -> None:
    candidates = tuple(
        _candidate(index, gate=0.52 if index == 11 else 0.80)
        for index in range(12)
    )
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        payload = json.loads(request.read())
        preview_urls = payload["preview_image_urls"]
        assert "https://images.example/10.jpg" not in preview_urls
        assert "https://images.example/11.jpg" in preview_urls
        assert len(preview_urls) == 11
        if request.url.path == "/v1/visual-score":
            return httpx.Response(200, json={"scores": [0.1] * 11})
        if request.url.path == "/v1/preview-ocr":
            return httpx.Response(200, json={"texts": ["preview text"] * 11})
        raise AssertionError(f"unexpected path: {request.url.path}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = LocalAiClient("http://local-ai", client=http_client)
        visual_scores = await client.score_preview_candidates(("query",), candidates)
        ocr_texts = await client.extract_preview_texts(candidates)

    assert requested_paths == ["/v1/visual-score", "/v1/preview-ocr"]
    assert len(visual_scores) == 12
    assert visual_scores[10] is None
    assert visual_scores[11] == 0.1
    assert len(ocr_texts) == 12
    assert ocr_texts[10] is None
    assert ocr_texts[11] == "preview text"
