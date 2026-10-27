from uuid import UUID

from vimi_social.domain.international import UiLocale
from vimi_social.domain.source import AdultClassification, CandidateContent
from vimi_social.telegram.scout_results import build_scout_result_page

_TASK_ID = UUID("11111111-1111-1111-1111-111111111111")


def _candidate(index: int, *, continuation: bool = False) -> CandidateContent:
    metadata: dict[str, object] = {"curator_rank": index + 1}
    if continuation:
        metadata.update(
            {
                "retrieval_query": "gay twink porno",
                "retrieval_query_variants": ["gay twink porno"],
                "retrieval_relaxation_level": 0,
                "retrieval_specificity": 1.0,
                "retrieval_language_mode": "en",
                "x_search_scope": "recent",
                "x_next_token": "next-page",
            }
        )
    return CandidateContent(
        id=UUID(int=index + 1),
        source="x",
        source_id=str(index + 1),
        source_url=f"https://x.com/i/web/status/{index + 1}",
        author=str(index % 3),
        published_at=None,
        media_type="video",
        duration_ms=12000,
        width=720,
        height=1280,
        title=f"Result {index + 1}",
        caption=None,
        tags=(),
        engagement={},
        adult_classification=AdultClassification.UNKNOWN,
        explicitness_score=None,
        provenance_hint="PUBLIC_X_POST_REUSE_RIGHTS_NOT_ESTABLISHED",
        availability="DISCOVERED_METADATA_ONLY",
        connector_metadata=metadata,
    )


def test_second_scout_page_keeps_global_result_numbers() -> None:
    candidates = tuple(_candidate(index) for index in range(25))

    message = build_scout_result_page(
        UiLocale.RU,
        candidates,
        task_id=_TASK_ID,
        page=1,
    )

    assert "🔎 Найдено: 25" in message.text
    assert "Страница 2/3" in message.text
    assert "11. Result 11" in message.text
    assert "20. Result 20" in message.text
    assert "10. Result 10" not in message.text
    assert "21. Result 21" not in message.text

    callbacks = [
        button.callback_data
        for row in message.keyboard
        for button in row
        if button.callback_data is not None
    ]
    assert f"scout:page:{_TASK_ID}:0" in callbacks
    assert f"scout:page:{_TASK_ID}:2" in callbacks
    assert any(value.startswith("candidate:select:") for value in callbacks)
    assert f"scout:more:{_TASK_ID}" not in callbacks


def test_last_scout_page_shows_remaining_results_without_padding() -> None:
    candidates = tuple(_candidate(index) for index in range(25))

    message = build_scout_result_page(
        UiLocale.EN,
        candidates,
        task_id=_TASK_ID,
        page=2,
    )

    assert "Page 3/3" in message.text
    assert "21. Result 21" in message.text
    assert "25. Result 25" in message.text
    assert "26." not in message.text


def test_scout_page_offers_continuation_only_when_x_next_token_exists() -> None:
    candidates = tuple(
        _candidate(index, continuation=index == 0)
        for index in range(12)
    )

    message = build_scout_result_page(
        UiLocale.RU,
        candidates,
        task_id=_TASK_ID,
        page=1,
    )

    callbacks = [
        button.callback_data
        for row in message.keyboard
        for button in row
        if button.callback_data is not None
    ]
    labels = [button.text for row in message.keyboard for button in row]
    assert f"scout:more:{_TASK_ID}" in callbacks
    assert "🔎 Ещё результаты" in labels
