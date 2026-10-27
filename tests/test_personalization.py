from datetime import UTC, datetime
from uuid import UUID

import pytest

from vimi_social.domain.identity import TenantId
from vimi_social.domain.interest import UserInterestProfile
from vimi_social.domain.source import AdultClassification, CandidateContent
from vimi_social.source.personalization import (
    PersonalizedFilteringCandidateCurator,
    _cache_taste_semantic_scores,  # pyright: ignore[reportPrivateUsage]
)


def _candidate(
    source_id: str,
    caption: str,
    *,
    affinity: float,
    specificity: float = 1.0,
) -> CandidateContent:
    return CandidateContent(
        id=None,
        source="x",
        source_id=source_id,
        source_url=f"https://x.com/i/web/status/{source_id}",
        author=source_id,
        published_at=None,
        media_type="video",
        duration_ms=600_000,
        width=1920,
        height=1080,
        title=caption,
        caption=caption,
        tags=(),
        engagement={},
        adult_classification=AdultClassification.UNKNOWN,
        explicitness_score=None,
        provenance_hint="PUBLIC_X_POST_REUSE_RIGHTS_NOT_ESTABLISHED",
        availability="DISCOVERED_MEDIA_REFERENCE_AVAILABLE",
        connector_metadata={
            "personal_affinity_score": affinity,
            "retrieval_specificity": specificity,
        },
    )


def _profile() -> UserInterestProfile:
    return UserInterestProfile(
        tenant_id=TenantId.parse("00000000-0000-0000-0000-000000000001"),
        user_id=UUID("00000000-0000-0000-0000-000000000002"),
        destination_account_id=UUID("00000000-0000-0000-0000-000000000003"),
        external_account_id="x-user-1",
        term_weights={"twink": 1.0, "cinematic": 0.4},
        hashtag_weights={"twink": 1.0},
        author_weights={"preferred": 1.0},
        source_stats={"bookmarks": 10},
        sample_size=10,
        generated_at=datetime(2026, 10, 27, tzinfo=UTC),
    )


class _FakeSemanticScorer:
    def __init__(self) -> None:
        self.calls = 0

    async def score_candidates(
        self,
        query_variants: tuple[str, ...],
        candidates: tuple[CandidateContent, ...],
    ) -> tuple[float, ...]:
        self.calls += 1
        assert query_variants == ("user interests: twink cinematic",)
        return tuple(0.8 for _ in candidates)

    async def score_texts(
        self,
        query_variants: tuple[str, ...],
        texts: tuple[str | None, ...],
    ) -> tuple[float | None, ...]:
        del query_variants, texts
        return ()


def test_taste_affinity_breaks_ties_between_relevant_candidates() -> None:
    ordinary = _candidate(
        "ordinary",
        "Bangkok nightlife walking documentary",
        affinity=0.0,
    )
    preferred = _candidate(
        "preferred",
        "Bangkok nightlife rooftop documentary",
        affinity=1.0,
    )

    ranked = PersonalizedFilteringCandidateCurator().rank(
        (ordinary, preferred),
        query_variants=("Bangkok nightlife",),
        preferred_languages=("en",),
        limit=10,
    )

    assert [candidate.source_id for candidate in ranked] == ["preferred", "ordinary"]
    assert _metadata_float(ranked[0], "curator_personal_affinity_score") == 1.0
    preferred_score = _metadata_float(ranked[0], "curator_personalized_score")
    ordinary_score = _metadata_float(ranked[1], "curator_personalized_score")
    assert preferred_score > ordinary_score


def test_taste_affinity_cannot_rescue_irrelevant_broadened_candidate() -> None:
    irrelevant = _candidate(
        "irrelevant",
        "Completely unrelated cooking tutorial",
        affinity=1.0,
        specificity=0.25,
    )

    ranked = PersonalizedFilteringCandidateCurator().rank(
        (irrelevant,),
        query_variants=("Bangkok nightlife",),
        preferred_languages=("en",),
        limit=10,
    )

    assert ranked == ()


@pytest.mark.asyncio
async def test_e5_taste_scores_are_cached_within_one_scout_run() -> None:
    scorer = _FakeSemanticScorer()
    candidate = _candidate(
        "candidate-1",
        "young creator long form video",
        affinity=0.0,
    )
    cache: dict[tuple[str, str], float] = {}

    await _cache_taste_semantic_scores(
        scorer,
        _profile(),
        cache,
        (candidate,),
    )
    await _cache_taste_semantic_scores(
        scorer,
        _profile(),
        cache,
        (candidate,),
    )

    assert scorer.calls == 1
    assert cache == {("x", "candidate-1"): 0.8}


def _metadata_float(candidate: CandidateContent, key: str) -> float:
    value = candidate.connector_metadata.get(key)
    assert isinstance(value, int | float) and not isinstance(value, bool)
    return float(value)
