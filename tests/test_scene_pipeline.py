from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

import pytest

from vimi_social.domain.analysis import (
    AdultContentPolicy,
    DestinationProfile,
    PolicyDecision,
    SceneBoundary,
)
from vimi_social.domain.media import (
    BaseAdultClassification,
    BaseContentClassification,
    MediaAsset,
    MediaProbeResult,
)
from vimi_social.media.policy import PlatformPreflight, X_ORGANIC_PROFILE
from vimi_social.media.process_runner import ProcessResult
from vimi_social.media.scenes import SceneDetector, SceneRanker
from vimi_social.media.variant_planner import VariantPlanner


class FakeRunner:
    def __init__(self, stderr: bytes) -> None:
        self.stderr = stderr
        self.calls: list[tuple[tuple[str, ...], Path]] = []

    async def run(self, argv: Sequence[str], *, cwd: Path) -> ProcessResult:
        self.calls.append((tuple(argv), cwd))
        return ProcessResult(returncode=0, stdout=b"", stderr=self.stderr)


def _asset(
    *,
    duration_ms: int = 60_000,
    adult: BaseAdultClassification = BaseAdultClassification.NO_ADULT_SIGNAL_DETECTED,
    signals: tuple[str, ...] = ("metadata_text_only_no_adult_signal",),
) -> MediaAsset:
    return MediaAsset(
        id=uuid4(),
        tenant_id=uuid4(),
        candidate_id=uuid4(),
        preparation_id=uuid4(),
        sha256="a" * 64,
        storage_path="content/a.mp4",
        size_bytes=1234,
        media_format="mp4",
        content_type="video/mp4",
        final_url="https://video.example/a.mp4",
        probe=MediaProbeResult(
            duration_ms=duration_ms,
            width=1080,
            height=1920,
            video_codec="h264",
            audio_codec="aac",
            container="mp4",
            frame_rate=30.0,
            has_audio=True,
        ),
        classification=BaseContentClassification(
            adult=adult,
            explicitness_score=0.9 if adult is BaseAdultClassification.ADULT_EXPLICIT else None,
            classifier_version="metadata-text-v1",
            signals=signals,
        ),
    )


@pytest.mark.asyncio
async def test_scene_detector_turns_ffmpeg_cuts_into_ordered_boundaries(tmp_path: Path) -> None:
    runner = FakeRunner(
        b"[Parsed_showinfo] pts_time:5.000\n"
        b"[Parsed_showinfo] pts_time:5.200\n"
        b"[Parsed_showinfo] pts_time:14.500\n"
    )
    detector = SceneDetector(runner, min_scene_ms=750)

    scenes = await detector.detect(
        tmp_path / "asset.mp4",
        duration_ms=20_000,
        scratch_dir=tmp_path / "scratch",
    )

    assert scenes == (
        SceneBoundary(ordinal=0, start_ms=0, end_ms=5_000),
        SceneBoundary(ordinal=1, start_ms=5_000, end_ms=14_500),
        SceneBoundary(ordinal=2, start_ms=14_500, end_ms=20_000),
    )
    assert runner.calls[0][0][0] == "ffmpeg"
    assert "showinfo" in runner.calls[0][0][6]


def test_scene_ranker_is_deterministic_and_preserves_conservative_classification() -> None:
    classification = BaseContentClassification(
        adult=BaseAdultClassification.POSSIBLY_SENSITIVE,
        explicitness_score=0.4,
        classifier_version="metadata-text-v1",
        signals=("source_possibly_sensitive",),
    )
    scenes = (
        SceneBoundary(ordinal=0, start_ms=0, end_ms=2_000),
        SceneBoundary(ordinal=1, start_ms=2_000, end_ms=14_000),
        SceneBoundary(ordinal=2, start_ms=14_000, end_ms=24_000),
    )

    ranked = SceneRanker().rank(
        scenes,
        asset_duration_ms=24_000,
        classification=classification,
    )

    assert ranked[0].ordinal == 1
    assert ranked[-1].ordinal == 0
    assert all(scene.adult_classification is BaseAdultClassification.POSSIBLY_SENSITIVE for scene in ranked)
    assert all("scene_classification_inherits_asset_baseline" in scene.signals for scene in ranked)


def test_x_preflight_requires_review_for_metadata_only_and_explicit_content() -> None:
    preflight = PlatformPreflight()

    metadata_only = preflight.evaluate(_asset(), X_ORGANIC_PROFILE)
    explicit = preflight.evaluate(
        _asset(adult=BaseAdultClassification.ADULT_EXPLICIT, signals=("adult_keyword",)),
        X_ORGANIC_PROFILE,
    )

    assert metadata_only.decision is PolicyDecision.MANUAL_REVIEW_REQUIRED
    assert metadata_only.reason_codes == ("VISUAL_CLASSIFICATION_EVIDENCE_REQUIRED",)
    assert explicit.decision is PolicyDecision.MANUAL_REVIEW_REQUIRED
    assert explicit.requires_sensitive_label is True
    assert "EXPLICIT_CONSENT_EVIDENCE_REQUIRES_REVIEW" in explicit.reason_codes


def test_preflight_can_require_technical_adaptation_when_profile_has_duration_limit() -> None:
    profile = DestinationProfile(
        destination="test-platform",
        capability_version="cap-v1",
        policy_version="policy-v1",
        supports_video=True,
        max_video_duration_ms=30_000,
        adult_policy=AdultContentPolicy.ALLOW_LABELLED_REQUIRES_REVIEW,
    )
    decision = PlatformPreflight().evaluate(
        _asset(signals=("visual_classifier_clean",)),
        profile,
    )

    assert decision.decision is PolicyDecision.ADAPTATION_REQUIRED
    assert decision.max_video_duration_ms == 30_000


def test_variant_planner_keeps_review_gate_while_building_preview_recipe() -> None:
    asset = _asset(duration_ms=20_000)
    ranked = SceneRanker().rank(
        (
            SceneBoundary(ordinal=0, start_ms=0, end_ms=8_000),
            SceneBoundary(ordinal=1, start_ms=8_000, end_ms=20_000),
        ),
        asset_duration_ms=20_000,
        classification=asset.classification,
    )
    preflight = PlatformPreflight().evaluate(asset, X_ORGANIC_PROFILE)

    plan = VariantPlanner().plan(asset, ranked, preflight)

    assert plan.decision is PolicyDecision.MANUAL_REVIEW_REQUIRED
    assert plan.recipe is not None
    assert plan.recipe.strategy.value == "PASSTHROUGH"
    assert plan.recipe.expected_duration_ms == 20_000


def test_variant_planner_selects_ranked_scenes_under_adaptation_limit() -> None:
    asset = _asset(duration_ms=40_000, signals=("visual_classifier_clean",))
    ranked = SceneRanker().rank(
        (
            SceneBoundary(ordinal=0, start_ms=0, end_ms=10_000),
            SceneBoundary(ordinal=1, start_ms=10_000, end_ms=22_000),
            SceneBoundary(ordinal=2, start_ms=22_000, end_ms=40_000),
        ),
        asset_duration_ms=40_000,
        classification=asset.classification,
    )
    profile = DestinationProfile(
        destination="test-platform",
        capability_version="cap-v1",
        policy_version="policy-v1",
        supports_video=True,
        max_video_duration_ms=25_000,
        adult_policy=AdultContentPolicy.ALLOW_LABELLED_REQUIRES_REVIEW,
    )
    preflight = PlatformPreflight().evaluate(asset, profile)

    plan = VariantPlanner().plan(asset, ranked, preflight)

    assert plan.decision is PolicyDecision.ADAPTATION_REQUIRED
    assert plan.recipe is not None
    assert plan.recipe.strategy.value == "CLIP_SEQUENCE"
    assert plan.recipe.expected_duration_ms <= 25_000
    assert [segment.start_ms for segment in plan.recipe.segments] == sorted(
        segment.start_ms for segment in plan.recipe.segments
    )
