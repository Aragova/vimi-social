from vimi_social.domain.source import AdultClassification, CandidateContent
from vimi_social.source.unified_continuation import UnifiedContinuationCandidateCurator


def _candidate(source_id: str, *, duration_ms: int, text: str) -> CandidateContent:
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
        title=text,
        caption=text,
        tags=(),
        engagement={},
        adult_classification=AdultClassification.UNKNOWN,
        explicitness_score=None,
        provenance_hint="PUBLIC_X_POST_REUSE_RIGHTS_NOT_ESTABLISHED",
        availability="DISCOVERED_METADATA_ONLY",
        connector_metadata={},
    )


def test_unified_continuation_rejects_known_sub_minute_video() -> None:
    curator = UnifiedContinuationCandidateCurator()
    candidates = (
        _candidate("short", duration_ms=59_000, text="same caption"),
        _candidate("long", duration_ms=61_000, text="same caption"),
    )

    ranked = curator.rank(
        candidates,
        query_variants=("same", "caption"),
        preferred_languages=("en",),
        limit=10,
        minimum_relevance=0.0,
    )

    assert [candidate.source_id for candidate in ranked] == ["long"]


def test_unified_continuation_keeps_text_near_duplicates_with_distinct_ids() -> None:
    curator = UnifiedContinuationCandidateCurator()
    candidates = (
        _candidate("one", duration_ms=120_000, text="same caption"),
        _candidate("two", duration_ms=120_000, text="same caption"),
    )

    ranked = curator.rank(
        candidates,
        query_variants=("same", "caption"),
        preferred_languages=("en",),
        limit=10,
        minimum_relevance=0.0,
    )

    assert {candidate.source_id for candidate in ranked} == {"one", "two"}
