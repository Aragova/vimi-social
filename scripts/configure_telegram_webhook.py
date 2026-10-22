import os
import sys

import httpx


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def main() -> int:
    token = _required("VIMI_TELEGRAM_BOT_TOKEN")
    secret = _required("VIMI_TELEGRAM_WEBHOOK_SECRET")
    public_host = _required("VIMI_PUBLIC_HOST")
    webhook_url = f"https://{public_host}/telegram/webhook"

    response = httpx.post(
        f"https://api.telegram.org/bot{token}/setWebhook",
        data={
            "url": webhook_url,
            "secret_token": secret,
            "drop_pending_updates": "true",
        },
        timeout=20.0,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram rejected webhook configuration: {payload}")

    info = httpx.get(
        f"https://api.telegram.org/bot{token}/getWebhookInfo",
        timeout=20.0,
    )
    info.raise_for_status()
    info_payload = info.json()
    configured_url = str(info_payload.get("result", {}).get("url", ""))
    if configured_url != webhook_url:
        raise RuntimeError(
            f"Telegram webhook verification failed: expected {webhook_url!r}, got {configured_url!r}"
        )

    print(f"Telegram webhook configured: {webhook_url}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Webhook configuration failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
