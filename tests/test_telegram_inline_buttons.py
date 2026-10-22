import json
from typing import cast

import httpx
import pytest

from vimi_social.telegram.client import TelegramBotApiClient
from vimi_social.telegram.menus import InlineButton, OutgoingMessage


@pytest.mark.asyncio
async def test_telegram_client_serializes_url_and_callback_buttons() -> None:
    seen_payload: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        decoded_obj: object = json.loads(request.content)
        assert isinstance(decoded_obj, dict)
        decoded = cast(dict[str, object], decoded_obj)
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

    reply_markup_obj = seen_payload["reply_markup"]
    assert isinstance(reply_markup_obj, dict)
    reply_markup = cast(dict[str, object], reply_markup_obj)
    keyboard_obj = reply_markup["inline_keyboard"]
    assert isinstance(keyboard_obj, list)
    keyboard = cast(list[object], keyboard_obj)
    first_row_obj = keyboard[0]
    assert isinstance(first_row_obj, list)
    first_row = cast(list[object], first_row_obj)
    view_obj = first_row[0]
    select_obj = first_row[1]
    assert isinstance(view_obj, dict)
    assert isinstance(select_obj, dict)
    view = cast(dict[str, object], view_obj)
    select = cast(dict[str, object], select_obj)
    assert view["url"] == "https://x.com/i/web/status/1"
    callback_data = select["callback_data"]
    assert isinstance(callback_data, str)
    assert callback_data.startswith("candidate:select:")
    await gateway.aclose()
