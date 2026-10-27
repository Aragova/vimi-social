from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

AUTHORIZATION_ENDPOINT = "https://x.com/i/oauth2/authorize"
DEFAULT_SCOPES = (
    "tweet.read tweet.write users.read follows.read like.read list.read bookmark.read "
    "media.write offline.access"
)


def write_env_value(path: Path, key: str, value: str) -> None:
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


def upsert_env_value(path: Path, key: str, value: str) -> None:
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
        updated.append(f"{key}={value}")
    path.write_text("\n".join(updated) + "\n")
    path.chmod(0o600)


def request_target(line: str) -> str | None:
    parts = line.split('"')
    if len(parts) < 2:
        return None
    request_parts = parts[1].split()
    if len(request_parts) < 2:
        return None
    return request_parts[1]


def callback_code(request_target_value: str, expected_state: str) -> str | None:
    query = parse_qs(urlsplit(request_target_value).query)
    state = query.get("state", [""])[0]
    code = query.get("code", [""])[0]
    if state != expected_state or not code:
        return None
    return code


def authorization_url(
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
