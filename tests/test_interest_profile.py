from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from vimi_social.domain.identity import TenantId
from vimi_social.domain.interest import (
    UserInterestProfile,
    XInterestList,
    XInterestPost,
    XInterestSnapshot,
    XInterestUser,
)
from vimi_social.domain.source import AdultClassification, CandidateContent
from vimi_social.source.interest_profile import (
    apply_interest_profile,
    build_interest_profile,
)


def _candidate(
    source_id: str,
    caption: str,
    *,
    author: str | None,
) -> CandidateContent:
    return CandidateContent(
        id=None,
        source="x",
        source_id=source_id,
        source_url=f"https://x.com/i/web/status/{source_id}",
        author=author,
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
        connector_metadata={},
    )


def _profile() -> UserInterestProfile:
    return UserInterestProfile(
        tenant_id=TenantId.parse("00000000-0000-0000-0000-000000000001"),
        user_id=UUID("00000000-0000-0000-0000-000000000002"),
        destination_account_id=UUID("00000000-0000-0000-0000-000000000003"),
        external_account_id="x-user-1",
        term_weights={"twink": 1.0, "cinematic": 0.4},
        hashtag_weights={"twink": 1.0},
        author_weights={"fav-author": 1.0},
        source_stats={"bookmarks": 10},
        sample_size=10,
        generated_at=datetime(2026, 10, 27, tzinfo=UTC),
    )


def test_bookmarks_contribute_stronger_taste_signal_than_likes_and_following() -> None:
    snapshot = XInterestSnapshot(
        user_id="me",
        following=(
            XInterestUser(id="follow-author", description="travel documentary"),
        ),
        liked_posts=(
            XInterestPost(
                id="liked",
                text="city nightlife #night",
                author_id="liked-author",
            ),
        ),
        bookmarked_posts=(
            XInterestPost(
                id="saved",
                text="twink documentary #twink",
                author_id="saved-author",
            ),
        ),
        lists=(XInterestList(id="list-1", name="Long video creators"),),
        list_posts=(
            XInterestPost(
                id="list-post",
                text="cinematic long form",
                author_id="list-author",
            ),
        ),
    )

    draft = build_interest_profile(snapshot)

    assert draft.author_weights["saved-author"] == 1.0
    assert draft.author_weights["liked-author"] < draft.author_weights["saved-author"]
    assert draft.author_weights["follow-author"] < draft.author_weights["liked-author"]
    assert draft.hashtag_weights["twink"] == 1.0
    assert draft.term_weights["twink"] > 0
    assert draft.source_stats == {
        "following": 1,
        "likes": 1,
        "bookmarks": 1,
        "lists": 1,
        "list_posts": 1,
    }
    assert draft.sample_size == 5


def test_candidate_affinity_is_explainable_and_zero_for_unrelated_content() -> None:
    matching = apply_interest_profile(
        _candidate(
            "matching",
            "A cinematic #twink long form video",
            author="fav-author",
        ),
        _profile(),
    )
    unrelated = apply_interest_profile(
        _candidate("other", "Bangkok street food market", author="other-author"),
        _profile(),
    )

    assert _metadata_float(matching, "personal_affinity_score") > 0.8
    reasons = _metadata_strings(matching, "personal_affinity_reasons")
    assert "author:fav-author" in reasons
    assert "hashtag:twink" in reasons
    assert _metadata_float(unrelated, "personal_affinity_score") == 0.0


def _metadata_float(candidate: CandidateContent, key: str) -> float:
    value = candidate.connector_metadata.get(key)
    assert isinstance(value, int | float) and not isinstance(value, bool)
    return float(value)


def _metadata_strings(candidate: CandidateContent, key: str) -> tuple[str, ...]:
    value = candidate.connector_metadata.get(key)
    assert isinstance(value, list)
    items = cast(list[object], value)
    assert all(isinstance(item, str) for item in items)
    return tuple(item for item in items if isinstance(item, str))
