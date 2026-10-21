import json

import httpx
import pytest

from vimi_social.telegram.client import TelegramBotApiClient
from vimi_social.telegram.menus import InlineButton, OutgoingMessage


@pytest.mark.asyncio
async def test_telegram_client_serializes_url_and_callback_buttons() -> None:
    seen_payload: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        decoded = json.loads(request.content)
        assert isinstance(decoded, dict)
        seen_payload.update(decoded)
        return httpx.Response(200, json={"ok": True})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = TelegramBotApiClient("test-token", client=http_client)

    await gateway.send_message(
        123,
        OutgoingMessage(
            "results",
            keyboard=(
                (
                    InlineButton("View", url="https://x.com/i/web/status/1"),
                    InlineButton("Select", "candidate:select:00000000-0000-0000-0000-000000000001"),
                ),
            ),
        ),
    )

    reply_markup = seen_payload["reply_markup"]
    assert isinstance(reply_markup, dict)
    keyboard = reply_markup["inline_keyboard"]
    assert isinstance(keyboard, list)
    assert keyboard[0][0]["url"] == "https://x.com/i/web/status/1"
    assert keyboard[0][1]["callback_data"].startswith("candidate:select:")
    await gateway.aclose()
