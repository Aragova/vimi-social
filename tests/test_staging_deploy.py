import os
import pathlib
import subprocess

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _run_staging_deploy_validation(
    tmp_path: pathlib.Path,
    *,
    openai_api_key: str = "",
    search_translation_api_key: str = "",
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
                f"VIMI_SEARCH_TRANSLATION_API_KEY={search_translation_api_key}",
                "VIMI_SEARCH_TRANSLATION_MODEL=gpt-6-luna",
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


def test_staging_deploy_allows_openai_key_to_be_empty(tmp_path: pathlib.Path) -> None:
    completed = _run_staging_deploy_validation(tmp_path, openai_api_key="")

    assert completed.returncode == 0, completed.stderr


def test_staging_deploy_allows_search_translation_key_to_be_empty(
    tmp_path: pathlib.Path,
) -> None:
    completed = _run_staging_deploy_validation(
        tmp_path,
        search_translation_api_key="",
    )

    assert completed.returncode == 0, completed.stderr


def test_staging_deploy_still_rejects_empty_required_secret(tmp_path: pathlib.Path) -> None:
    completed = _run_staging_deploy_validation(tmp_path, x_bearer_token="")

    assert completed.returncode != 0
    assert "Missing required staging value: VIMI_X_BEARER_TOKEN" in completed.stderr


def test_staging_compose_treats_optional_ai_keys_as_optional() -> None:
    compose = (REPO_ROOT / "infra/docker/docker-compose.staging.yml").read_text()

    assert "VIMI_SEARCH_TRANSLATION_API_KEY: ${VIMI_SEARCH_TRANSLATION_API_KEY:-}" in compose
    assert "VIMI_SEARCH_TRANSLATION_API_KEY is required" not in compose
    assert "VIMI_OPENAI_API_KEY: ${VIMI_OPENAI_API_KEY:-}" in compose
    assert "VIMI_OPENAI_API_KEY is required" not in compose
