from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from vimi_social.domain.identity import OperationKey, TenantId


class PublicationState(StrEnum):
    REQUESTED = "REQUESTED"
    RESERVED = "RESERVED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    READY = "READY"
    DISPATCHING = "DISPATCHING"
    PROVIDER_ACCEPTED = "PROVIDER_ACCEPTED"
    UNKNOWN = "UNKNOWN"
    CONFIRMED = "CONFIRMED"
    FAILED_SAFE = "FAILED_SAFE"
    FAILED_PERMANENT = "FAILED_PERMANENT"
    BLOCKED = "BLOCKED"


class VariantArtifactState(StrEnum):
    QUEUED = "QUEUED"
    RENDERING = "RENDERING"
    READY = "READY"
    FAILED_SAFE = "FAILED_SAFE"


class DestinationAccountState(StrEnum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"


class PublicationPreviewState(StrEnum):
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCKED = "BLOCKED"
    NO_DESTINATION = "NO_DESTINATION"
    ACCOUNT_SELECTION_REQUIRED = "ACCOUNT_SELECTION_REQUIRED"
    RENDER_FAILED = "RENDER_FAILED"


class ProviderMutationKind(StrEnum):
    CONFIRMED = "CONFIRMED"
    PROVIDER_ACCEPTED = "PROVIDER_ACCEPTED"
    FAILED_SAFE = "FAILED_SAFE"
    FAILED_PERMANENT = "FAILED_PERMANENT"
    UNKNOWN = "UNKNOWN"


class ReconciliationKind(StrEnum):
    CONFIRMED = "CONFIRMED"
    PENDING = "PENDING"
    PROVED_ABSENT = "PROVED_ABSENT"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True, slots=True)
class PublicationCommand:
    tenant_id: TenantId
    operation_key: OperationKey
    target_id: str
    metric: str
    quantity: int = 1

    def __post_init__(self) -> None:
        if not self.target_id.strip():
            raise ValueError("target_id must not be empty")
        if not self.metric.strip():
            raise ValueError("metric must not be empty")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")


@dataclass(frozen=True, slots=True)
class VariantArtifact:
    id: UUID
    tenant_id: UUID
    plan_id: UUID
    asset_id: UUID
    operation_key: str
    state: VariantArtifactState
    render_attempt_token: UUID | None
    sha256: str | None
    storage_path: str | None
    size_bytes: int | None
    duration_ms: int | None
    failure_code: str | None


@dataclass(frozen=True, slots=True)
class DestinationAccount:
    id: UUID
    tenant_id: UUID
    platform: str
    external_account_id: str
    display_name: str | None
    credential_ref: str
    state: DestinationAccountState


@dataclass(frozen=True, slots=True)
class PublicationOperation:
    id: UUID
    tenant_id: UUID
    artifact_id: UUID
    destination_account_id: UUID
    operation_key: str
    state: PublicationState
    publish_attempt_token: UUID | None
    caption: str
    remote_media_id: str | None
    remote_post_id: str | None
    failure_code: str | None


@dataclass(frozen=True, slots=True)
class RenderResult:
    state: VariantArtifactState
    artifact_id: str | None = None
    failure_code: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    duration_ms: int | None = None


@dataclass(frozen=True, slots=True)
class PublicationPreviewResult:
    state: PublicationPreviewState
    artifact_id: str | None = None
    publication_id: str | None = None
    destination: str | None = None
    destination_name: str | None = None
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderMutationResult:
    kind: ProviderMutationKind
    remote_media_id: str | None = None
    remote_post_id: str | None = None
    failure_code: str | None = None


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    kind: ReconciliationKind
    remote_post_id: str | None = None


@dataclass(frozen=True, slots=True)
class PublicationWorkflowInput:
    publication_id: str
    operation_key: str
    source_task_operation_key: str
    source_task_execution_token: str
    destination_task_queue: str = "vimi-social-destination"


@dataclass(frozen=True, slots=True)
class PublicationResult:
    state: PublicationState
    publication_id: str
    remote_post_id: str | None = None
    failure_code: str | None = None
