from collections.abc import Iterable
from typing import cast

import httpx

from vimi_social.domain.interest import (
    XInterestList,
    XInterestPost,
    XInterestSnapshot,
    XInterestUser,
)


class XUserContextReauthRequired(RuntimeError):
    pass


class XUserContextUnavailable(RuntimeError):
    pass


class XUserContextScopeUnavailable(RuntimeError):
    pass


class XUserContextClient:
    """Read a bounded, privacy-minimized sample from one OAuth user context."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 20.0,
        list_sample_limit: int = 3,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._list_sample_limit = max(0, min(10, list_sample_limit))

    async def fetch_snapshot(self, access_token: str) -> XInterestSnapshot:
        token = access_token.strip()
        if not token:
            raise XUserContextReauthRequired("X user-context access token is empty")
        headers = {"Authorization": f"Bearer {token}"}

        me = await self._required_get(
            "/2/users/me",
            headers=headers,
            params={"user.fields": "id,name,username"},
        )
        user_id = _required_data_id(me)

        unavailable: list[str] = []
        following_raw = await self._optional_collection(
            f"/2/users/{user_id}/following",
            "following",
            headers,
            {
                "max_results": "100",
                "user.fields": "id,name,username,description",
            },
            unavailable,
        )
        likes_raw = await self._optional_collection(
            f"/2/users/{user_id}/liked_tweets",
            "likes",
            headers,
            {
                "max_results": "100",
                "tweet.fields": "id,text,author_id,created_at,lang,public_metrics",
            },
            unavailable,
        )
        bookmarks_raw = await self._optional_collection(
            f"/2/users/{user_id}/bookmarks",
            "bookmarks",
            headers,
            {
                "max_results": "100",
                "tweet.fields": "id,text,author_id,created_at,lang,public_metrics",
            },
            unavailable,
        )
        followed_lists_raw = await self._optional_collection(
            f"/2/users/{user_id}/followed_lists",
            "followed_lists",
            headers,
            {
                "max_results": "100",
                "list.fields": "id,name,description,private,member_count,follower_count",
            },
            unavailable,
        )
        memberships_raw = await self._optional_collection(
            f"/2/users/{user_id}/list_memberships",
            "list_memberships",
            headers,
            {
                "max_results": "100",
                "list.fields": "id,name,description,private,member_count,follower_count",
            },
            unavailable,
        )

        lists = _deduplicate_lists(
            (*_parse_lists(followed_lists_raw), *_parse_lists(memberships_raw))
        )
        list_posts: list[XInterestPost] = []
        for item in lists[: self._list_sample_limit]:
            raw_posts = await self._optional_collection(
                f"/2/lists/{item.id}/tweets",
                f"list_posts:{item.id}",
                headers,
                {
                    "max_results": "25",
                    "tweet.fields": "id,text,author_id,created_at,lang,public_metrics",
                },
                unavailable,
            )
            list_posts.extend(_parse_posts(raw_posts))

        return XInterestSnapshot(
            user_id=user_id,
            following=_parse_users(following_raw),
            liked_posts=_parse_posts(likes_raw),
            bookmarked_posts=_parse_posts(bookmarks_raw),
            lists=lists,
            list_posts=tuple(list_posts),
            unavailable_sources=tuple(dict.fromkeys(unavailable)),
        )

    async def _optional_collection(
        self,
        path: str,
        label: str,
        headers: dict[str, str],
        params: dict[str, str],
        unavailable: list[str],
    ) -> list[dict[str, object]]:
        try:
            payload = await self._get(path, headers=headers, params=params)
        except XUserContextScopeUnavailable:
            # Missing/unsupported optional scopes are a valid partial snapshot.
            # Transient provider failures deliberately propagate so callers do not
            # overwrite a previously useful profile with a false empty snapshot.
            unavailable.append(label)
            return []
        return _data_list(payload)

    async def _required_get(
        self,
        path: str,
        *,
        headers: dict[str, str],
        params: dict[str, str],
    ) -> dict[str, object]:
        try:
            return await self._get(path, headers=headers, params=params)
        except XUserContextScopeUnavailable as exc:
            raise XUserContextReauthRequired(
                "X user-context token lacks required base scopes"
            ) from exc

    async def _get(
        self,
        path: str,
        *,
        headers: dict[str, str],
        params: dict[str, str],
    ) -> dict[str, object]:
        try:
            response = await self._client.get(
                f"https://api.x.com{path}",
                headers=headers,
                params=params,
            )
        except httpx.HTTPError as exc:
            raise XUserContextUnavailable("X user-context transport failed") from exc

        if response.status_code == 401:
            raise XUserContextReauthRequired("X user-context token was rejected")
        if response.status_code in {403, 404}:
            raise XUserContextScopeUnavailable(
                f"X user-context endpoint unavailable with HTTP {response.status_code}"
            )
        if response.status_code == 429:
            raise XUserContextUnavailable("X user-context endpoint is rate limited")
        if response.status_code >= 400:
            raise XUserContextUnavailable(
                f"X user-context endpoint failed with HTTP {response.status_code}"
            )
        try:
            payload_obj: object = response.json()
        except ValueError as exc:
            raise XUserContextUnavailable("X user-context returned invalid JSON") from exc
        if not isinstance(payload_obj, dict):
            raise XUserContextUnavailable("X user-context returned an invalid response shape")
        return cast(dict[str, object], payload_obj)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _required_data_id(payload: dict[str, object]) -> str:
    data_obj = payload.get("data")
    if not isinstance(data_obj, dict):
        raise XUserContextUnavailable("X /users/me returned no user object")
    data = cast(dict[object, object], data_obj)
    user_id = data.get("id")
    if not isinstance(user_id, str) or not user_id:
        raise XUserContextUnavailable("X /users/me returned no user id")
    return user_id


def _data_list(payload: dict[str, object]) -> list[dict[str, object]]:
    raw = payload.get("data")
    if not isinstance(raw, list):
        return []
    return [
        cast(dict[str, object], item)
        for item in cast(list[object], raw)
        if isinstance(item, dict)
    ]


def _parse_users(items: Iterable[dict[str, object]]) -> tuple[XInterestUser, ...]:
    result: list[XInterestUser] = []
    for item in items:
        user_id = _optional_str(item.get("id"))
        if user_id is None:
            continue
        result.append(
            XInterestUser(
                id=user_id,
                username=_optional_str(item.get("username")),
                name=_optional_str(item.get("name")),
                description=_optional_str(item.get("description")),
            )
        )
    return tuple(result)


def _parse_posts(items: Iterable[dict[str, object]]) -> tuple[XInterestPost, ...]:
    result: list[XInterestPost] = []
    for item in items:
        post_id = _optional_str(item.get("id"))
        if post_id is None:
            continue
        result.append(
            XInterestPost(
                id=post_id,
                text=_optional_str(item.get("text")) or "",
                author_id=_optional_str(item.get("author_id")),
            )
        )
    return tuple(result)


def _parse_lists(items: Iterable[dict[str, object]]) -> tuple[XInterestList, ...]:
    result: list[XInterestList] = []
    for item in items:
        list_id = _optional_str(item.get("id"))
        name = _optional_str(item.get("name"))
        if list_id is None or name is None:
            continue
        result.append(
            XInterestList(
                id=list_id,
                name=name,
                description=_optional_str(item.get("description")),
            )
        )
    return tuple(result)


def _deduplicate_lists(items: Iterable[XInterestList]) -> tuple[XInterestList, ...]:
    result: list[XInterestList] = []
    seen: set[str] = set()
    for item in items:
        if item.id in seen:
            continue
        seen.add(item.id)
        result.append(item)
    return tuple(result)


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
