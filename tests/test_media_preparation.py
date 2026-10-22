import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from vimi_social.domain.media import (
    BaseAdultClassification,
    CuratorDecision,
    RightsBasis,
)
from vimi_social.domain.source import AdultClassification, CandidateContent
from vimi_social.media.classifier import BasicContentClassifier
from vimi_social.media.curator import CandidateCurator
from vimi_social.media.probe import MediaProbe
from vimi_social.media.process_runner import ProcessResult


class FakeToolRunner:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload
        self.calls: list[tuple[tuple[str, ...], Path]] = []

    async def run(self, argv: Sequence[str], *, cwd: Path) -> ProcessResult:
        self.calls.append((tuple(argv), cwd))
        return ProcessResult(
            returncode=0,
            stdout=json.dumps(self._payload).encode(),
            stderr=b"",
        )


def _candidate(
    *,
    caption: str = "training clip",
    sensitive: bool = False,
    acquisition_url: str | None = "https://video.example/file.mp4",
) -> CandidateContent:
    metadata: dict[str, object] = {}
    if acquisition_url is not None:
        metadata["acquisition_url"] = acquisition_url
    return CandidateContent(
        id=None,
        source="x",
        source_id="123",
        source_url="https://x.com/i/web/status/123",
        author="42",
        published_at=None,
        media_type="video",
        duration_ms=12500,
        width=1080,
        height=1920,
        title="Training",
        caption=caption,
        tags=("fitness",),
        engagement={"like_count": 10},
        adult_classification=(
            AdultClassification.POSSIBLY_SENSITIVE if sensitive else AdultClassification.UNKNOWN
        ),
        explicitness_score=None,
        provenance_hint="PUBLIC_X_POST_REUSE_RIGHTS_NOT_ESTABLISHED",
        availability="DISCOVERED_MEDIA_REFERENCE_AVAILABLE",
        connector_metadata=metadata,
    )


def test_curator_requires_rights_before_exposing_acquisition_url() -> None:
    curator = CandidateCurator()
    candidate = _candidate()

    pending = curator.assess(candidate, RightsBasis.UNKNOWN)
    allowed = curator.assess(candidate, RightsBasis.USER_CONFIRMED)

    assert pending.decision is CuratorDecision.RIGHTS_REVIEW_REQUIRED
    assert pending.acquisition_url is None
    assert allowed.decision is CuratorDecision.ACQUISITION_ALLOWED
    assert allowed.acquisition_url == "https://video.example/file.mp4"


def test_curator_blocks_missing_permitted_media_reference_even_after_rights() -> None:
    assessment = CandidateCurator().assess(
        _candidate(acquisition_url=None),
        RightsBasis.USER_CONFIRMED,
    )

    assert assessment.decision is CuratorDecision.BLOCKED
    assert assessment.acquisition_url is None


def test_base_classifier_is_conservative_and_preserves_sensitive_signal() -> None:
    classifier = BasicContentClassifier()

    clean = classifier.classify(_candidate())
    sensitive = classifier.classify(_candidate(sensitive=True))
    explicit = classifier.classify(_candidate(caption="NSFW nude video"))

    assert clean.adult is BaseAdultClassification.NO_ADULT_SIGNAL_DETECTED
    assert "metadata_text_only_no_adult_signal" in clean.signals
    assert sensitive.adult is BaseAdultClassification.POSSIBLY_SENSITIVE
    assert "source_possibly_sensitive" in sensitive.signals
    assert explicit.adult is BaseAdultClassification.ADULT_EXPLICIT
    assert explicit.explicitness_score == 0.85


@pytest.mark.asyncio
async def test_media_probe_extracts_deterministic_technical_metadata(tmp_path: Path) -> None:
    runner = FakeToolRunner(
        {
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1080,
                    "height": 1920,
                    "avg_frame_rate": "30000/1001",
                },
                {"codec_type": "audio", "codec_name": "aac"},
            ],
            "format": {
                "duration": "12.500000",
                "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
            },
        }
    )
    probe = MediaProbe(runner)
    media_path = tmp_path / "asset.mp4"

    result = await probe.probe(media_path, scratch_dir=tmp_path / "scratch")

    assert result.duration_ms == 12500
    assert result.width == 1080
    assert result.height == 1920
    assert result.video_codec == "h264"
    assert result.audio_codec == "aac"
    assert result.has_audio is True
    assert result.frame_rate is not None
    assert abs(result.frame_rate - (30000 / 1001)) < 1e-8
    assert runner.calls[0][0][0] == "ffprobe"
    assert "--" in runner.calls[0][0]
