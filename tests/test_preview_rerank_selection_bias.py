import json

import httpx
import pytest

from vimi_social.ai.client import LocalAiClient
from vimi_social.domain.source import AdultClassification, CandidateContent


def _candidate(index: int) -> CandidateContent:
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
        connector_metadata={
            "preview_image_url": f"https://images.example/{index}.jpg",
            "curator_rank": index + 1,
            "curator_text_gate_score": 0.95,
            "curator_minimum_text_relevance_score": 0.48,
        },
    )


@pytest.mark.asyncio
async def test_preview_ai_does_not_skip_confident_candidates_below_first_page() -> None:
    candidates = tuple(_candidate(index) for index in range(12))
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        payload = json.loads(request.read())
        preview_urls = payload["preview_image_urls"]
        assert preview_urls == [
            f"https://images.example/{index}.jpg" for index in range(12)
        ]
        if request.url.path == "/v1/visual-score":
            return httpx.Response(200, json={"scores": [0.1] * 12})
        if request.url.path == "/v1/preview-ocr":
            return httpx.Response(200, json={"texts": ["preview text"] * 12})
        raise AssertionError(f"unexpected path: {request.url.path}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = LocalAiClient("http://local-ai", client=http_client)
        visual_scores = await client.score_preview_candidates(("query",), candidates)
        ocr_texts = await client.extract_preview_texts(candidates)

    assert requested_paths == ["/v1/visual-score", "/v1/preview-ocr"]
    assert visual_scores == (0.1,) * 12
    assert ocr_texts == ("preview text",) * 12
