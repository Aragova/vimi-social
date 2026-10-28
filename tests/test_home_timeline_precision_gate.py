from vimi_social.domain.source import AdultClassification, CandidateContent
from vimi_social.source.retrieval_v3 import RetrievalV3CandidateCurator


def _timeline_candidate(
    source_id: str,
    text: str,
    *,
    duration_ms: int = 600_000,
) -> CandidateContent:
    return CandidateContent(
        id=None,
        source="x",
        source_id=source_id,
        source_url=f"https://x.com/i/web/status/{source_id}",
        author=f"author-{source_id}",
        published_at=None,
        media_type="video",
        duration_ms=duration_ms,
        width=1920,
        height=1080,
        title=text,
        caption=text,
        tags=(),
        engagement={"like_count": 10},
        adult_classification=AdultClassification.UNKNOWN,
        explicitness_score=None,
        provenance_hint="PUBLIC_X_POST_REUSE_RIGHTS_NOT_ESTABLISHED",
        availability="DISCOVERED_MEDIA_REFERENCE_AVAILABLE",
        connector_metadata={
            "acquisition_url": f"https://video.example/{source_id}.mp4",
            "language": "en",
            "retrieval_specificity": 0.0,
            "retrieval_strategy": "home_timeline_personalized_seed",
            "x_candidate_origin": "home_timeline",
        },
    )


def test_timeline_strong_semantic_match_can_pass_without_literal_query_terms() -> None:
    candidate = _timeline_candidate(
        "semantic-pass",
        "Chudai watch full video",
    )

    ranked = RetrievalV3CandidateCurator().rank(
        (candidate,),
        query_variants=("gay porn twink young",),
        preferred_languages=("en",),
        limit=1,
        semantic_scores=(0.86,),
        minimum_relevance=0.18,
    )

    assert [item.source_id for item in ranked] == ["semantic-pass"]
    metadata = ranked[0].connector_metadata
    assert metadata["curator_timeline_gate_method"] == "semantic"
    assert metadata["curator_timeline_semantic_minimum"] == 0.81
    assert metadata["retrieval_source_specificity"] == 0.0
    assert "retrieval_specificity" not in metadata


def test_timeline_long_form_semantic_match_passes_calibrated_floor() -> None:
    candidate = _timeline_candidate(
        "long-semantic-pass",
        "hearts full video",
        duration_ms=19 * 60 * 1000,
    )

    ranked = RetrievalV3CandidateCurator().rank(
        (candidate,),
        query_variants=("gay porn twink young",),
        preferred_languages=("en",),
        limit=1,
        semantic_scores=(0.818,),
        minimum_relevance=0.18,
    )

    assert [item.source_id for item in ranked] == ["long-semantic-pass"]
    metadata = ranked[0].connector_metadata
    assert metadata["curator_timeline_gate_method"] == "semantic"
    assert metadata["curator_timeline_semantic_raw_score"] == 0.818
    assert metadata["curator_timeline_semantic_minimum"] == 0.81


def test_timeline_long_form_semantic_match_below_calibrated_floor_is_rejected() -> None:
    candidate = _timeline_candidate(
        "long-semantic-reject",
        "hearts full video",
        duration_ms=19 * 60 * 1000,
    )

    ranked = RetrievalV3CandidateCurator().rank(
        (candidate,),
        query_variants=("gay porn twink young",),
        preferred_languages=("en",),
        limit=1,
        semantic_scores=(0.809,),
        minimum_relevance=0.18,
    )

    assert ranked == ()


def test_timeline_short_video_keeps_stricter_semantic_floor() -> None:
    candidate = _timeline_candidate(
        "short-semantic-reject",
        "hearts full video",
        duration_ms=2 * 60 * 1000,
    )

    ranked = RetrievalV3CandidateCurator().rank(
        (candidate,),
        query_variants=("gay porn twink young",),
        preferred_languages=("en",),
        limit=1,
        semantic_scores=(0.818,),
        minimum_relevance=0.18,
    )

    assert ranked == ()


def test_timeline_weak_semantic_match_is_rejected_without_lexical_support() -> None:
    candidate = _timeline_candidate(
        "semantic-reject",
        "unrelated cooking tutorial",
    )

    ranked = RetrievalV3CandidateCurator().rank(
        (candidate,),
        query_variants=("gay porn twink young",),
        preferred_languages=("en",),
        limit=1,
        semantic_scores=(0.80,),
        minimum_relevance=0.18,
    )

    assert ranked == ()


def test_timeline_lexical_fallback_requires_two_intent_tokens_when_e5_unavailable() -> None:
    candidate = _timeline_candidate(
        "lexical-pass",
        "gay porn full video",
    )

    ranked = RetrievalV3CandidateCurator().rank(
        (candidate,),
        query_variants=("gay porn twink young",),
        preferred_languages=("en",),
        limit=1,
        semantic_scores=None,
        minimum_relevance=0.18,
    )

    assert [item.source_id for item in ranked] == ["lexical-pass"]
    assert ranked[0].connector_metadata["curator_timeline_gate_method"] == "lexical_fallback"
    assert ranked[0].connector_metadata["curator_timeline_lexical_match_count"] == 2


def test_timeline_lexical_fallback_rejects_single_token_match() -> None:
    candidate = _timeline_candidate(
        "lexical-reject",
        "gay dating discussion",
    )

    ranked = RetrievalV3CandidateCurator().rank(
        (candidate,),
        query_variants=("gay porn twink young",),
        preferred_languages=("en",),
        limit=1,
        semantic_scores=None,
        minimum_relevance=0.18,
    )

    assert ranked == ()
