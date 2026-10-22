import os
import subprocess
from pathlib import Path

import httpx
import pytest

from vimi_social.ops.telegram_webhook import telegram_request


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_staging_deploy_validation(
    tmp_path: Path,
    *,
    openai_api_key: str = "",
    x_bearer_token: str = "x-source-test",
) -> subprocess.CompletedProcess[str]:
    env_file = tmp_path / ".env.staging"
    env_file.write_text(
        "\n".join(
            [
                "VIMI_PUBLIC_HOST=staging.example.com",
                "VIMI_POSTGRES_BOOTSTRAP_PASSWORD=bootstrap-test",
                "VIMI_APP_DB_PASSWORD=app-test",
                "VIMI_MIGRATOR_DB_PASSWORD=migrator-test",
                "VIMI_TELEGRAM_BOT_TOKEN=telegram-test",
                "VIMI_TELEGRAM_WEBHOOK_SECRET=webhook-test",
                f"VIMI_X_BEARER_TOKEN={x_bearer_token}",
                f"VIMI_OPENAI_API_KEY={openai_api_key}",
                "VIMI_VISUAL_MODERATION_MODEL=omni-moderation-latest",
                "VIMI_DEST_X_PRIMARY_TOKEN=x-destination-test",
                "VIMI_MEDIA_MAX_BYTES=67108864",
            ]
        )
        + "\n"
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_docker = fake_bin / "docker"
    fake_docker.write_text("#!/bin/sh\nexit 0\n")
    fake_docker.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["VIMI_STAGING_ENV_FILE"] = str(env_file)
    env["VIMI_STAGING_COHOST"] = "true"

    return subprocess.run(
        ["sh", "scripts/deploy_staging.sh"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_staging_deploy_allows_openai_key_to_be_empty(tmp_path: Path) -> None:
    completed = _run_staging_deploy_validation(tmp_path, openai_api_key="")

    assert completed.returncode == 0, completed.stderr


def test_staging_deploy_still_rejects_empty_required_secret(tmp_path: Path) -> None:
    completed = _run_staging_deploy_validation(tmp_path, x_bearer_token="")

    assert completed.returncode != 0
    assert "Missing required staging value: VIMI_X_BEARER_TOKEN" in completed.stderr


def test_staging_compose_treats_openai_key_as_optional() -> None:
    compose = (REPO_ROOT / "infra/docker/docker-compose.staging.yml").read_text()

    assert "VIMI_OPENAI_API_KEY: ${VIMI_OPENAI_API_KEY:-}" in compose
    assert "VIMI_OPENAI_API_KEY is required" not in compose


def test_telegram_http_status_failure_does_not_expose_bot_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "123456:super-secret-staging-token"

    def fake_request(
        method: str,
        url: str,
        **_: object,
    ) -> httpx.Response:
        assert method == "POST"
        assert token in url
        return httpx.Response(401)

    monkeypatch.setattr(httpx, "request", fake_request)

    with pytest.raises(RuntimeError) as captured:
        telegram_request("POST", token, "setWebhook")

    assert str(captured.value) == "Telegram setWebhook failed with HTTP 401"
    assert token not in str(captured.value)


def test_telegram_network_failure_suppresses_token_bearing_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "123456:super-secret-staging-token"

    def fake_request(
        method: str,
        url: str,
        **_: object,
    ) -> httpx.Response:
        request = httpx.Request(method, url)
        raise httpx.ConnectError("connection failed", request=request)

    monkeypatch.setattr(httpx, "request", fake_request)

    with pytest.raises(RuntimeError) as captured:
        telegram_request("GET", token, "getWebhookInfo")

    assert str(captured.value) == "Telegram getWebhookInfo request failed"
    assert token not in str(captured.value)
    assert captured.value.__suppress_context__ is True
