from vimi_social.domain.source import AdultClassification, CandidateContent
from vimi_social.source.unified_ranking import (
    hashtag_stuffing_penalty,
    score_candidate,
)


def _candidate(
    source_id: str,
    *,
    duration_ms: int,
    text: str,
) -> CandidateContent:
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


def test_hashtag_stuffing_penalty_detects_staging_pattern() -> None:
    candidate = _candidate(
        "search-spam",
        duration_ms=84_000,
        text=(
            "Young guy #gayxxx #gaysex #gayporn #gay #hotguys "
            "#porn #cuteguys #bigcocks"
        ),
    )

    assert hashtag_stuffing_penalty(candidate) == 1.0


def test_hashtag_stuffing_penalty_does_not_hit_normal_caption() -> None:
    candidate = _candidate(
        "normal",
        duration_ms=600_000,
        text="Young creator sharing a long-form studio scene #video #creator",
    )

    assert hashtag_stuffing_penalty(candidate) == 0.0


def test_long_form_candidate_outranks_hashtag_stuffed_search_regression() -> None:
    search_candidate = _candidate(
        "search",
        duration_ms=84_000,
        text=(
            "Young guy #gayxxx #gaysex #gayporn #gay #hotguys "
            "#porn #cuteguys #bigcocks"
        ),
    )
    timeline_candidate = _candidate(
        "timeline",
        duration_ms=1_098_000,
        text="Long-form creator scene",
    )

    search_score, scored_search = score_candidate(
        search_candidate,
        semantic_raw=0.896062,
        lexical=1.0,
        visual_relevance=None,
        ocr_relevance=None,
    )
    timeline_score, _ = score_candidate(
        timeline_candidate,
        semantic_raw=0.826216,
        lexical=0.0,
        visual_relevance=None,
        ocr_relevance=None,
    )

    assert scored_search.connector_metadata[
        "curator_hashtag_stuffing_penalty_score"
    ] == 1.0
    assert timeline_score > search_score
