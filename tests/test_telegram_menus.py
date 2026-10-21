from uuid import uuid4

from vimi_social.domain.international import UiLocale
from vimi_social.domain.source import (
    AdultClassification,
    CandidateContent,
    ScoutRunResult,
    SourceTaskState,
)
from vimi_social.telegram.menus import (
    build_main_menu,
    build_scout_results,
    build_source_menu,
)


def test_main_menu_is_localized_without_changing_callback_contract() -> None:
    ru = build_main_menu(UiLocale.RU)
    en = build_main_menu(UiLocale.EN)

    assert "Добро пожаловать" in ru.text
    assert "Welcome" in en.text
    assert ru.keyboard[0][0].callback_data == "task:new"
    assert en.keyboard[0][0].callback_data == "task:new"


def test_source_menu_exposes_all_three_canonical_source_modes() -> None:
    menu = build_source_menu(UiLocale.RU)
    callbacks = [row[0].callback_data for row in menu.keyboard]
    assert callbacks == ["source:ai_search", "source:manual_upload", "source:feed"]


def test_scout_results_expose_view_select_and_search_more_actions() -> None:
    candidate_id = uuid4()
    candidate = CandidateContent(
        id=candidate_id,
        source="x",
        source_id="123",
        source_url="https://x.com/i/web/status/123",
        author="42",
        published_at=None,
        media_type="video",
        duration_ms=1000,
        width=1080,
        height=1920,
        title="Candidate title",
        caption="Candidate caption",
        tags=(),
        engagement={"like_count": 5, "retweet_count": 2, "reply_count": 1},
        adult_classification=AdultClassification.UNKNOWN,
        explicitness_score=None,
        provenance_hint="PUBLIC_X_POST_REUSE_RIGHTS_NOT_ESTABLISHED",
        availability="DISCOVERED_METADATA_ONLY",
        connector_metadata={},
    )
    result = ScoutRunResult(
        operation_key="source-task:test",
        state=SourceTaskState.COMPLETED,
        discovered_count=1,
        candidate_count=1,
    )

    message = build_scout_results(UiLocale.EN, result, (candidate,))

    assert "Found: 1" in message.text
    assert message.keyboard[0][0].url == candidate.source_url
    assert message.keyboard[0][1].callback_data == f"candidate:select:{candidate_id}"
    assert message.keyboard[-1][0].callback_data == "source:ai_search"
