from vimi_social.domain.source import AdultClassification, CandidateContent
from vimi_social.source.curator import CandidateCurator, restore_curator_order


def _candidate(
    source_id: str,
    caption: str,
    *,
    width: int = 1080,
    height: int = 1920,
    duration_ms: int = 20_000,
    likes: int = 0,
    acquisition: bool = True,
    language: str = "en",
) -> CandidateContent:
    metadata: dict[str, object] = {"language": language}
    if acquisition:
        metadata["acquisition_url"] = f"https://media.example/{source_id}.mp4"
    return CandidateContent(
        id=None,
        source="x",
        source_id=source_id,
        source_url=f"https://x.com/i/web/status/{source_id}",
        author="author",
        published_at=None,
        media_type="video",
        duration_ms=duration_ms,
        width=width,
        height=height,
        title=caption,
        caption=caption,
        tags=(),
        engagement={"like_count": likes},
        adult_classification=AdultClassification.UNKNOWN,
        explicitness_score=None,
        provenance_hint="PUBLIC_X_POST_REUSE_RIGHTS_NOT_ESTABLISHED",
        availability="DISCOVERED_MEDIA_REFERENCE_AVAILABLE",
        connector_metadata=metadata,
    )


def _score(candidate: CandidateContent, key: str) -> float:
    value = candidate.connector_metadata[key]
    assert isinstance(value, float)
    return value


def test_curator_prioritizes_relevance_over_popularity() -> None:
    relevant = _candidate(
        "relevant",
        "Bangkok nightlife from Sukhumvit after dark",
        likes=15,
    )
    popular_noise = _candidate(
        "noise",
        "Beach workout compilation and fitness motivation",
        likes=100_000,
    )

    ranked = CandidateCurator().rank(
        (popular_noise, relevant),
        query_variants=("Bangkok nightlife",),
        preferred_languages=("en",),
        limit=10,
    )

    assert [candidate.source_id for candidate in ranked] == ["relevant", "noise"]
    assert _score(ranked[0], "curator_relevance_score") > _score(
        ranked[1], "curator_relevance_score"
    )
    assert [candidate.connector_metadata["curator_rank"] for candidate in ranked] == [1, 2]


def test_curator_uses_quality_to_break_equal_relevance() -> None:
    low_quality = _candidate(
        "low",
        "Bangkok nightlife",
        width=320,
        height=240,
        duration_ms=1_000,
        acquisition=False,
    )
    high_quality = _candidate(
        "high",
        "Bangkok nightlife",
        width=1080,
        height=1920,
        duration_ms=30_000,
        likes=500,
    )

    ranked = CandidateCurator().rank(
        (low_quality, high_quality),
        query_variants=("Bangkok nightlife",),
        preferred_languages=("en",),
        limit=10,
    )

    assert [candidate.source_id for candidate in ranked] == ["high", "low"]
    assert _score(ranked[0], "curator_quality_score") > _score(
        ranked[1], "curator_quality_score"
    )


def test_curator_semantic_evidence_can_override_lexical_noise() -> None:
    lexical_trap = _candidate(
        "trap",
        "Bangkok at night: unrelated conference commentary",
        likes=50_000,
    )
    semantic_match = _candidate(
        "match",
        "City lights, skyline and traffic after sunset in Thailand",
        likes=5,
    )

    ranked = CandidateCurator().rank(
        (lexical_trap, semantic_match),
        query_variants=("Bangkok city at night",),
        preferred_languages=("en",),
        limit=10,
        semantic_scores=(0.74, 0.91),
        minimum_relevance=0.18,
    )

    assert [candidate.source_id for candidate in ranked] == ["match", "trap"]
    assert _score(ranked[0], "curator_semantic_raw_score") == 0.91
    assert _score(ranked[0], "curator_semantic_relevance_score") == 0.7
    assert _score(ranked[0], "curator_relevance_score") > _score(
        ranked[1], "curator_relevance_score"
    )


def test_curator_visual_evidence_can_break_equal_text_relevance() -> None:
    event = _candidate("event", "Bangkok at night", likes=10)
    city = _candidate("city", "Bangkok at night", likes=10)

    ranked = CandidateCurator().rank(
        (event, city),
        query_variants=("Bangkok at night",),
        preferred_languages=("en",),
        limit=10,
        semantic_scores=(0.84, 0.84),
        visual_scores=(0.10, 0.80),
        visual_weight=0.25,
        minimum_relevance=0.18,
    )

    assert [candidate.source_id for candidate in ranked] == ["city", "event"]
    assert _score(ranked[0], "curator_visual_raw_score") == 0.8
    assert _score(ranked[0], "curator_visual_relevance_score") == 1.0
    assert _score(ranked[1], "curator_visual_relevance_score") == 0.0
    assert _score(ranked[0], "curator_text_relevance_score") == _score(
        ranked[1], "curator_text_relevance_score"
    )
    assert _score(ranked[0], "curator_relevance_score") > _score(
        ranked[1], "curator_relevance_score"
    )


def test_curator_calibrates_compressed_visual_cosines_relative_to_task() -> None:
    low = _candidate("low", "Bangkok at night", likes=10)
    middle = _candidate("middle", "Bangkok at night", likes=10)
    high = _candidate("high", "Bangkok at night", likes=10)

    ranked = CandidateCurator().rank(
        (low, middle, high),
        query_variants=("Bangkok at night",),
        preferred_languages=("en",),
        limit=10,
        semantic_scores=(0.84, 0.84, 0.84),
        visual_scores=(0.013, 0.048, 0.064),
        visual_weight=0.15,
        minimum_relevance=0.18,
    )

    assert [candidate.source_id for candidate in ranked] == ["high", "middle", "low"]
    assert _score(ranked[0], "curator_visual_relevance_score") == 1.0
    assert _score(ranked[1], "curator_visual_relevance_score") == 0.5
    assert _score(ranked[2], "curator_visual_relevance_score") == 0.0


def test_curator_equal_visual_cosines_leave_text_ranking_unchanged() -> None:
    first = _candidate("first", "Bangkok at night", likes=20)
    second = _candidate("second", "Bangkok at night", likes=10)

    ranked = CandidateCurator().rank(
        (first, second),
        query_variants=("Bangkok at night",),
        preferred_languages=("en",),
        limit=10,
        semantic_scores=(0.84, 0.84),
        visual_scores=(0.048, 0.048),
        visual_weight=0.25,
        minimum_relevance=0.18,
    )

    assert [candidate.source_id for candidate in ranked] == ["first", "second"]
    assert _score(ranked[0], "curator_visual_raw_score") == 0.048
    assert "curator_visual_relevance_score" not in ranked[0].connector_metadata
    assert _score(ranked[0], "curator_relevance_score") == _score(
        ranked[0], "curator_text_relevance_score"
    )


def test_curator_missing_visual_evidence_does_not_penalize_candidate() -> None:
    first = _candidate("first", "Bangkok at night", likes=10)
    second = _candidate("second", "Bangkok at night", likes=10)

    ranked = CandidateCurator().rank(
        (first, second),
        query_variants=("Bangkok at night",),
        preferred_languages=("en",),
        limit=10,
        semantic_scores=(0.84, 0.84),
        visual_scores=(None, None),
        visual_weight=0.25,
        minimum_relevance=0.18,
    )

    assert [candidate.source_id for candidate in ranked] == ["first", "second"]
    assert "curator_visual_raw_score" not in ranked[0].connector_metadata
    assert _score(ranked[0], "curator_relevance_score") == _score(
        ranked[0], "curator_text_relevance_score"
    )


def test_curator_filters_low_semantic_relevance_when_enabled() -> None:
    relevant = _candidate("relevant", "Bangkok skyline after sunset")
    noise = _candidate("noise", "Seoul technology conference keynote")

    ranked = CandidateCurator().rank(
        (noise, relevant),
        query_variants=("Bangkok at night",),
        preferred_languages=("en",),
        limit=10,
        semantic_scores=(0.71, 0.90),
        minimum_relevance=0.18,
    )

    assert [candidate.source_id for candidate in ranked] == ["relevant"]


def test_curator_enforces_final_result_budget() -> None:
    candidates = tuple(
        _candidate(str(index), f"Bangkok nightlife clip {index}")
        for index in range(15)
    )

    ranked = CandidateCurator().rank(
        candidates,
        query_variants=("Bangkok nightlife",),
        preferred_languages=("en",),
        limit=10,
    )

    assert len(ranked) == 10
    assert all("curator_total_score" in candidate.connector_metadata for candidate in ranked)
    assert [candidate.connector_metadata["curator_rank"] for candidate in ranked] == list(
        range(1, 11)
    )


def test_restore_curator_order_recovers_rank_after_reload_shuffle() -> None:
    ranked = CandidateCurator().rank(
        (
            _candidate("noise", "Beach workout compilation", likes=100_000),
            _candidate("best", "Bangkok nightlife Sukhumvit", likes=10),
            _candidate("good", "Bangkok night market", likes=5),
        ),
        query_variants=("Bangkok nightlife", "Bangkok night"),
        preferred_languages=("en",),
        limit=10,
    )

    reloaded = (ranked[2], ranked[0], ranked[1])
    restored = restore_curator_order(reloaded)

    assert restored == ranked
