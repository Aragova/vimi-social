from vimi_social.domain.source import AdultClassification, CandidateContent
from vimi_social.source.query_planner import ScoutQueryRound
from vimi_social.source.unified_scout import (
    _merge_exact_candidates,  # pyright: ignore[reportPrivateUsage]
    _passes_query_gate,  # pyright: ignore[reportPrivateUsage]
    _prepare_search_candidate,  # pyright: ignore[reportPrivateUsage]
    _prepare_timeline_seeds,  # pyright: ignore[reportPrivateUsage]
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


def test_timeline_seed_is_first_class_source() -> None:
    prepared = _prepare_timeline_seeds((_candidate("timeline"),))

    assert len(prepared) == 1
    assert prepared[0].connector_metadata["x_candidate_origin"] == "home_timeline"
    assert prepared[0].connector_metadata["x_candidate_origins"] == ["home_timeline"]


def test_exact_duplicate_merges_timeline_origin_and_search_state() -> None:
    seed = _prepare_timeline_seeds(
        (_candidate("shared", duration_ms=1_080_000),)
    )[0]
    search = _prepare_search_candidate(
        _candidate(
            "shared",
            duration_ms=120_000,
            metadata={
                "x_search_scope": "all",
                "x_search_query": "((gay) OR (twink)) has:videos",
                "x_next_token": "next-page",
            },
        ),
        _search_round(),
        continuation_generation=0,
    )

    merged = _merge_exact_candidates((seed, search))

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


def test_similar_text_with_different_ids_is_not_deduplicated() -> None:
    first = _candidate("one", text="same promotional looking caption")
    second = _candidate("two", text="same promotional looking caption")

    merged = _merge_exact_candidates((first, second))

    assert [candidate.source_id for candidate in merged] == ["one", "two"]


def test_long_timeline_candidate_passes_calibrated_semantic_gate() -> None:
    candidate = _prepare_timeline_seeds(
        (_candidate("long", duration_ms=23 * 60 * 1000),)
    )[0]

    assert _passes_query_gate(
        candidate,
        semantic_raw=0.823,
        lexical=0.0,
        lexical_matches=0,
        minimum_relevance=0.18,
    )


def test_shorter_timeline_candidate_keeps_stricter_semantic_gate() -> None:
    candidate = _prepare_timeline_seeds(
        (_candidate("shorter", duration_ms=2 * 60 * 1000),)
    )[0]

    assert not _passes_query_gate(
        candidate,
        semantic_raw=0.823,
        lexical=0.0,
        lexical_matches=0,
        minimum_relevance=0.18,
    )
