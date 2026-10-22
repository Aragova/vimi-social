from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from vimi_social.domain.media import BaseAdultClassification


class SceneAnalysisState(StrEnum):
    QUEUED = "QUEUED"
    ANALYZING = "ANALYZING"
    READY = "READY"
    FAILED_SAFE = "FAILED_SAFE"


class SceneClassificationBasis(StrEnum):
    ASSET_LEVEL_INHERITED = "ASSET_LEVEL_INHERITED"


class PolicyDecision(StrEnum):
    DIRECT_ALLOWED = "DIRECT_ALLOWED"
    ADAPTATION_REQUIRED = "ADAPTATION_REQUIRED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    BLOCKED = "BLOCKED"


class RenderStrategy(StrEnum):
    PASSTHROUGH = "PASSTHROUGH"
    CLIP_SEQUENCE = "CLIP_SEQUENCE"


class AdultContentPolicy(StrEnum):
    ALLOW_LABELLED_REQUIRES_REVIEW = "ALLOW_LABELLED_REQUIRES_REVIEW"
    BLOCK = "BLOCK"


@dataclass(frozen=True, slots=True)
class SceneBoundary:
    ordinal: int
    start_ms: int
    end_ms: int


@dataclass(frozen=True, slots=True)
class RankedScene:
    ordinal: int
    start_ms: int
    end_ms: int
    rank_score: float
    adult_classification: BaseAdultClassification
    explicitness_score: float | None
    classification_basis: SceneClassificationBasis
    signals: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DestinationProfile:
    destination: str
    capability_version: str
    policy_version: str
    supports_video: bool
    max_video_duration_ms: int | None
    adult_policy: AdultContentPolicy


@dataclass(frozen=True, slots=True)
class PreflightDecision:
    destination: str
    decision: PolicyDecision
    capability_version: str
    policy_version: str
    requires_sensitive_label: bool
    reason_codes: tuple[str, ...]
    max_video_duration_ms: int | None


@dataclass(frozen=True, slots=True)
class RenderSegment:
    scene_ordinal: int
    start_ms: int
    end_ms: int
    rank_score: float


@dataclass(frozen=True, slots=True)
class RenderRecipe:
    strategy: RenderStrategy
    expected_duration_ms: int
    segments: tuple[RenderSegment, ...]


@dataclass(frozen=True, slots=True)
class VariantPlan:
    destination: str
    decision: PolicyDecision
    capability_version: str
    policy_version: str
    planner_version: str
    requires_sensitive_label: bool
    reason_codes: tuple[str, ...]
    recipe: RenderRecipe | None


@dataclass(frozen=True, slots=True)
class MediaAnalysis:
    id: UUID
    tenant_id: UUID
    asset_id: UUID
    preparation_id: UUID
    operation_key: str
    state: SceneAnalysisState
    analysis_attempt_token: UUID | None
    detector_version: str | None
    ranker_version: str | None
    failure_code: str | None


@dataclass(frozen=True, slots=True)
class MediaAnalysisResult:
    state: SceneAnalysisState
    failure_code: str | None = None
    analysis_id: str | None = None
    scene_count: int = 0
    top_scene_start_ms: int | None = None
    top_scene_end_ms: int | None = None
    destination: str | None = None
    policy_decision: PolicyDecision | None = None
    policy_version: str | None = None
    render_strategy: RenderStrategy | None = None
    planned_duration_ms: int | None = None
    requires_sensitive_label: bool = False
