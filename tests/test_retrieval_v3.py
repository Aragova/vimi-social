import pytest

from vimi_social.domain.source import AdultClassification, CandidateContent
from vimi_social.source.query_planner import MultilingualQueryPlanner
from vimi_social.source.retrieval_v3 import (
    ConceptQueryPlanner,
    RetrievalV3CandidateCurator,
    retrieval_target_view,
)


def _candidate(
    source_id: str,
    *,
    text: str,
    duration_ms: int | None,
) -> CandidateContent:
    return CandidateContent(
        id=None,
        source="x",
        source_id=source_id,
        source_url=f"https://x.com/i/web/status/{source_id}",
        author=f"author-{source_id}",
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
        connector_metadata={
            "acquisition_url": f"https://video.example/{source_id}.mp4",
            "language": "en",
            "retrieval_specificity": 0.5,
        },
    )


@pytest.mark.asyncio
async def test_concept_planner_searches_token_pairs_before_broad_or() -> None:
    planner = ConceptQueryPlanner(MultilingualQueryPlanner())
    plan = await planner.plan("gay porn twink young", ("en",))

    rounds = [
        search_round
        async for search_round in planner.search_rounds(
            plan,
            "gay porn twink young",
            ("en",),
        )
    ]

    assert rounds[0].strategy == "provider_concept_recall"
    assert rounds[0].query_variants == (
        "porn twink",
        "twink young",
        "gay twink",
    )
    assert rounds[0].preferred_languages == ("en",)
    assert rounds[0].max_pages == 1
    assert [item.relaxation_level for item in rounds] == list(range(1, len(rounds) + 1))
    assert len({item.relaxation_level for item in rounds}) == len(rounds)
    assert any(search_round.strategy == "provider_or_primary" for search_round in rounds[1:])


def test_retrieval_target_stays_open_when_ten_results_are_only_one_to_five_minutes() -> None:
    short_pool = tuple(
        _candidate(
            f"short-{index}",
            text=f"gay porn twink young scene {index}",
            duration_ms=120_000,
        )
        for index in range(10)
    )

    target_view = retrieval_target_view(short_pool)

    assert len(target_view) == 9


def test_retrieval_target_can_stop_after_three_preferred_long_form_results() -> None:
    candidates = tuple(
        _candidate(
            f"long-{index}",
            text=f"gay porn twink young long scene {index}",
            duration_ms=600_000,
        )
        for index in range(3)
    ) + tuple(
        _candidate(
            f"short-{index}",
            text=f"gay porn twink young short scene {index}",
            duration_ms=120_000,
        )
        for index in range(7)
    )

    target_view = retrieval_target_view(candidates)

    assert len(target_view) == 10


def test_v3_ranking_demotes_link_farm_without_relevance_gate_bypass() -> None:
    curator = RetrievalV3CandidateCurator()
    legitimate = _candidate(
        "legitimate",
        text="young gay porn twink full scene",
        duration_ms=600_000,
    )
    link_farm = _candidate(
        "link-farm",
        text=(
            "Young Twink Best Gay Porn Sites: "
            "https://t.co/example1 https://t.co/example2"
        ),
        duration_ms=600_000,
    )

    ranked = curator.rank(
        (link_farm, legitimate),
        query_variants=("gay porn twink young",),
        preferred_languages=("en",),
        limit=2,
    )

    assert [candidate.source_id for candidate in ranked] == ["legitimate", "link-farm"]
    first_penalty = ranked[0].connector_metadata["curator_spam_penalty_score"]
    second_penalty = ranked[1].connector_metadata["curator_spam_penalty_score"]
    first_score = ranked[0].connector_metadata["curator_v3_score"]
    second_score = ranked[1].connector_metadata["curator_v3_score"]
    assert isinstance(first_penalty, int | float) and not isinstance(first_penalty, bool)
    assert isinstance(second_penalty, int | float) and not isinstance(second_penalty, bool)
    assert isinstance(first_score, int | float) and not isinstance(first_score, bool)
    assert isinstance(second_score, int | float) and not isinstance(second_score, bool)
    assert float(first_penalty) == 0.0
    assert float(second_penalty) > 0.0
    assert float(first_score) > float(second_score)
