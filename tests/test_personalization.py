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
    assert ranked[0].connector_metadata["curator_personal_affinity_score"] == 1.0
    assert ranked[0].connector_metadata["curator_personalized_score"] > ranked[1].connector_metadata[
        "curator_personalized_score"
    ]


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
