from vimi_social.domain.source import (
    AdultClassification,
    CandidateContent,
    ScoutRefillContinuationState,
)
from vimi_social.source.continuation_state import find_scout_continuation_state
from vimi_social.source.query_planner import ScoutQueryRound
from vimi_social.source.unified_ranking import (
    merge_exact_candidates,
    passes_query_gate,
    prepare_search_candidate,
    prepare_timeline_seeds,
)
from vimi_social.source.unified_scout import (
    apply_latest_continuation_state,
    round_identity,
)


def _candidate(
    source_id: str,
    *,
    duration_ms: int = 120_000,
    text: str = "gay porn twink young scene",
    metadata: dict[str, object] | None = None,
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
        engagement={"like_count": 10},
        adult_classification=AdultClassification.UNKNOWN,
        explicitness_score=None,
        provenance_hint="PUBLIC_X_POST_REUSE_RIGHTS_NOT_ESTABLISHED",
        availability="DISCOVERED_METADATA_ONLY",
        connector_metadata=metadata or {},
    )


def _search_round() -> ScoutQueryRound:
    return ScoutQueryRound(
        query_variants=("gay", "porn", "twink", "young"),
        preferred_languages=("en",),
        relaxation_level=1,
        specificity=0.25,
        strategy="provider_or_translated",
        max_pages=2,
    )


def _prepare_search(candidate: CandidateContent) -> CandidateContent:
    search_round = _search_round()
    return prepare_search_candidate(
        candidate,
        query_variants=search_round.query_variants,
        preferred_languages=search_round.preferred_languages,
        relaxation_level=search_round.relaxation_level,
        specificity=search_round.specificity,
        strategy=search_round.strategy,
        continuation_generation=0,
    )


def test_timeline_seed_is_first_class_source() -> None:
    prepared = prepare_timeline_seeds((_candidate("timeline"),))

    assert len(prepared) == 1
    assert prepared[0].connector_metadata["x_candidate_origin"] == "home_timeline"
    assert prepared[0].connector_metadata["x_candidate_origins"] == ["home_timeline"]


def test_exact_duplicate_merges_timeline_origin_and_search_state() -> None:
    seed = prepare_timeline_seeds(
        (_candidate("shared", duration_ms=1_080_000),)
    )[0]
    search = _prepare_search(
        _candidate(
            "shared",
            duration_ms=120_000,
            metadata={
                "x_search_scope": "all",
                "x_search_query": "((gay) OR (twink)) has:videos",
                "x_next_token": "next-page",
            },
        )
    )

    merged = merge_exact_candidates((seed, search))

    assert len(merged) == 1
    candidate = merged[0]
    assert candidate.duration_ms == 1_080_000
    assert candidate.connector_metadata["x_candidate_origin"] == "home_timeline"
    assert candidate.connector_metadata["x_candidate_origins"] == [
        "home_timeline",
        "search",
    ]
    assert candidate.connector_metadata["x_search_scope"] == "all"
    assert candidate.connector_metadata["x_next_token"] == "next-page"
    assert candidate.connector_metadata["retrieval_relaxation_level"] == 1


def test_exact_duplicate_latest_search_copy_retires_old_cursor() -> None:
    older = _prepare_search(
        _candidate(
            "shared-search",
            metadata={
                "x_search_scope": "all",
                "x_search_query": "query",
                "x_next_token": "stale-page",
            },
        )
    )
    newer_round = ScoutQueryRound(
        query_variants=("gay", "twink"),
        preferred_languages=(),
        relaxation_level=2,
        specificity=0.5,
        strategy="provider_or_unrestricted",
        max_pages=1,
    )
    newer = prepare_search_candidate(
        _candidate(
            "shared-search",
            metadata={
                "x_search_scope": "all",
                "x_search_query": "new-query",
            },
        ),
        query_variants=newer_round.query_variants,
        preferred_languages=newer_round.preferred_languages,
        relaxation_level=newer_round.relaxation_level,
        specificity=newer_round.specificity,
        strategy=newer_round.strategy,
        continuation_generation=1,
    )

    merged = merge_exact_candidates((older, newer))

    assert len(merged) == 1
    metadata = merged[0].connector_metadata
    assert metadata["x_search_query"] == "new-query"
    assert metadata["retrieval_relaxation_level"] == 2
    assert metadata["x_continuation_generation"] == 1
    assert "x_next_token" not in metadata


def test_similar_text_with_different_ids_is_not_deduplicated() -> None:
    first = _candidate("one", text="same promotional looking caption")
    second = _candidate("two", text="same promotional looking caption")

    merged = merge_exact_candidates((first, second))

    assert [candidate.source_id for candidate in merged] == ["one", "two"]


def test_long_timeline_candidate_passes_calibrated_semantic_gate() -> None:
    candidate = prepare_timeline_seeds(
        (_candidate("long", duration_ms=23 * 60 * 1000),)
    )[0]

    assert passes_query_gate(
        candidate,
        semantic_raw=0.823,
        lexical=0.0,
        lexical_matches=0,
        minimum_relevance=0.18,
    )


def test_shorter_timeline_candidate_keeps_stricter_semantic_gate() -> None:
    candidate = prepare_timeline_seeds(
        (_candidate("shorter", duration_ms=2 * 60 * 1000),)
    )[0]

    assert not passes_query_gate(
        candidate,
        semantic_raw=0.823,
        lexical=0.0,
        lexical_matches=0,
        minimum_relevance=0.18,
    )


def test_round_identity_keeps_language_broadening_distinct() -> None:
    query = ("gay twink",)

    assert round_identity(query, ("en",)) != round_identity(query, ())


def test_exhausted_latest_page_retires_older_cursor() -> None:
    old = _prepare_search(
        _candidate(
            "old",
            metadata={
                "x_search_scope": "all",
                "x_search_query": "query",
                "x_next_token": "already-consumed",
            },
        )
    )
    state = ScoutRefillContinuationState(
        retrieval_query="gay",
        retrieval_query_variants=("gay", "twink"),
        retrieval_relaxation_level=1,
        retrieval_specificity=0.25,
        retrieval_language_mode="en",
        continuation_generation=1,
        page_start_token="already-consumed",
        next_token=None,
        search_scope="all",
        search_query="query",
    )

    updated = apply_latest_continuation_state((old,), state)

    assert find_scout_continuation_state(updated) is None
    assert updated[0].connector_metadata["x_continuation_generation"] == 1
    assert "x_next_token" not in updated[0].connector_metadata


def test_latest_page_cursor_survives_when_more_results_exist() -> None:
    carrier = _prepare_search(
        _candidate(
            "carrier",
            metadata={
                "x_search_scope": "all",
                "x_search_query": "query",
            },
        )
    )
    state = ScoutRefillContinuationState(
        retrieval_query="gay",
        retrieval_query_variants=("gay", "twink"),
        retrieval_relaxation_level=1,
        retrieval_specificity=0.25,
        retrieval_language_mode="en",
        continuation_generation=2,
        page_start_token="page-2",
        next_token="page-3",
        search_scope="all",
        search_query="query",
    )

    updated = apply_latest_continuation_state((carrier,), state)
    continuation = find_scout_continuation_state(updated)

    assert continuation is not None
    assert continuation.next_token == "page-3"
    assert continuation.generation == 2
