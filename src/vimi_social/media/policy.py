from collections.abc import Sequence

from vimi_social.domain.analysis import (
    AdultContentPolicy,
    DestinationProfile,
    PolicyDecision,
    PreflightDecision,
    RankedScene,
    SceneClassificationBasis,
)
from vimi_social.domain.media import BaseAdultClassification, MediaAsset

X_ORGANIC_PROFILE = DestinationProfile(
    destination="x",
    capability_version="x-organic-video-v1",
    policy_version="x-adult-2024-05-reviewed-2026-10-22",
    supports_video=True,
    max_video_duration_ms=None,
    adult_policy=AdultContentPolicy.ALLOW_LABELLED_REQUIRES_REVIEW,
)


class DestinationProfileRegistry:
    def __init__(self, profiles: tuple[DestinationProfile, ...] | None = None) -> None:
        selected = profiles or (X_ORGANIC_PROFILE,)
        self._profiles = {profile.destination: profile for profile in selected}
        if len(self._profiles) != len(selected):
            raise ValueError("destination profiles must have unique destination keys")

    def require(self, destination: str) -> DestinationProfile:
        try:
            return self._profiles[destination]
        except KeyError:
            raise KeyError(f"destination profile is not configured: {destination}") from None


class PlatformPreflight:
    def evaluate(
        self,
        asset: MediaAsset,
        profile: DestinationProfile,
        scenes: Sequence[RankedScene] = (),
    ) -> PreflightDecision:
        if not profile.supports_video:
            return _decision(
                profile,
                PolicyDecision.BLOCKED,
                False,
                ("DESTINATION_VIDEO_UNSUPPORTED",),
            )

        adult = asset.classification.adult
        if adult is BaseAdultClassification.ADULT_EXPLICIT:
            if profile.adult_policy is AdultContentPolicy.BLOCK:
                return _decision(
                    profile,
                    PolicyDecision.BLOCKED,
                    True,
                    ("ADULT_CONTENT_BLOCKED_BY_DESTINATION_PROFILE",),
                )
            return _decision(
                profile,
                PolicyDecision.MANUAL_REVIEW_REQUIRED,
                True,
                (
                    "ADULT_CONTENT_REQUIRES_SENSITIVE_LABEL",
                    "EXPLICIT_CONSENT_EVIDENCE_REQUIRES_REVIEW",
                ),
            )

        if adult in {
            BaseAdultClassification.UNKNOWN,
            BaseAdultClassification.POSSIBLY_SENSITIVE,
        }:
            return _decision(
                profile,
                PolicyDecision.MANUAL_REVIEW_REQUIRED,
                adult is BaseAdultClassification.POSSIBLY_SENSITIVE,
                ("CONTENT_CLASSIFICATION_REQUIRES_REVIEW",),
            )

        visual = tuple(
            scene
            for scene in scenes
            if scene.classification_basis is SceneClassificationBasis.VISUAL_MODERATION
        )
        if scenes and len(visual) != len(scenes):
            return _decision(
                profile,
                PolicyDecision.MANUAL_REVIEW_REQUIRED,
                False,
                ("VISUAL_CLASSIFICATION_INCOMPLETE",),
            )
        if visual:
            if any(
                scene.adult_classification is BaseAdultClassification.ADULT_EXPLICIT
                for scene in visual
            ):
                if profile.adult_policy is AdultContentPolicy.BLOCK:
                    return _decision(
                        profile,
                        PolicyDecision.BLOCKED,
                        True,
                        ("VISUAL_ADULT_CONTENT_BLOCKED_BY_DESTINATION_PROFILE",),
                    )
                return _decision(
                    profile,
                    PolicyDecision.MANUAL_REVIEW_REQUIRED,
                    True,
                    (
                        "VISUAL_ADULT_CONTENT_REQUIRES_REVIEW",
                        "VISUAL_AGE_AND_CONSENT_NOT_VERIFIED",
                    ),
                )
            if any(
                scene.adult_classification
                in {BaseAdultClassification.UNKNOWN, BaseAdultClassification.POSSIBLY_SENSITIVE}
                for scene in visual
            ):
                return _decision(
                    profile,
                    PolicyDecision.MANUAL_REVIEW_REQUIRED,
                    True,
                    ("VISUAL_CONTENT_CLASSIFICATION_REQUIRES_REVIEW",),
                )
        elif "metadata_text_only_no_adult_signal" in asset.classification.signals:
            return _decision(
                profile,
                PolicyDecision.MANUAL_REVIEW_REQUIRED,
                False,
                ("VISUAL_CLASSIFICATION_EVIDENCE_REQUIRED",),
            )

        duration = asset.probe.duration_ms
        if (
            duration is not None
            and profile.max_video_duration_ms is not None
            and duration > profile.max_video_duration_ms
        ):
            return _decision(
                profile,
                PolicyDecision.ADAPTATION_REQUIRED,
                False,
                ("VIDEO_DURATION_EXCEEDS_DESTINATION_CAPABILITY",),
            )

        return _decision(
            profile,
            PolicyDecision.DIRECT_ALLOWED,
            False,
            ("VIDEO_DIRECTLY_ELIGIBLE",),
        )


def _decision(
    profile: DestinationProfile,
    decision: PolicyDecision,
    requires_sensitive_label: bool,
    reason_codes: tuple[str, ...],
) -> PreflightDecision:
    return PreflightDecision(
        destination=profile.destination,
        decision=decision,
        capability_version=profile.capability_version,
        policy_version=profile.policy_version,
        requires_sensitive_label=requires_sensitive_label,
        reason_codes=reason_codes,
        max_video_duration_ms=profile.max_video_duration_ms,
    )
