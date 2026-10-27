from vimi_social.domain.source import AdultClassification, CandidateContent
from vimi_social.source.activities import _apply_continuation_state


def _candidate() -> CandidateContent:
    return CandidateContent(
        id=None,
        source="x",
        source_id="long-round-0",
        source_url="https://x.com/i/web/status/long-round-0",
        author="author",
        published_at=None,
        media_type="video",
        duration_ms=600_000,
        width=1920,
        height=1080,
        title="long-form candidate",
        caption="long-form candidate",
        tags=(),
        engagement={"like_count": 10},
        adult_classification=AdultClassification.UNKNOWN,
        explicitness_score=None,
        provenance_hint="PUBLIC_X_POST_REUSE_RIGHTS_NOT_ESTABLISHED",
        availability="DISCOVERED_METADATA_ONLY",
        connector_metadata={
            "retrieval_query": "round zero",
            "retrieval_query_variants": ["round zero"],
            "retrieval_relaxation_level": 0,
            "retrieval_specificity": "strict",
            "retrieval_language_mode": "en",
            "x_search_scope": "all",
            "x_search_query": "round zero",
            "x_next_token": "page-2",
            "x_continuation_generation": 0,
        },
    )


def test_earlier_round_retirement_survives_unmatched_broader_round_state() -> None:
    retired_round = {
        "retrieval_query": "round zero",
        "retrieval_query_variants": ["round zero"],
        "retrieval_relaxation_level": 0,
        "retrieval_specificity": "strict",
        "retrieval_language_mode": "en",
        "x_search_scope": "all",
        "x_search_query": "round zero",
        "x_page_start_token": "page-2",
        "x_continuation_generation": 1,
    }
    empty_broader_round = {
        "retrieval_query": "broader round",
        "retrieval_query_variants": ["broader round"],
        "retrieval_relaxation_level": 1,
        "retrieval_specificity": "relaxed",
        "retrieval_language_mode": "en",
        "x_search_scope": "all",
        "x_search_query": "broader round",
        "x_continuation_generation": 0,
    }

    curated = (_candidate(),)
    for state in (retired_round, empty_broader_round):
        curated = _apply_continuation_state(curated, state)

    metadata = curated[0].connector_metadata
    assert metadata["x_continuation_generation"] == 1
    assert metadata["x_page_start_token"] == "page-2"
    assert "x_next_token" not in metadata
