from uuid import UUID

from vimi_social.domain.source import AdultClassification, CandidateContent
from vimi_social.source.continuation_state import find_scout_continuation_state


def _candidate(
    source_id: str,
    *,
    level: int,
    mode: str,
    token: str | None,
) -> CandidateContent:
    metadata: dict[str, object] = {
        "retrieval_query": "гей порно твинк",
        "retrieval_query_variants": ["гей порно твинк", "gay porn twink"],
        "retrieval_relaxation_level": level,
        "retrieval_specificity": 0.75,
        "retrieval_language_mode": mode,
        "x_search_scope": "recent",
        "curator_rank": int(source_id),
    }
    if token is not None:
        metadata["x_next_token"] = token
    return CandidateContent(
        id=UUID(int=int(source_id)),
        source="x",
        source_id=source_id,
        source_url=f"https://x.com/i/web/status/{source_id}",
        author=None,
        published_at=None,
        media_type="video",
        duration_ms=None,
        width=None,
        height=None,
        title="gay porn twink",
        caption=None,
        tags=(),
        engagement={},
        adult_classification=AdultClassification.UNKNOWN,
        explicitness_score=None,
        provenance_hint="PUBLIC_X_POST_REUSE_RIGHTS_NOT_ESTABLISHED",
        availability="DISCOVERED_METADATA_ONLY",
        connector_metadata=metadata,
    )


def test_continuation_uses_latest_successful_round_not_earlier_token() -> None:
    candidates = (
        _candidate("1", level=0, mode="ru", token="old-ru"),
        _candidate("2", level=0, mode="ru+en", token="old-bilingual"),
        _candidate("3", level=1, mode="ru", token="relaxed-ru"),
        _candidate("4", level=1, mode="ru+en", token="wanted-token"),
    )

    state = find_scout_continuation_state(candidates)

    assert state is not None
    assert state.next_token == "wanted-token"
    assert state.relaxation_level == 1
    assert state.preferred_languages == ("ru", "en")
    assert state.query_variants == ("гей порно твинк", "gay porn twink")


def test_continuation_is_unavailable_when_latest_round_is_exhausted() -> None:
    candidates = (
        _candidate("1", level=0, mode="ru+en", token="older-token"),
        _candidate("2", level=1, mode="ru+en", token=None),
    )

    assert find_scout_continuation_state(candidates) is None
