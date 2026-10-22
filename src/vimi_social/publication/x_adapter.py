import asyncio
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import httpx

from vimi_social.domain.publication import (
    ProviderMutationKind,
    ProviderMutationResult,
    ReconciliationKind,
    ReconciliationResult,
)


@dataclass(frozen=True, slots=True)
class XUploadResult:
    media_id: str


class DestinationCredentialError(RuntimeError):
    pass


class EnvironmentCredentialResolver:
    """Resolve only explicitly namespaced destination secrets from worker environment."""

    def __init__(self, *, allowed_prefix: str = "VIMI_DEST_") -> None:
        self._allowed_prefix = allowed_prefix

    def resolve(self, credential_ref: str) -> str:
        prefix = "env:"
        if not credential_ref.startswith(prefix):
            raise DestinationCredentialError("unsupported destination credential reference")
        variable = credential_ref[len(prefix) :]
        if not variable.startswith(self._allowed_prefix):
            raise DestinationCredentialError(
                "destination credential reference is outside allowlist"
            )
        value = os.environ.get(variable)
        if value is None or not value.strip():
            raise DestinationCredentialError("destination credential is unavailable")
        return value.strip()


class XDestinationAdapter:
    platform = "x"
    _chunk_bytes = 4 * 1024 * 1024

    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        max_processing_polls: int = 30,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if max_processing_polls <= 0:
            raise ValueError("max_processing_polls must be positive")
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None
        self._max_processing_polls = max_processing_polls

    async def publish_video(
        self,
        *,
        access_token: str,
        video_path: Path,
        caption: str,
        checkpoint_media: Callable[[str], Awaitable[bool]],
    ) -> ProviderMutationResult:
        if not video_path.is_file():
            return ProviderMutationResult(
                kind=ProviderMutationKind.FAILED_SAFE,
                failure_code="X_VIDEO_NOT_AVAILABLE",
            )
        size_bytes = video_path.stat().st_size
        if size_bytes <= 0:
            return ProviderMutationResult(
                kind=ProviderMutationKind.FAILED_SAFE,
                failure_code="X_VIDEO_EMPTY",
            )
        headers = {"Authorization": f"Bearer {access_token}"}
        mutation_started = False
        media_id: str | None = None
        try:
            mutation_started = True
            init = await self._client.post(
                "https://api.x.com/2/media/upload/initialize",
                headers={**headers, "Content-Type": "application/json"},
                json={
                    "media_type": "video/mp4",
                    "total_bytes": size_bytes,
                    "media_category": "tweet_video",
                },
            )
            init_failure = _known_http_failure(init, phase="INIT")
            if init_failure is not None:
                return init_failure
            media_id = _media_id(init)

            with video_path.open("rb") as handle:
                segment_index = 0
                while True:
                    chunk = handle.read(self._chunk_bytes)
                    if not chunk:
                        break
                    response = await self._client.post(
                        f"https://api.x.com/2/media/upload/{media_id}/append",
                        headers=headers,
                        data={"segment_index": str(segment_index)},
                        files={"media": ("chunk.mp4", chunk, "application/octet-stream")},
                    )
                    if not 200 <= response.status_code < 300:
                        return ProviderMutationResult(
                            kind=ProviderMutationKind.UNKNOWN,
                            remote_media_id=media_id,
                            failure_code=f"X_APPEND_HTTP_{response.status_code}",
                        )
                    segment_index += 1

            finalized = await self._client.post(
                f"https://api.x.com/2/media/upload/{media_id}/finalize",
                headers=headers,
            )
            if not 200 <= finalized.status_code < 300:
                return ProviderMutationResult(
                    kind=ProviderMutationKind.UNKNOWN,
                    remote_media_id=media_id,
                    failure_code=f"X_FINALIZE_HTTP_{finalized.status_code}",
                )
            processing = _processing_info(finalized)
            if processing is not None:
                processing_result = await self._wait_for_processing(
                    access_token=access_token,
                    media_id=media_id,
                    initial=processing,
                )
                if processing_result is not None:
                    return processing_result

            if not await checkpoint_media(media_id):
                return ProviderMutationResult(
                    kind=ProviderMutationKind.UNKNOWN,
                    remote_media_id=media_id,
                    failure_code="LOCAL_MEDIA_CHECKPOINT_OWNERSHIP_LOST",
                )

            payload: dict[str, object] = {"media": {"media_ids": [media_id]}}
            normalized_caption = caption.strip()
            if normalized_caption:
                payload["text"] = normalized_caption
            post = await self._client.post(
                "https://api.x.com/2/tweets",
                headers={**headers, "Content-Type": "application/json"},
                json=payload,
            )
            if 200 <= post.status_code < 300:
                post_id = _post_id(post)
                return ProviderMutationResult(
                    kind=ProviderMutationKind.CONFIRMED,
                    remote_media_id=media_id,
                    remote_post_id=post_id,
                )
            if post.status_code in {400, 401, 403, 404, 409, 422}:
                return ProviderMutationResult(
                    kind=ProviderMutationKind.FAILED_PERMANENT,
                    remote_media_id=media_id,
                    failure_code=f"X_CREATE_POST_HTTP_{post.status_code}",
                )
            if post.status_code == 429:
                return ProviderMutationResult(
                    kind=ProviderMutationKind.FAILED_SAFE,
                    remote_media_id=media_id,
                    failure_code="X_CREATE_POST_RATE_LIMITED",
                )
            return ProviderMutationResult(
                kind=ProviderMutationKind.UNKNOWN,
                remote_media_id=media_id,
                failure_code=f"X_CREATE_POST_HTTP_{post.status_code}_AMBIGUOUS",
            )
        except (httpx.HTTPError, TimeoutError, OSError):
            return ProviderMutationResult(
                kind=(
                    ProviderMutationKind.UNKNOWN
                    if mutation_started
                    else ProviderMutationKind.FAILED_SAFE
                ),
                remote_media_id=media_id,
                failure_code="X_PUBLICATION_TRANSPORT_AMBIGUOUS",
            )
        except ValueError:
            return ProviderMutationResult(
                kind=(
                    ProviderMutationKind.UNKNOWN
                    if mutation_started
                    else ProviderMutationKind.FAILED_SAFE
                ),
                remote_media_id=media_id,
                failure_code="X_PUBLICATION_RESPONSE_INVALID",
            )

    async def reconcile(
        self,
        *,
        access_token: str,
        remote_post_id: str | None,
    ) -> ReconciliationResult:
        if remote_post_id is None:
            return ReconciliationResult(kind=ReconciliationKind.INCONCLUSIVE)
        try:
            response = await self._client.get(
                f"https://api.x.com/2/tweets/{remote_post_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except httpx.HTTPError:
            return ReconciliationResult(kind=ReconciliationKind.INCONCLUSIVE)
        if 200 <= response.status_code < 300:
            return ReconciliationResult(
                kind=ReconciliationKind.CONFIRMED,
                remote_post_id=remote_post_id,
            )
        # X lookup absence is not strong enough to prove non-publication after an
        # ambiguous create because reads may be eventually consistent and an
        # unknown create usually gives us no remote post id at all.
        return ReconciliationResult(kind=ReconciliationKind.INCONCLUSIVE)

    async def _wait_for_processing(
        self,
        *,
        access_token: str,
        media_id: str,
        initial: Mapping[str, object],
    ) -> ProviderMutationResult | None:
        processing = initial
        for _ in range(self._max_processing_polls):
            state = _optional_str(processing.get("state"))
            if state in {None, "succeeded"}:
                return None
            if state == "failed":
                return ProviderMutationResult(
                    kind=ProviderMutationKind.FAILED_PERMANENT,
                    remote_media_id=media_id,
                    failure_code="X_MEDIA_PROCESSING_FAILED",
                )
            delay = _bounded_check_after(processing.get("check_after_secs"))
            await asyncio.sleep(delay)
            try:
                response = await self._client.get(
                    "https://api.x.com/2/media/upload",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={"command": "STATUS", "media_id": media_id},
                )
            except httpx.HTTPError:
                return ProviderMutationResult(
                    kind=ProviderMutationKind.UNKNOWN,
                    remote_media_id=media_id,
                    failure_code="X_MEDIA_STATUS_TRANSPORT_AMBIGUOUS",
                )
            if not 200 <= response.status_code < 300:
                return ProviderMutationResult(
                    kind=ProviderMutationKind.UNKNOWN,
                    remote_media_id=media_id,
                    failure_code=f"X_MEDIA_STATUS_HTTP_{response.status_code}",
                )
            info = _processing_info(response)
            if info is None:
                return None
            processing = info
        return ProviderMutationResult(
            kind=ProviderMutationKind.UNKNOWN,
            remote_media_id=media_id,
            failure_code="X_MEDIA_PROCESSING_STATUS_INCONCLUSIVE",
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _known_http_failure(response: httpx.Response, *, phase: str) -> ProviderMutationResult | None:
    if 200 <= response.status_code < 300:
        return None
    if response.status_code == 429:
        return ProviderMutationResult(
            kind=ProviderMutationKind.FAILED_SAFE,
            failure_code=f"X_{phase}_RATE_LIMITED",
        )
    if 400 <= response.status_code < 500:
        return ProviderMutationResult(
            kind=ProviderMutationKind.FAILED_PERMANENT,
            failure_code=f"X_{phase}_HTTP_{response.status_code}",
        )
    return ProviderMutationResult(
        kind=ProviderMutationKind.UNKNOWN,
        failure_code=f"X_{phase}_HTTP_{response.status_code}_AMBIGUOUS",
    )


def _media_id(response: httpx.Response) -> str:
    root = _response_object(response)
    data_raw = root.get("data")
    if not isinstance(data_raw, dict):
        raise ValueError("X media response is missing data")
    data = cast(Mapping[str, object], data_raw)
    identifier = data.get("id")
    if not isinstance(identifier, str) or not identifier:
        raise ValueError("X media response is missing id")
    return identifier


def _post_id(response: httpx.Response) -> str:
    root = _response_object(response)
    data_raw = root.get("data")
    if not isinstance(data_raw, dict):
        raise ValueError("X create-post response is missing data")
    data = cast(Mapping[str, object], data_raw)
    identifier = data.get("id")
    if not isinstance(identifier, str) or not identifier:
        raise ValueError("X create-post response is missing id")
    return identifier


def _processing_info(response: httpx.Response) -> Mapping[str, object] | None:
    root = _response_object(response)
    data_raw = root.get("data")
    if not isinstance(data_raw, dict):
        raise ValueError("X media response is missing data")
    data = cast(Mapping[str, object], data_raw)
    info_raw = data.get("processing_info")
    return cast(Mapping[str, object], info_raw) if isinstance(info_raw, dict) else None


def _response_object(response: httpx.Response) -> Mapping[str, object]:
    try:
        decoded = cast(object, response.json())
    except ValueError as exc:
        raise ValueError("X API returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise ValueError("X API returned invalid response shape")
    return cast(Mapping[str, object], decoded)


def _bounded_check_after(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 1
    return max(1, min(int(value), 30))


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None
