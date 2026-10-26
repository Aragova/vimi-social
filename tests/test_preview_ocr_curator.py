from vimi_social.domain.source import AdultClassification, CandidateContent
from vimi_social.source.curator import CandidateCurator


def _candidate(source_id: str, caption: str) -> CandidateContent:
    return CandidateContent(
        id=None,
        source="x",
        source_id=source_id,
        source_url=f"https://x.com/i/web/status/{source_id}",
        author="author",
        published_at=None,
        media_type="video",
        duration_ms=20_000,
        width=1080,
        height=1920,
        title=caption,
        caption=caption,
        tags=(),
        engagement={},
        adult_classification=AdultClassification.UNKNOWN,
        explicitness_score=None,
        provenance_hint="PUBLIC_X_POST_REUSE_RIGHTS_NOT_ESTABLISHED",
        availability="DISCOVERED_MEDIA_REFERENCE_AVAILABLE",
        connector_metadata={
            "language": "en",
            "acquisition_url": f"https://media.example/{source_id}.mp4",
        },
    )


def _score(candidate: CandidateContent, key: str) -> float:
    value = candidate.connector_metadata[key]
    assert isinstance(value, float)
    return value


def test_preview_ocr_semantic_evidence_breaks_equal_base_ranking() -> None:
    event = _candidate("event", "Bangkok at night")
    market = _candidate("market", "Bangkok at night")

    ranked = CandidateCurator().rank(
        (event, market),
        query_variants=("Bangkok at night",),
        preferred_languages=("en",),
        limit=10,
        semantic_scores=(0.84, 0.84),
        visual_scores=(0.05, 0.05),
        preview_ocr_texts=("BLOCKCHAIN WEEK BANGKOK", "BANGKOK NIGHT MARKET"),
        preview_ocr_semantic_scores=(0.72, 0.94),
        preview_ocr_weight=0.10,
        minimum_relevance=0.18,
    )

    assert [candidate.source_id for candidate in ranked] == ["market", "event"]
    assert ranked[0].connector_metadata["curator_preview_ocr_text"] == "BANGKOK NIGHT MARKET"
    assert _score(ranked[0], "curator_preview_ocr_semantic_raw_score") == 0.94
    assert _score(ranked[0], "curator_preview_ocr_relevance_score") == 0.8
    assert _score(ranked[0], "curator_relevance_score") > _score(
        ranked[1], "curator_relevance_score"
    )


def test_missing_preview_ocr_evidence_leaves_existing_relevance_unchanged() -> None:
    first = _candidate("first", "Bangkok at night")
    second = _candidate("second", "Bangkok at night")

    ranked = CandidateCurator().rank(
        (first, second),
        query_variants=("Bangkok at night",),
        preferred_languages=("en",),
        limit=10,
        semantic_scores=(0.84, 0.84),
        visual_scores=(0.04, 0.08),
        preview_ocr_texts=(None, None),
        preview_ocr_semantic_scores=(None, None),
        visual_weight=0.15,
        preview_ocr_weight=0.10,
        minimum_relevance=0.18,
    )

    assert [candidate.source_id for candidate in ranked] == ["second", "first"]
    assert "curator_preview_ocr_text" not in ranked[0].connector_metadata
    assert "curator_preview_ocr_relevance_score" not in ranked[0].connector_metadata
