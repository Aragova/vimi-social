from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from vimi_social.domain.identity import OperationKey, TenantId


class SourceMode(StrEnum):
    AI_SEARCH = "AI_SEARCH"
    MANUAL_UPLOAD = "MANUAL_UPLOAD"
    SOURCE_FEED = "SOURCE_FEED"


class SourceTaskState(StrEnum):
    QUEUED = "QUEUED"
    SCOUTING = "SCOUTING"
    COMPLETED = "COMPLETED"
    FAILED_SAFE = "FAILED_SAFE"
    UNKNOWN = "UNKNOWN"


class AdultClassification(StrEnum):
    UNKNOWN = "UNKNOWN"
    POSSIBLY_SENSITIVE = "POSSIBLY_SENSITIVE"


@dataclass(frozen=True, slots=True)
class SourceTask:
    id: UUID
    tenant_id: TenantId
    actor_user_id: UUID
    operation_key: OperationKey
    execution_token: UUID
    source_mode: SourceMode
    user_intent: str
    requested_sources: tuple[str, ...]
    preferred_languages: tuple[str, ...]
    state: SourceTaskState
    failure_code: str | None
    telegram_update_id: int | None
    telegram_message_id: int | None
    telegram_chat_id: int | None
    locale: str


@dataclass(frozen=True, slots=True)
class CandidateContent:
    id: UUID | None
    source: str
    source_id: str
    source_url: str
    author: str | None
    published_at: datetime | None
    media_type: str
    duration_ms: int | None
    width: int | None
    height: int | None
    title: str | None
    caption: str | None
    tags: tuple[str, ...]
    engagement: Mapping[str, int]
    adult_classification: AdultClassification
    explicitness_score: float | None
    provenance_hint: str
    availability: str
    connector_metadata: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ScoutSearchRequest:
    intent: str
    requested_sources: tuple[str, ...]
    preferred_languages: tuple[str, ...]
    max_results: int = 10

    def __post_init__(self) -> None:
        if not self.intent.strip():
            raise ValueError("Scout intent must not be empty")
        if self.max_results < 1 or self.max_results > 100:
            raise ValueError("Scout max_results must be between 1 and 100")


@dataclass(frozen=True, slots=True)
class ScoutWorkflowInput:
    operation_key: str
    execution_token: str


@dataclass(frozen=True, slots=True)
class ScoutRunResult:
    operation_key: str
    state: SourceTaskState
    discovered_count: int
    candidate_count: int
    failure_code: str | None = None
