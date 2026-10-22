import os

import httpx


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def telegram_request(
    method: str,
    token: str,
    endpoint: str,
    *,
    data: dict[str, str] | None = None,
) -> httpx.Response:
    try:
        response = httpx.request(
            method,
            f"https://api.telegram.org/bot{token}/{endpoint}",
            data=data,
            timeout=20.0,
        )
    except httpx.RequestError:
        raise RuntimeError(f"Telegram {endpoint} request failed") from None
    if response.is_error:
        raise RuntimeError(
            f"Telegram {endpoint} failed with HTTP {response.status_code}"
        )
    return response


def main() -> int:
    token = _required("VIMI_TELEGRAM_BOT_TOKEN")
    secret = _required("VIMI_TELEGRAM_WEBHOOK_SECRET")
    public_host = _required("VIMI_PUBLIC_HOST")
    webhook_url = f"https://{public_host}/telegram/webhook"

    response = telegram_request(
        "POST",
        token,
        "setWebhook",
        data={
            "url": webhook_url,
            "secret_token": secret,
            "drop_pending_updates": "true",
        },
    )
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError("Telegram rejected webhook configuration")

    info = telegram_request("GET", token, "getWebhookInfo")
    info_payload = info.json()
    configured_url = str(info_payload.get("result", {}).get("url", ""))
    if configured_url != webhook_url:
        raise RuntimeError(
            "Telegram webhook verification failed: "
            f"expected {webhook_url!r}, got {configured_url!r}"
        )

    print(f"Telegram webhook configured: {webhook_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
