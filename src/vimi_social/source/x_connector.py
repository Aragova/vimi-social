import re
from dataclasses import replace
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
    SourceSearchCandidates,
)

_PLAIN_QUERY_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_X_BOOLEAN_WORDS = {"and", "or", "not"}
_X_SEARCH_SCOPES = {"recent", "all"}


class XSourceConnector:
    """Official X API v2 search connector.

    The connector performs discovery only. A returned video variant is retained as
    metadata for the rights-gated media worker; discovery never establishes reuse rights.
    """

    source_name = "x"

    def __init__(
        self,
        bearer_token: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10.0,
        search_scope: str = "recent",
    ) -> None:
        token = bearer_token.strip()
        if not token:
            raise ValueError("X bearer token must not be empty")
        normalized_scope = search_scope.strip().lower()
        if normalized_scope not in _X_SEARCH_SCOPES:
            raise ValueError("X search scope must be 'recent' or 'all'")
        self._token = token
        self._search_scope = normalized_scope
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None

    async def search(self, request: ScoutSearchRequest) -> tuple[CandidateContent, ...]:
        read_budget = max(1, request.max_results)
        scope = request.search_scope or self._search_scope
        if scope not in _X_SEARCH_SCOPES:
            raise ValueError("X search scope must be 'recent' or 'all'")
        query = _build_search_query(request, scope=scope)
        headers = {"Authorization": f"Bearer {self._token}"}
        candidates: list[CandidateContent] = []
        seen_posts: set[str] = set()
        seen_tokens: set[str] = set()
        page_token = request.pagination_token
        continuation_token: str | None = page_token
        posts_read = 0

        while posts_read < read_budget:
            if page_token is not None:
                if page_token in seen_tokens:
                    continuation_token = None
                    break
                seen_tokens.add(page_token)

            remaining = read_budget - posts_read
            params = {
                "query": query,
                "max_results": str(max(10, min(remaining, _max_page_size(scope)))),
                "tweet.fields": (
                    "attachments,author_id,created_at,lang,possibly_sensitive,public_metrics"
                ),
                "expansions": "attachments.media_keys",
                "media.fields": (
                    "alt_text,duration_ms,height,media_key,preview_image_url,type,url,variants,width"
                ),
            }
            if page_token is not None:
                params["next_token"] = page_token

            try:
                payload = await self._fetch_page(
                    params,
                    headers,
                    scope=scope,
                )
            except SourceConnectorUnavailable:
                if posts_read > 0:
                    # A transport/5xx failure is ambiguous: the provider may have
                    # processed this page even though its response was lost. Keep
                    # already-returned candidates but never expose the failed page's
                    # token for a blind paid retry.
                    continuation_token = None
                    break
                raise
            except (SourceConnectorRateLimited, SourceConnectorRejected):
                if posts_read > 0:
                    # 429/401/403 are definitive no-data responses. The current
                    # page token remains safe to retry manually later, even when
                    # earlier successful pages produced no convertible candidates.
                    continuation_token = page_token
                    break
                raise

            data = _object_list(payload.get("data"))
            posts_read += len(data)
            includes_obj = payload.get("includes")
            includes = (
                cast(dict[str, object], includes_obj)
                if isinstance(includes_obj, dict)
                else {}
            )
            media = _media_by_key(_object_list(includes.get("media")))

            for item in data:
                candidate = _candidate_from_post(item, media)
                if candidate is None or candidate.source_id in seen_posts:
                    continue
                seen_posts.add(candidate.source_id)
                candidates.append(candidate)

            token = _next_token(payload)
            continuation_token = token
            if not data or token is None:
                break
            if token in seen_tokens:
                continuation_token = None
                break
            if posts_read >= read_budget:
                break
            page_token = token

        return SourceSearchCandidates(
            (
                _with_search_state(
                    candidate,
                    scope=scope,
                    query=query,
                    continuation_token=continuation_token,
                    requested_token=request.pagination_token,
                )
                for candidate in candidates
            ),
            next_token=continuation_token,
        )

    async def _fetch_page(
        self,
        params: dict[str, str],
        headers: dict[str, str],
        *,
        scope: str,
    ) -> dict[str, object]:
        endpoint = "all" if scope == "all" else "recent"
        try:
            response = await self._client.get(
                f"https://api.x.com/2/tweets/search/{endpoint}",
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
        return cast(dict[str, object], payload_obj)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _build_search_query(request: ScoutSearchRequest, *, scope: str) -> str:
    variants = _normalized_query_variants(request)
    language_clause = ""
    if len(request.preferred_languages) == 1:
        language = request.preferred_languages[0].strip().lower()
        if language and language.replace("-", "").isalpha():
            language_clause = f" lang:{language.split('-', maxsplit=1)[0]}"

    suffix = f" has:videos -is:retweet{language_clause}"
    expression_budget = _query_limit(scope) - len(suffix)
    expression = _fit_query_expression(variants, expression_budget)
    return f"{expression}{suffix}"


def _query_limit(scope: str) -> int:
    return 1024 if scope == "all" else 512


def _max_page_size(scope: str) -> int:
    return 500 if scope == "all" else 100


def _with_search_state(
    candidate: CandidateContent,
    *,
    scope: str,
    query: str,
    continuation_token: str | None,
    requested_token: str | None,
) -> CandidateContent:
    metadata = dict(candidate.connector_metadata)
    metadata["x_search_scope"] = scope
    metadata["x_search_query"] = query
    if continuation_token is not None:
        metadata["x_next_token"] = continuation_token
    if requested_token is not None:
        metadata["x_page_start_token"] = requested_token
    return replace(candidate, connector_metadata=metadata)


def _normalized_query_variants(request: ScoutSearchRequest) -> tuple[str, ...]:
    raw_variants = request.query_variants or (request.intent,)
    result: list[str] = []
    seen: set[str] = set()
    for raw in raw_variants:
        normalized = " ".join(raw.split()).strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    if not result:
        raise ValueError("Scout intent is empty after normalization")
    return tuple(result[:4])


def _fit_query_expression(variants: tuple[str, ...], budget: int) -> str:
    if budget < 1:
        raise ValueError("X search query has no room for intent")

    full_expression = _group_query_variants(variants)
    if len(full_expression) <= budget:
        return full_expression

    selected: list[str] = []
    for variant in variants:
        candidate = _group_query_variants((*selected, variant))
        if len(candidate) <= budget:
            selected.append(variant)
    if selected:
        return _group_query_variants(tuple(selected))

    return _safe_plaintext_fallback(variants[0], budget)


def _group_query_variants(variants: tuple[str, ...]) -> str:
    if len(variants) == 1:
        return variants[0]
    parts = [f"({variant})" for variant in variants]
    return f"({' OR '.join(parts)})"


def _safe_plaintext_fallback(value: str, budget: int) -> str:
    tokens = [
        token
        for token in _PLAIN_QUERY_TOKEN.findall(value)
        if token.casefold() not in _X_BOOLEAN_WORDS
    ]
    selected: list[str] = []
    used = 0
    for token in tokens:
        extra = len(token) + (1 if selected else 0)
        if used + extra > budget:
            break
        selected.append(token)
        used += extra
    if not selected:
        raise ValueError("X search query has no safe searchable text within the budget")
    return " ".join(selected)


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
        attachments = cast(dict[object, object], attachments_obj)
        raw_keys = attachments.get("media_keys")
        if isinstance(raw_keys, list):
            keys = cast(list[object], raw_keys)
            media_keys = tuple(key for key in keys if isinstance(key, str))

    selected_media = _select_video_media(media_keys, media)
    if selected_media is None:
        return None

    media_type_value = selected_media.get("type")
    media_type = media_type_value if isinstance(media_type_value, str) else "unknown"
    published_at = _parse_datetime(item.get("created_at"))
    author_id = item.get("author_id")
    author = author_id if isinstance(author_id, str) else None
    possibly_sensitive = item.get("possibly_sensitive") is True
    acquisition_url = _best_mp4_variant(selected_media.get("variants"))

    metadata: dict[str, object] = {
        "media_key": _optional_str(selected_media.get("media_key")),
        "preview_image_url": _optional_str(selected_media.get("preview_image_url")),
        "media_url": _optional_str(selected_media.get("url")),
        "language": _optional_str(item.get("lang")),
        "acquisition_url": acquisition_url,
        "acquisition_reference": "OFFICIAL_X_API_VIDEO_VARIANT",
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
        availability=(
            "DISCOVERED_MEDIA_REFERENCE_AVAILABLE"
            if acquisition_url is not None
            else "DISCOVERED_METADATA_ONLY"
        ),
        connector_metadata=metadata,
    )


def _select_video_media(
    media_keys: tuple[str, ...],
    media: dict[str, dict[str, object]],
) -> dict[str, object] | None:
    for key in media_keys:
        item = media.get(key)
        if item is not None and item.get("type") == "video":
            return item
    return None


def _best_mp4_variant(value: object) -> str | None:
    if not isinstance(value, list):
        return None
    best_url: str | None = None
    best_bitrate = -1
    for raw in cast(list[object], value):
        if not isinstance(raw, dict):
            continue
        variant = cast(dict[object, object], raw)
        if variant.get("content_type") != "video/mp4":
            continue
        url = variant.get("url")
        if not isinstance(url, str) or not url:
            continue
        raw_bitrate = variant.get("bit_rate")
        bitrate = (
            raw_bitrate
            if isinstance(raw_bitrate, int) and not isinstance(raw_bitrate, bool)
            else 0
        )
        if best_url is None or bitrate > best_bitrate:
            best_url = url
            best_bitrate = bitrate
    return best_url


def _object_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    items = cast(list[object], value)
    return [cast(dict[str, object], item) for item in items if isinstance(item, dict)]


def _media_by_key(items: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for item in items:
        key = item.get("media_key")
        if isinstance(key, str):
            result[key] = item
    return result


def _next_token(payload: dict[str, object]) -> str | None:
    meta_obj = payload.get("meta")
    if not isinstance(meta_obj, dict):
        return None
    meta = cast(dict[object, object], meta_obj)
    token = meta.get("next_token")
    return token if isinstance(token, str) and token else None


def _public_metrics(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    metrics = cast(dict[object, object], value)
    result: dict[str, int] = {}
    for key in (
        "like_count",
        "reply_count",
        "retweet_count",
        "quote_count",
        "bookmark_count",
        "impression_count",
    ):
        raw = metrics.get(key)
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
