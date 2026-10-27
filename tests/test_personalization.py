from vimi_social.domain.source import AdultClassification, CandidateContent
from vimi_social.source.personalization import PersonalizedFilteringCandidateCurator


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


def _metadata_float(candidate: CandidateContent, key: str) -> float:
    value = candidate.connector_metadata.get(key)
    assert isinstance(value, int | float) and not isinstance(value, bool)
    return float(value)
