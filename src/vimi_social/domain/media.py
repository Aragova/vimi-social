from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class RightsBasis(StrEnum):
    UNKNOWN = "UNKNOWN"
    USER_CONFIRMED = "USER_CONFIRMED"
    CONNECTOR_AUTHORIZED = "CONNECTOR_AUTHORIZED"
    OWNED_SOURCE = "OWNED_SOURCE"
    LICENSED_SOURCE = "LICENSED_SOURCE"


class MediaPreparationState(StrEnum):
    AWAITING_RIGHTS = "AWAITING_RIGHTS"
    QUEUED = "QUEUED"
    ACQUIRING = "ACQUIRING"
    READY = "READY"
    FAILED_SAFE = "FAILED_SAFE"
    BLOCKED = "BLOCKED"


class BaseAdultClassification(StrEnum):
    UNKNOWN = "UNKNOWN"
    NO_ADULT_SIGNAL_DETECTED = "NO_ADULT_SIGNAL_DETECTED"
    POSSIBLY_SENSITIVE = "POSSIBLY_SENSITIVE"
    ADULT_EXPLICIT = "ADULT_EXPLICIT"


class CuratorDecision(StrEnum):
    RIGHTS_REVIEW_REQUIRED = "RIGHTS_REVIEW_REQUIRED"
    ACQUISITION_ALLOWED = "ACQUISITION_ALLOWED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class MediaPreparation:
    id: UUID
    tenant_id: UUID
    candidate_id: UUID
    operation_key: str
    rights_basis: RightsBasis
    state: MediaPreparationState
    failure_code: str | None
    source_task_operation_key: str
    source_task_execution_token: UUID


@dataclass(frozen=True, slots=True)
class MediaProbeResult:
    duration_ms: int | None
    width: int | None
    height: int | None
    video_codec: str | None
    audio_codec: str | None
    container: str | None
    frame_rate: float | None
    has_audio: bool


@dataclass(frozen=True, slots=True)
class BaseContentClassification:
    adult: BaseAdultClassification
    explicitness_score: float | None
    classifier_version: str
    signals: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MediaAsset:
    id: UUID
    tenant_id: UUID
    candidate_id: UUID
    preparation_id: UUID
    sha256: str
    storage_path: str
    size_bytes: int
    media_format: str
    content_type: str
    final_url: str
    probe: MediaProbeResult
    classification: BaseContentClassification


@dataclass(frozen=True, slots=True)
class CuratorAssessment:
    decision: CuratorDecision
    acquisition_url: str | None
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MediaPreparationWorkflowInput:
    preparation_id: str
    operation_key: str
    source_task_operation_key: str
    source_task_execution_token: str


@dataclass(frozen=True, slots=True)
class MediaPreparationResult:
    preparation_id: str
    state: MediaPreparationState
    failure_code: str | None = None
    asset_id: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    duration_ms: int | None = None
    width: int | None = None
    height: int | None = None
    adult_classification: BaseAdultClassification = BaseAdultClassification.UNKNOWN
    explicitness_score: float | None = None
    signals: tuple[str, ...] = ()


JsonObject = Mapping[str, object]
