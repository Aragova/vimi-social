from vimi_social.domain.source import AdultClassification, CandidateContent
from vimi_social.source.curator import CandidateCurator


def _candidate(source_id: str, caption: str, *, specificity: float) -> CandidateContent:
    return CandidateContent(
        id=None,
        source="x",
        source_id=source_id,
        source_url=f"https://x.com/i/web/status/{source_id}",
        author="author",
        published_at=None,
        media_type="video",
        duration_ms=300_000,
        width=1920,
        height=1080,
        title=caption,
        caption=caption,
        tags=(),
        engagement={"like_count": 10},
        adult_classification=AdultClassification.UNKNOWN,
        explicitness_score=None,
        provenance_hint="PUBLIC_X_POST_REUSE_RIGHTS_NOT_ESTABLISHED",
        availability="DISCOVERED_METADATA_ONLY",
        connector_metadata={
            "language": "en",
            "retrieval_specificity": specificity,
            "retrieval_relaxation_level": 3,
        },
    )


def test_broadened_lexical_fallback_still_requires_full_intent_match() -> None:
    anchor_only = _candidate(
        "anchor-only",
        "Local market food stalls and weekend shopping guide",
        specificity=0.25,
    )
    full_intent = _candidate(
        "full-intent",
        "Beautiful Bangkok night market walking tour after dark",
        specificity=0.25,
    )

    ranked = CandidateCurator().rank(
        (anchor_only, full_intent),
        query_variants=("Bangkok night market beautiful",),
        preferred_languages=("en",),
        limit=10,
        semantic_scores=None,
        minimum_relevance=0.18,
    )

    assert [candidate.source_id for candidate in ranked] == ["full-intent"]
    assert ranked[0].connector_metadata["curator_text_gate_score"] >= 0.60


def test_exact_lexical_fallback_keeps_existing_fail_open_behavior() -> None:
    exact = _candidate(
        "exact",
        "Local market food stalls and weekend shopping guide",
        specificity=1.0,
    )

    ranked = CandidateCurator().rank(
        (exact,),
        query_variants=("Bangkok night market beautiful",),
        preferred_languages=("en",),
        limit=10,
        semantic_scores=None,
        minimum_relevance=0.18,
    )

    assert [candidate.source_id for candidate in ranked] == ["exact"]
