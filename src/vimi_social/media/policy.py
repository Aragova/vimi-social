from vimi_social.domain.analysis import (
    AdultContentPolicy,
    DestinationProfile,
    PolicyDecision,
    PreflightDecision,
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
    def evaluate(self, asset: MediaAsset, profile: DestinationProfile) -> PreflightDecision:
        if not profile.supports_video:
            return PreflightDecision(
                destination=profile.destination,
                decision=PolicyDecision.BLOCKED,
                capability_version=profile.capability_version,
                policy_version=profile.policy_version,
                requires_sensitive_label=False,
                reason_codes=("DESTINATION_VIDEO_UNSUPPORTED",),
                max_video_duration_ms=profile.max_video_duration_ms,
            )

        adult = asset.classification.adult
        if adult is BaseAdultClassification.ADULT_EXPLICIT:
            if profile.adult_policy is AdultContentPolicy.BLOCK:
                decision = PolicyDecision.BLOCKED
                reasons = ("ADULT_CONTENT_BLOCKED_BY_DESTINATION_PROFILE",)
            else:
                decision = PolicyDecision.MANUAL_REVIEW_REQUIRED
                reasons = (
                    "ADULT_CONTENT_REQUIRES_SENSITIVE_LABEL",
                    "EXPLICIT_CONSENT_EVIDENCE_REQUIRES_REVIEW",
                )
            return PreflightDecision(
                destination=profile.destination,
                decision=decision,
                capability_version=profile.capability_version,
                policy_version=profile.policy_version,
                requires_sensitive_label=True,
                reason_codes=reasons,
                max_video_duration_ms=profile.max_video_duration_ms,
            )

        if adult in {
            BaseAdultClassification.UNKNOWN,
            BaseAdultClassification.POSSIBLY_SENSITIVE,
        }:
            return PreflightDecision(
                destination=profile.destination,
                decision=PolicyDecision.MANUAL_REVIEW_REQUIRED,
                capability_version=profile.capability_version,
                policy_version=profile.policy_version,
                requires_sensitive_label=(adult is BaseAdultClassification.POSSIBLY_SENSITIVE),
                reason_codes=("CONTENT_CLASSIFICATION_REQUIRES_REVIEW",),
                max_video_duration_ms=profile.max_video_duration_ms,
            )

        if "metadata_text_only_no_adult_signal" in asset.classification.signals:
            return PreflightDecision(
                destination=profile.destination,
                decision=PolicyDecision.MANUAL_REVIEW_REQUIRED,
                capability_version=profile.capability_version,
                policy_version=profile.policy_version,
                requires_sensitive_label=False,
                reason_codes=("VISUAL_CLASSIFICATION_EVIDENCE_REQUIRED",),
                max_video_duration_ms=profile.max_video_duration_ms,
            )

        duration = asset.probe.duration_ms
        if (
            duration is not None
            and profile.max_video_duration_ms is not None
            and duration > profile.max_video_duration_ms
        ):
            return PreflightDecision(
                destination=profile.destination,
                decision=PolicyDecision.ADAPTATION_REQUIRED,
                capability_version=profile.capability_version,
                policy_version=profile.policy_version,
                requires_sensitive_label=False,
                reason_codes=("VIDEO_DURATION_EXCEEDS_DESTINATION_CAPABILITY",),
                max_video_duration_ms=profile.max_video_duration_ms,
            )

        return PreflightDecision(
            destination=profile.destination,
            decision=PolicyDecision.DIRECT_ALLOWED,
            capability_version=profile.capability_version,
            policy_version=profile.policy_version,
            requires_sensitive_label=False,
            reason_codes=("VIDEO_DIRECTLY_ELIGIBLE",),
            max_video_duration_ms=profile.max_video_duration_ms,
        )
