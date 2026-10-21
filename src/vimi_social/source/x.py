from datetime import datetime

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from vimi_social.source.connectors import SourceConnectorUnavailable
from vimi_social.source.models import (
    CandidateContent,
    MediaKind,
    SourcePlatform,
    SourceSearchRequest,
)


class _XAttachments(BaseModel):
    media_keys: list[str] = Field(default_factory=list)


class _XPost(BaseModel):
    id: str
    text: str = ""
    author_id: str | None = None
    created_at: datetime | None = None
    possibly_sensitive: bool = False
    attachments: _XAttachments | None = None


class _XUser(BaseModel):
    id: str
    username: str


class _XMedia(BaseModel):
    model_config = ConfigDict(extra="ignore")

    media_key: str
    type: str


class _XIncludes(BaseModel):
    users: list[_XUser] = Field(default_factory=list)
    media: list[_XMedia] = Field(default_factory=list)


class _XSearchResponse(BaseModel):
    data: list[_XPost] = Field(default_factory=list)
    includes: _XIncludes = Field(default_factory=_XIncludes)


class XRecentSearchConnector:
    _endpoint = "https://api.x.com/2/tweets/search/recent"

    def __init__(
        self,
        bearer_token: str,
        *,
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        token = bearer_token.strip()
        if not token:
            raise ValueError("X bearer token must not be empty")
        self._token = token
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)

    @property
    def platform(self) -> SourcePlatform:
        return SourcePlatform.X

    async def search(self, request: SourceSearchRequest) -> tuple[CandidateContent, ...]:
        if request.source is not SourcePlatform.X:
            raise ValueError("X connector received a non-X search request")

        query = _video_query(request.query)
        try:
            response = await self._client.get(
                self._endpoint,
                headers={"Authorization": f"Bearer {self._token}"},
                params={
                    "query": query,
                    "max_results": str(request.limit),
                    "sort_order": "relevancy",
                    "tweet.fields": (
                        "author_id,created_at,possibly_sensitive,attachments"
                    ),
                    "expansions": "author_id,attachments.media_keys",
                    "user.fields": "username",
                    "media.fields": "media_key,type",
                },
            )
        except httpx.HTTPError:
            raise SourceConnectorUnavailable("X source request failed in transport") from None

        if response.status_code >= 300:
            raise SourceConnectorUnavailable(
                f"X source request failed with HTTP {response.status_code}"
            ) from None

        try:
            payload = _XSearchResponse.model_validate(response.json())
        except (ValueError, ValidationError):
            raise SourceConnectorUnavailable("X source returned an invalid response") from None

        users = {user.id: user.username for user in payload.includes.users}
        media = {item.media_key: item.type for item in payload.includes.media}
        candidates: list[CandidateContent] = []

        for post in payload.data:
            media_keys = tuple(post.attachments.media_keys) if post.attachments else ()
            media_types = {media[key] for key in media_keys if key in media}
            if "video" not in media_types and "animated_gif" not in media_types:
                continue

            username = users.get(post.author_id) if post.author_id is not None else None
            canonical_url = (
                f"https://x.com/{username}/status/{post.id}"
                if username is not None
                else f"https://x.com/i/web/status/{post.id}"
            )
            candidates.append(
                CandidateContent(
                    source=SourcePlatform.X,
                    external_id=post.id,
                    canonical_url=canonical_url,
                    author_handle=username,
                    text=post.text,
                    published_at=post.created_at,
                    possibly_sensitive=post.possibly_sensitive,
                    media_kind=MediaKind.VIDEO,
                    media_refs=media_keys,
                )
            )

        return tuple(candidates)

    async def aclose(self) -> None:
        await self._client.aclose()


def _video_query(query: str) -> str:
    filters: list[str] = []
    if "has:videos" not in query:
        filters.append("has:videos")
    if "is:retweet" not in query:
        filters.append("-is:retweet")
    if not filters:
        return query
    return f"({query}) {' '.join(filters)}"
