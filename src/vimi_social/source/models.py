from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from vimi_social.domain.source import SourceMode


class SourcePlatform(StrEnum):
    X = "X"
    TELEGRAM = "TELEGRAM"
    REDDIT = "REDDIT"
    WEB = "WEB"


class SourceTaskState(StrEnum):
    QUEUED = "QUEUED"
    DISCOVERING = "DISCOVERING"
    CANDIDATES_READY = "CANDIDATES_READY"
    FAILED_SAFE = "FAILED_SAFE"
    BLOCKED = "BLOCKED"


class MediaKind(StrEnum):
    VIDEO = "VIDEO"
    IMAGE = "IMAGE"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class SourceTask:
    id: UUID
    tenant_id: UUID
    actor_user_id: UUID
    origin_key: str
    source_mode: SourceMode
    query_text: str
    requested_source: SourcePlatform | None
    state: SourceTaskState
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SourceSearchRequest:
    source: SourcePlatform
    query: str
    limit: int = 10

    def __post_init__(self) -> None:
        query = self.query.strip()
        if not query:
            raise ValueError("source search query must not be empty")
        if len(query) > 400:
            raise ValueError("source search query must be at most 400 characters")
        if not 10 <= self.limit <= 100:
            raise ValueError("source search limit must be between 10 and 100")
        object.__setattr__(self, "query", query)


@dataclass(frozen=True, slots=True)
class CandidateContent:
    source: SourcePlatform
    external_id: str
    canonical_url: str
    author_handle: str | None
    text: str
    published_at: datetime | None
    possibly_sensitive: bool
    media_kind: MediaKind
    media_refs: tuple[str, ...] = ()
