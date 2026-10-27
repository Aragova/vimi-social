#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import cast

from vimi_social.ops.staging_x_oauth import upsert_env_value


def _read_client_id(path: Path) -> str:
    try:
        payload_obj: object = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read X OAuth client config from {path}") from exc
    if not isinstance(payload_obj, dict):
        raise RuntimeError(f"invalid X OAuth client config in {path}")
    payload = cast(dict[str, object], payload_obj)
    raw = payload.get("client_id")
    client_id = raw.strip() if isinstance(raw, str) else ""
    if not client_id:
        raise RuntimeError(f"client_id is missing from {path}")
    return client_id


def _read_secret(path: Path, label: str) -> str:
    if not path.is_file():
        raise RuntimeError(f"{label} file not found: {path}")
    value = path.read_text().strip()
    if not value:
        raise RuntimeError(f"{label} file is empty: {path}")
    return value


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Enable automatic staging X OAuth refresh from credentials already "
            "saved by configure_staging_x_oauth.py. No secret values are printed."
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
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if not args.env_file.is_file():
        raise RuntimeError(f"staging env file not found: {args.env_file}")

    client_id = _read_client_id(args.client_config)
    client_secret = _read_secret(args.client_secret_file, "X client secret")
    refresh_token = _read_secret(args.refresh_token_file, "X refresh token")

    upsert_env_value(args.env_file, "VIMI_X_OAUTH_CLIENT_ID", client_id)
    upsert_env_value(args.env_file, "VIMI_X_OAUTH_CLIENT_SECRET", client_secret)
    upsert_env_value(
        args.env_file,
        "VIMI_DEST_X_PRIMARY_REFRESH_TOKEN",
        refresh_token,
    )
    upsert_env_value(
        args.env_file,
        "VIMI_X_OAUTH_REFRESH_INTERVAL_SECONDS",
        "5400",
    )

    print("OK: staging X OAuth auto-refresh enabled from saved credentials")
    print("OK: no OAuth secret values were printed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
