from vimi_social.domain.source import AdultClassification, CandidateContent
from vimi_social.source.candidate_filter import filter_scout_candidates


def _candidate(
    source_id: str,
    caption: str,
    *,
    duration_ms: int | None = 600_000,
    likes: int = 0,
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
        width=1080,
        height=1920,
        title=caption,
        caption=caption,
        tags=(),
        engagement={"like_count": likes},
        adult_classification=AdultClassification.UNKNOWN,
        explicitness_score=None,
        provenance_hint="PUBLIC_X_POST_REUSE_RIGHTS_NOT_ESTABLISHED",
        availability="DISCOVERED_MEDIA_REFERENCE_AVAILABLE",
        connector_metadata={
            "preview_image_url": f"https://pbs.twimg.com/{source_id}.jpg",
            "acquisition_url": f"https://video.twimg.com/{source_id}.mp4",
        },
    )


def test_filter_rejects_known_videos_shorter_than_one_minute() -> None:
    candidates = (
        _candidate("15s", "short spam", duration_ms=15_000),
        _candidate("59s", "still too short", duration_ms=59_999),
        _candidate("60s", "minimum accepted", duration_ms=60_000),
        _candidate("10m", "long form", duration_ms=600_000),
    )

    filtered = filter_scout_candidates(candidates)

    assert [candidate.source_id for candidate in filtered] == ["60s", "10m"]


def test_filter_keeps_unknown_duration_fail_open() -> None:
    candidate = _candidate("unknown", "provider omitted duration", duration_ms=None)

    assert filter_scout_candidates((candidate,)) == (candidate,)


def test_filter_suppresses_exact_text_duplicates_across_different_posts() -> None:
    candidates = (
        _candidate("first", "Top and bottom Gay video promo repeated caption", duration_ms=300_000),
        _candidate("second", "Top and bottom Gay video promo repeated caption", duration_ms=600_000),
        _candidate("third", "A genuinely different long-form video", duration_ms=600_000),
    )

    filtered = filter_scout_candidates(candidates)

    assert [candidate.source_id for candidate in filtered] == ["second", "third"]


def test_filter_suppresses_near_duplicate_promotional_templates() -> None:
    candidates = (
        _candidate(
            "promo-1",
            "https://t.co/abc CHECK ME OUT! CHEAP SUB #onlyfans #porn #xxx #gay #self promo",
            duration_ms=420_000,
        ),
        _candidate(
            "promo-2",
            "https://t.co/xyz WOW CHECK ME OUT! CHEAP SUB #onlyfans #porn #xxx #gay #self promo",
            duration_ms=900_000,
        ),
    )

    filtered = filter_scout_candidates(candidates)

    assert [candidate.source_id for candidate in filtered] == ["promo-2"]


def test_filter_does_not_merge_distinct_content_with_some_shared_tags() -> None:
    candidates = (
        _candidate("city", "Bangkok night market walking tour #gay #video #travel #night"),
        _candidate("beach", "Pattaya beach sunset documentary #gay #video #travel #night"),
    )

    filtered = filter_scout_candidates(candidates)

    assert [candidate.source_id for candidate in filtered] == ["city", "beach"]


def test_filter_suppresses_continuation_duplicate_against_existing_results() -> None:
    existing = (
        _candidate("existing", "Top and bottom Gay video promo repeated caption"),
    )
    new = (
        _candidate("duplicate", "Top and bottom Gay video promo repeated caption"),
        _candidate("fresh", "Fresh long form twink documentary"),
    )

    filtered = filter_scout_candidates(new, existing=existing)

    assert [candidate.source_id for candidate in filtered] == ["fresh"]
