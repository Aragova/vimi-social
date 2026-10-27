import asyncio
import base64
import json
import os
from pathlib import Path
from typing import cast

import httpx

_TOKEN_ENDPOINT = "https://api.x.com/2/oauth2/token"
_PRIMARY_CREDENTIAL_REF = "env:VIMI_DEST_X_PRIMARY_TOKEN"


class XOAuthRefreshUnavailable(RuntimeError):
    pass


class XOAuthTokenManager:
    """Own and refresh the staging X user token only inside destination-worker."""

    def __init__(
        self,
        *,
        access_token: str | None,
        refresh_token: str | None,
        client_id: str | None,
        client_secret: str | None,
        state_path: Path,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._access_token = (access_token or "").strip()
        self._bootstrap_refresh_token = (refresh_token or "").strip()
        self._client_id = (client_id or "").strip()
        self._client_secret = (client_secret or "").strip()
        self._state_path = state_path
        self._client = client or httpx.AsyncClient(timeout=20.0)
        self._owns_client = client is None
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return bool(
            self._client_id
            and self._client_secret
            and (self._read_refresh_token() or self._bootstrap_refresh_token)
        )

    def supports(self, credential_ref: str) -> bool:
        return credential_ref == _PRIMARY_CREDENTIAL_REF and self.enabled

    def current_access_token(self) -> str:
        return self._access_token

    async def refresh_after_rejection(self, rejected_access_token: str) -> str:
        async with self._lock:
            current = self._access_token.strip()
            if current and current != rejected_access_token.strip():
                return current
            return await self._refresh_locked()

    async def refresh_now(self) -> str:
        async with self._lock:
            return await self._refresh_locked()

    async def run_periodic(self, *, interval_seconds: float = 5400.0) -> None:
        interval = max(300.0, interval_seconds)
        while True:
            await asyncio.sleep(interval)
            try:
                await self.refresh_now()
            except XOAuthRefreshUnavailable:
                # Best-effort maintenance only. The activity path still detects a
                # rejected token and can surface REAUTH_REQUIRED without crashing
                # the destination worker.
                continue

    async def _refresh_locked(self) -> str:
        refresh_token = self._read_refresh_token() or self._bootstrap_refresh_token
        if not (refresh_token and self._client_id and self._client_secret):
            raise XOAuthRefreshUnavailable("X OAuth refresh credentials are unavailable")

        basic = base64.b64encode(
            f"{self._client_id}:{self._client_secret}".encode()
        ).decode()
        try:
            response = await self._client.post(
                _TOKEN_ENDPOINT,
                headers={
                    "Authorization": f"Basic {basic}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
            )
        except httpx.HTTPError as exc:
            raise XOAuthRefreshUnavailable("X OAuth refresh transport failed") from exc

        if not 200 <= response.status_code < 300:
            raise XOAuthRefreshUnavailable(
                f"X OAuth refresh failed with HTTP {response.status_code}"
            )
        try:
            payload_obj: object = response.json()
        except json.JSONDecodeError as exc:
            raise XOAuthRefreshUnavailable("X OAuth refresh returned invalid JSON") from exc
        if not isinstance(payload_obj, dict):
            raise XOAuthRefreshUnavailable("X OAuth refresh returned invalid payload")
        payload = cast(dict[str, object], payload_obj)
        access_raw = payload.get("access_token")
        access_token = access_raw.strip() if isinstance(access_raw, str) else ""
        if not access_token:
            raise XOAuthRefreshUnavailable("X OAuth refresh returned no access token")

        refresh_raw = payload.get("refresh_token")
        rotated_refresh_token = (
            refresh_raw.strip()
            if isinstance(refresh_raw, str) and refresh_raw.strip()
            else refresh_token
        )
        self._persist_refresh_token(rotated_refresh_token)
        self._access_token = access_token
        self._bootstrap_refresh_token = rotated_refresh_token
        # EnvironmentCredentialResolver reads os.environ at call time, so this also
        # refreshes publication/reconciliation credentials in the same worker.
        os.environ["VIMI_DEST_X_PRIMARY_TOKEN"] = access_token
        return access_token

    def _read_refresh_token(self) -> str:
        try:
            if self._state_path.is_file():
                return self._state_path.read_text().strip()
        except OSError:
            return ""
        return ""

    def _persist_refresh_token(self, refresh_token: str) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._state_path.with_name(f".{self._state_path.name}.tmp")
            temporary.write_text(refresh_token + "\n")
            temporary.chmod(0o600)
            temporary.replace(self._state_path)
            self._state_path.chmod(0o600)
        except OSError as exc:
            raise XOAuthRefreshUnavailable(
                "X OAuth refresh token state could not be persisted"
            ) from exc

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
