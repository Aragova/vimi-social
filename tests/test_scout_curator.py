from vimi_social.domain.source import AdultClassification, CandidateContent
from vimi_social.source.curator import CandidateCurator


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
