from uuid import uuid4

from vimi_social.domain.international import UiLocale
from vimi_social.domain.source import (
    AdultClassification,
    CandidateContent,
    ScoutRunResult,
    SourceTaskState,
)
from vimi_social.telegram.scout_results import build_scout_results


def _candidate(index: int) -> CandidateContent:
    return CandidateContent(
        id=uuid4(),
        source="x",
        source_id=str(index),
        source_url=f"https://x.com/i/web/status/{index}",
        author=str(index),
        published_at=None,
        media_type="video",
        duration_ms=1000,
        width=1080,
        height=1920,
        title=(
            f"Candidate {index} with a deliberately long description that should be "
            "trimmed before it reaches the Telegram results card"
        ),
        caption=None,
        tags=(),
        engagement={"like_count": 5, "retweet_count": 2, "reply_count": 1},
        adult_classification=AdultClassification.UNKNOWN,
        explicitness_score=None,
        provenance_hint="PUBLIC_X_POST_REUSE_RIGHTS_NOT_ESTABLISHED",
        availability="DISCOVERED_METADATA_ONLY",
        connector_metadata={},
    )


def test_compact_scout_results_show_all_ten_candidates_without_raw_urls() -> None:
    candidates = tuple(_candidate(index) for index in range(1, 11))
    result = ScoutRunResult(
        operation_key="source-task:test",
        state=SourceTaskState.COMPLETED,
        discovered_count=10,
        candidate_count=10,
    )

    message = build_scout_results(UiLocale.RU, result, candidates)

    assert message.text.splitlines()[0] == "🔎 Найдено: 10"
    assert len(message.text.splitlines()) == 11
    assert "https://x.com" not in message.text
    assert "❤️" not in message.text
    assert message.text.splitlines()[-1].startswith("10. Candidate 10")
    assert len(message.keyboard) == 11

    for index, row in enumerate(message.keyboard[:-1], start=1):
        assert row[0].text.endswith(str(index))
        assert row[0].url == candidates[index - 1].source_url
        assert row[1].text.endswith(str(index))
        assert row[1].callback_data == f"candidate:select:{candidates[index - 1].id}"

    assert message.keyboard[-1][0].callback_data == "source:ai_search"
