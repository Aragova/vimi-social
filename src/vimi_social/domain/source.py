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
class ScoutRefillContinuationState:
    retrieval_query: str
    retrieval_query_variants: tuple[str, ...]
    retrieval_relaxation_level: int
    retrieval_specificity: float
    retrieval_language_mode: str
    continuation_generation: int
    page_start_token: str | None
    next_token: str | None
    search_scope: str | None = None
    search_query: str | None = None

    def __post_init__(self) -> None:
        if not self.retrieval_query.strip():
            raise ValueError("Scout refill retrieval query must not be empty")
        if not self.retrieval_query_variants:
            raise ValueError("Scout refill query variants must not be empty")
        if self.retrieval_relaxation_level < 0:
            raise ValueError("Scout refill relaxation level must not be negative")
        if self.continuation_generation < 0:
            raise ValueError("Scout refill generation must not be negative")
        if not self.retrieval_language_mode.strip():
            raise ValueError("Scout refill language mode must not be empty")


@dataclass(frozen=True, slots=True)
class ScoutSearchRequest:
    intent: str
    requested_sources: tuple[str, ...]
    preferred_languages: tuple[str, ...]
    query_variants: tuple[str, ...] = ()
    max_results: int = 10
    pagination_token: str | None = None
    search_scope: str | None = None

    def __post_init__(self) -> None:
        if not self.intent.strip():
            raise ValueError("Scout intent must not be empty")
        if self.max_results < 1 or self.max_results > 1000:
            raise ValueError("Scout max_results must be between 1 and 1000")
        if any(not query.strip() for query in self.query_variants):
            raise ValueError("Scout query variants must not contain empty values")
        if self.pagination_token is not None and not self.pagination_token.strip():
            raise ValueError("Scout pagination token must not be empty")
        if self.search_scope is not None and self.search_scope not in {"recent", "all"}:
            raise ValueError("Scout search scope must be 'recent' or 'all'")


@dataclass(frozen=True, slots=True)
class ScoutWorkflowInput:
    operation_key: str
    execution_token: str


@dataclass(frozen=True, slots=True)
class ScoutContinuationWorkflowInput:
    operation_key: str
    execution_token: str
    request_key: str
    telegram_update_id: int
    telegram_message_id: int
    telegram_chat_id: int


@dataclass(frozen=True, slots=True)
class ScoutRunResult:
    operation_key: str
    state: SourceTaskState
    discovered_count: int
    candidate_count: int
    failure_code: str | None = None
