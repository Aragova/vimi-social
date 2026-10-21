from datetime import datetime
from typing import cast

import httpx

from vimi_social.domain.source import (
    AdultClassification,
    CandidateContent,
    ScoutSearchRequest,
)
from vimi_social.source.connectors import (
    SourceConnectorRateLimited,
    SourceConnectorRejected,
    SourceConnectorUnavailable,
)


class XSourceConnector:
    """Official X API v2 Recent Search connector.

    The connector intentionally uses metadata discovery only. It does not download
    discovered media and does not infer redistribution rights from public availability.
    """

    source_name = "x"

    def __init__(
        self,
        bearer_token: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        token = bearer_token.strip()
        if not token:
            raise ValueError("X bearer token must not be empty")
        self._token = token
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None

    async def search(self, request: ScoutSearchRequest) -> tuple[CandidateContent, ...]:
        query = _build_recent_search_query(request)
        params = {
            "query": query,
            "max_results": str(max(10, min(request.max_results, 100))),
            "tweet.fields": (
                "attachments,author_id,created_at,lang,possibly_sensitive,public_metrics"
            ),
            "expansions": "attachments.media_keys",
            "media.fields": (
                "alt_text,duration_ms,height,media_key,preview_image_url,type,url,width"
            ),
        }
        headers = {"Authorization": f"Bearer {self._token}"}

        try:
            response = await self._client.get(
                "https://api.x.com/2/tweets/search/recent",
                params=params,
                headers=headers,
            )
        except httpx.HTTPError:
            raise SourceConnectorUnavailable("X API transport failed") from None

        if response.status_code == 429:
            raise SourceConnectorRateLimited(_retry_after(response)) from None
        if response.status_code in {401, 403}:
            raise SourceConnectorRejected(
                f"X API rejected credentials or access with HTTP {response.status_code}"
            )
        if response.status_code >= 400:
            raise SourceConnectorUnavailable(
                f"X API search failed with HTTP {response.status_code}"
            )

        try:
            payload_obj: object = response.json()
        except ValueError:
            raise SourceConnectorUnavailable("X API returned invalid JSON") from None
        if not isinstance(payload_obj, dict):
            raise SourceConnectorUnavailable("X API returned an invalid response shape")

        payload = cast(dict[str, object], payload_obj)
        data = _object_list(payload.get("data"))
        includes_obj = payload.get("includes")
        includes = cast(dict[str, object], includes_obj) if isinstance(includes_obj, dict) else {}
        media = _media_by_key(_object_list(includes.get("media")))

        candidates: list[CandidateContent] = []
        for item in data:
            candidate = _candidate_from_post(item, media)
            if candidate is not None:
                candidates.append(candidate)
        return tuple(candidates[: request.max_results])

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _build_recent_search_query(request: ScoutSearchRequest) -> str:
    intent = " ".join(request.intent.split())
    language_clause = ""
    if len(request.preferred_languages) == 1:
        language = request.preferred_languages[0].strip().lower()
        if language and language.replace("-", "").isalpha():
            language_clause = f" lang:{language.split('-', maxsplit=1)[0]}"

    suffix = f" has:videos -is:retweet{language_clause}"
    max_intent_length = 512 - len(suffix)
    trimmed_intent = intent[:max_intent_length].rstrip()
    if not trimmed_intent:
        raise ValueError("Scout intent is empty after normalization")
    return f"{trimmed_intent}{suffix}"


def _candidate_from_post(
    item: dict[str, object],
    media: dict[str, dict[str, object]],
) -> CandidateContent | None:
    post_id = item.get("id")
    text_value = item.get("text")
    if not isinstance(post_id, str) or not post_id:
        return None
    text = text_value if isinstance(text_value, str) else ""

    media_keys: tuple[str, ...] = ()
    attachments_obj = item.get("attachments")
    if isinstance(attachments_obj, dict):
        raw_keys = attachments_obj.get("media_keys")
        if isinstance(raw_keys, list):
            media_keys = tuple(key for key in raw_keys if isinstance(key, str))

    selected_media = next((media[key] for key in media_keys if key in media), None)
    if selected_media is None:
        return None

    media_type_value = selected_media.get("type")
    media_type = media_type_value if isinstance(media_type_value, str) else "unknown"
    published_at = _parse_datetime(item.get("created_at"))
    author_id = item.get("author_id")
    author = author_id if isinstance(author_id, str) else None
    possibly_sensitive = item.get("possibly_sensitive") is True

    metadata: dict[str, object] = {
        "media_key": _optional_str(selected_media.get("media_key")),
        "preview_image_url": _optional_str(selected_media.get("preview_image_url")),
        "media_url": _optional_str(selected_media.get("url")),
        "language": _optional_str(item.get("lang")),
    }

    return CandidateContent(
        id=None,
        source="x",
        source_id=post_id,
        source_url=f"https://x.com/i/web/status/{post_id}",
        author=author,
        published_at=published_at,
        media_type=media_type,
        duration_ms=_optional_int(selected_media.get("duration_ms")),
        width=_optional_int(selected_media.get("width")),
        height=_optional_int(selected_media.get("height")),
        title=_truncate(text, 160) or None,
        caption=text or None,
        tags=(),
        engagement=_public_metrics(item.get("public_metrics")),
        adult_classification=(
            AdultClassification.POSSIBLY_SENSITIVE
            if possibly_sensitive
            else AdultClassification.UNKNOWN
        ),
        explicitness_score=None,
        provenance_hint="PUBLIC_X_POST_REUSE_RIGHTS_NOT_ESTABLISHED",
        availability="DISCOVERED_METADATA_ONLY",
        connector_metadata=metadata,
    )


def _object_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [cast(dict[str, object], item) for item in value if isinstance(item, dict)]


def _media_by_key(items: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for item in items:
        key = item.get("media_key")
        if isinstance(key, str):
            result[key] = item
    return result


def _public_metrics(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key in (
        "like_count",
        "reply_count",
        "retweet_count",
        "quote_count",
        "bookmark_count",
        "impression_count",
    ):
        raw = value.get(key)
        if isinstance(raw, int) and not isinstance(raw, bool):
            result[key] = raw
    return result


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _truncate(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _retry_after(response: httpx.Response) -> int | None:
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        seconds = int(raw)
    except ValueError:
        return None
    return max(1, min(seconds, 86_400))
