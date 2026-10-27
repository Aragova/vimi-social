from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from vimi_social.domain.identity import TenantId


class XInterestSyncState(StrEnum):
    SYNCED = "SYNCED"
    CACHED = "CACHED"
    NO_ACCOUNT = "NO_ACCOUNT"
    MULTIPLE_ACCOUNTS = "MULTIPLE_ACCOUNTS"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class XInterestSyncResult:
    state: XInterestSyncState
    sample_size: int = 0
    unavailable_sources: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class XInterestUser:
    id: str
    username: str | None = None
    name: str | None = None
    description: str | None = None


@dataclass(frozen=True, slots=True)
class XInterestPost:
    id: str
    text: str
    author_id: str | None = None


@dataclass(frozen=True, slots=True)
class XInterestList:
    id: str
    name: str
    description: str | None = None


@dataclass(frozen=True, slots=True)
class XInterestSnapshot:
    user_id: str
    following: tuple[XInterestUser, ...] = ()
    liked_posts: tuple[XInterestPost, ...] = ()
    bookmarked_posts: tuple[XInterestPost, ...] = ()
    lists: tuple[XInterestList, ...] = ()
    list_posts: tuple[XInterestPost, ...] = ()
    unavailable_sources: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class UserInterestProfile:
    tenant_id: TenantId
    user_id: UUID
    destination_account_id: UUID
    external_account_id: str
    term_weights: Mapping[str, float]
    hashtag_weights: Mapping[str, float]
    author_weights: Mapping[str, float]
    source_stats: Mapping[str, int]
    sample_size: int
    generated_at: datetime
