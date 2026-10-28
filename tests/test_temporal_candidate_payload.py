from datetime import UTC, datetime

import pytest
from temporalio.converter import DataConverter

from vimi_social.domain.source import (
    AdultClassification,
    CandidateContent,
    ScoutWorkflowInput,
    XTimelineSeedResult,
)
from vimi_social.source.timeline_wire import to_temporal_safe_timeline_candidate


def _timeline_candidate() -> CandidateContent:
    return CandidateContent(
        id=None,
        source="x",
        source_id="timeline-1",
        source_url="https://x.com/i/web/status/timeline-1",
        author="creator",
        published_at=datetime(2026, 10, 27, 12, 0, tzinfo=UTC),
        media_type="video",
        duration_ms=600_000,
        width=1920,
        height=1080,
        title="long form creator video",
        caption="long form creator video",
        tags=("twink",),
        engagement={"like_count": 42},
        adult_classification=AdultClassification.UNKNOWN,
        explicitness_score=None,
        provenance_hint="PUBLIC_X_POST_REUSE_RIGHTS_NOT_ESTABLISHED",
        availability="DISCOVERED_METADATA_ONLY",
        connector_metadata={
            "x_candidate_origin": "home_timeline",
            "acquisition_reference": {
                "url": "https://video.example/high.mp4",
                "bit_rate": 2_000_000,
            },
            "retrieval_specificity": 0.0,
        },
    )


def _wire_candidate() -> CandidateContent:
    return to_temporal_safe_timeline_candidate(_timeline_candidate())


def test_timeline_wire_preserves_timestamp_as_iso_metadata() -> None:
    candidate = _wire_candidate()
    assert candidate.published_at is None
    assert candidate.connector_metadata["x_published_at_iso"] == "2026-10-27T12:00:00+00:00"


@pytest.mark.asyncio
async def test_timeline_seed_result_round_trips_through_temporal_converter() -> None:
    candidate = _wire_candidate()
    expected = XTimelineSeedResult(candidates=(candidate,), posts_read=1)

    payloads = await DataConverter.default.encode([expected])
    decoded = await DataConverter.default.decode(payloads, [XTimelineSeedResult])

    assert decoded == [expected]


@pytest.mark.asyncio
async def test_scout_workflow_input_with_timeline_seed_round_trips_temporal_converter() -> None:
    candidate = _wire_candidate()
    expected = ScoutWorkflowInput(
        operation_key="source-task:test",
        execution_token="00000000-0000-0000-0000-000000000001",
        seed_candidates=(candidate,),
        seed_posts_read=1,
        seed_failure_code="TIMELINE_UNAVAILABLE",
    )

    payloads = await DataConverter.default.encode([expected])
    decoded = await DataConverter.default.decode(payloads, [ScoutWorkflowInput])

    assert decoded == [expected]