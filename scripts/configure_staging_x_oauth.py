#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import selectors
import secrets
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

AUTHORIZATION_ENDPOINT = "https://x.com/i/oauth2/authorize"
TOKEN_ENDPOINT = "https://api.x.com/2/oauth2/token"
DEFAULT_SCOPES = "tweet.read tweet.write users.read media.write offline.access"


def _read_env_value(path: Path, key: str) -> str:
    for raw_line in path.read_text().splitlines():
        if raw_line.startswith(f"{key}="):
            return raw_line.split("=", 1)[1].strip()
    raise RuntimeError(f"{key} is missing from {path}")


def _write_env_value(path: Path, key: str, value: str) -> None:
    lines = path.read_text().splitlines()
    updated: list[str] = []
    found = False
    for line in lines:
        if line.startswith(f"{key}="):
            updated.append(f"{key}={value}")
            found = True
        else:
            updated.append(line)
    if not found:
        raise RuntimeError(f"{key} is missing from {path}")
    path.write_text("\n".join(updated) + "\n")
    path.chmod(0o600)


def _load_client_id(path: Path) -> str:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read X OAuth client config from {path}") from exc
    client_id = str(payload.get("client_id", "")).strip()
    if not client_id:
        raise RuntimeError(f"client_id is missing from {path}")
    return client_id


def _request_target(line: str) -> str | None:
    parts = line.split('"')
    if len(parts) < 2:
        return None
    request_parts = parts[1].split()
    if len(request_parts) < 2:
        return None
    return request_parts[1]


def _callback_code(request_target: str, expected_state: str) -> str | None:
    query = parse_qs(urlsplit(request_target).query)
    state = query.get("state", [""])[0]
    code = query.get("code", [""])[0]
    if state != expected_state or not code:
        return None
    return code


def _authorization_url(
    *, client_id: str, redirect_uri: str, state: str, code_challenge: str
) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": DEFAULT_SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTHORIZATION_ENDPOINT}?{urlencode(params)}"


def _exchange_code(
    *,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code_verifier: str,
) -> tuple[str, str | None]:
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    body = urlencode(
        {
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        }
    ).encode()
    request = Request(
        TOKEN_ENDPOINT,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:  # noqa: S310 - fixed HTTPS endpoint
            payload: Any = json.loads(response.read())
    except HTTPError as exc:
        raw_body = exc.read().decode(errors="replace")
        try:
            error_payload = json.loads(raw_body)
        except json.JSONDecodeError:
            error_payload = {}
        error = str(error_payload.get("error", "unknown_error"))
        description = str(error_payload.get("error_description", "")).strip()
        detail = f" {description}" if description else ""
        raise RuntimeError(
            f"X token exchange failed: HTTP {exc.code} {error}{detail}"
        ) from exc

    if not isinstance(payload, dict):
        raise RuntimeError("X token exchange returned an invalid response")
    access_token = str(payload.get("access_token", "")).strip()
    if not access_token:
        raise RuntimeError("X token exchange returned no access_token")
    refresh_raw = payload.get("refresh_token")
    refresh_token = str(refresh_raw).strip() if refresh_raw else None
    return access_token, refresh_token


def _wait_for_code(
    *, log_path: Path, expected_state: str, timeout_seconds: int
) -> str:
    subprocess.run(["sudo", "-v"], check=True)
    process = subprocess.Popen(
        ["sudo", "-n", "tail", "-n", "0", "-F", str(log_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    if process.stdout is None:
        process.terminate()
        raise RuntimeError("failed to capture nginx access log")

    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout_seconds
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("timed out waiting for X OAuth callback")
            events = selector.select(timeout=remaining)
            if not events:
                raise RuntimeError("timed out waiting for X OAuth callback")
            line = process.stdout.readline()
            if not line:
                if process.poll() is not None:
                    raise RuntimeError("nginx access-log watcher stopped unexpectedly")
                continue
            request_target = _request_target(line)
            if request_target is None:
                continue
            code = _callback_code(request_target, expected_state)
            if code is not None:
                return code
    finally:
        selector.close()
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a fresh X OAuth 2.0 authorization URL, wait for the nginx "
            "callback, exchange the short-lived code immediately, and store the "
            "user access token in .env.staging without printing credentials."
        )
    )
    parser.add_argument("--env-file", type=Path, default=Path(".env.staging"))
    parser.add_argument(
        "--client-config",
        type=Path,
        default=Path.home() / ".vimi_x_oauth_tmp.json",
    )
    parser.add_argument(
        "--client-secret-file",
        type=Path,
        default=Path.home() / ".x_client_secret",
    )
    parser.add_argument(
        "--refresh-token-file",
        type=Path,
        default=Path.home() / ".vimi_x_refresh_token",
    )
    parser.add_argument(
        "--nginx-access-log",
        type=Path,
        default=Path("/var/log/nginx/access.log"),
    )
    parser.add_argument("--timeout-seconds", type=int, default=300)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.timeout_seconds <= 0:
        raise RuntimeError("--timeout-seconds must be positive")
    if not args.env_file.is_file():
        raise RuntimeError(f"staging env file not found: {args.env_file}")
    if not args.client_secret_file.is_file():
        raise RuntimeError(f"X client secret file not found: {args.client_secret_file}")

    public_host = _read_env_value(args.env_file, "VIMI_PUBLIC_HOST")
    if not public_host:
        raise RuntimeError("VIMI_PUBLIC_HOST must not be empty")
    client_id = _load_client_id(args.client_config)
    client_secret = args.client_secret_file.read_text().strip()
    if not client_secret:
        raise RuntimeError("X client secret file is empty")

    redirect_uri = f"https://{public_host}/"
    code_verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(24)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).rstrip(b"=").decode()

    state_payload = {
        "client_id": client_id,
        "code_verifier": code_verifier,
        "state": state,
        "redirect_uri": redirect_uri,
    }
    args.client_config.write_text(json.dumps(state_payload))
    args.client_config.chmod(0o600)

    authorization_url = _authorization_url(
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=code_challenge,
    )

    print("Open this X authorization URL now:")
    print(authorization_url)
    print()
    print("Waiting for the X callback in nginx...")

    code = _wait_for_code(
        log_path=args.nginx_access_log,
        expected_state=state,
        timeout_seconds=args.timeout_seconds,
    )
    access_token, refresh_token = _exchange_code(
        code=code,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
    )
    _write_env_value(
        args.env_file,
        "VIMI_DEST_X_PRIMARY_TOKEN",
        access_token,
    )

    if refresh_token:
        args.refresh_token_file.write_text(refresh_token + "\n")
        args.refresh_token_file.chmod(0o600)

    print("OK: X user access token obtained")
    print("OK: VIMI_DEST_X_PRIMARY_TOKEN saved to staging env")
    if refresh_token:
        print("OK: X refresh token saved")
    else:
        print("WARNING: X did not return a refresh token")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
