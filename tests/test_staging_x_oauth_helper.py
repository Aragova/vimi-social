from pathlib import Path

from vimi_social.ops.staging_x_oauth import (
    authorization_url,
    callback_code,
    request_target,
    write_env_value,
)


def test_request_target_extracts_nginx_request_path() -> None:
    line = (
        '127.0.0.1 - - [22/Oct/2026:21:00:00 +0300] '
        '"GET /?state=abc&code=xyz HTTP/1.1" 200 32 "-" "Mozilla"'
    )

    assert request_target(line) == "/?state=abc&code=xyz"


def test_callback_code_requires_matching_state() -> None:
    assert callback_code("/?state=expected&code=abc123", "expected") == "abc123"
    assert callback_code("/?state=other&code=abc123", "expected") is None
    assert callback_code("/?state=expected", "expected") is None


def test_authorization_url_contains_required_oauth_values() -> None:
    url = authorization_url(
        client_id="client-id",
        redirect_uri="https://staging.usevimi.ru/",
        state="state-value",
        code_challenge="challenge-value",
    )

    assert url.startswith("https://x.com/i/oauth2/authorize?")
    assert "client_id=client-id" in url
    assert "state=state-value" in url
    assert "code_challenge=challenge-value" in url
    assert "media.write" in url


def test_write_env_value_replaces_only_requested_key(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.staging"
    env_file.write_text(
        "VIMI_PUBLIC_HOST=staging.usevimi.ru\n"
        "VIMI_DEST_X_PRIMARY_TOKEN=old-token\n"
        "VIMI_X_BEARER_TOKEN=source-token\n"
    )

    write_env_value(env_file, "VIMI_DEST_X_PRIMARY_TOKEN", "new-token")

    assert env_file.read_text() == (
        "VIMI_PUBLIC_HOST=staging.usevimi.ru\n"
        "VIMI_DEST_X_PRIMARY_TOKEN=new-token\n"
        "VIMI_X_BEARER_TOKEN=source-token\n"
    )
    assert env_file.stat().st_mode & 0o777 == 0o600
