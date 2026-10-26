import httpx
import pytest

from vimi_social.telegram.client import (
    TelegramBotApiClient,
    TelegramGatewayAmbiguous,
    TelegramGatewayRateLimited,
    TelegramGatewayRejected,
)
from vimi_social.telegram.menus import InlineButton, OutgoingMessage


@pytest.mark.asyncio
async def test_http_error_never_exposes_bot_token_or_request_url() -> None:
    token = "super-secret-bot-token"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = TelegramBotApiClient(token, client=http_client)

    with pytest.raises(TelegramGatewayRejected) as error:
        await gateway.send_message(123, OutgoingMessage("hello"))

    rendered = str(error.value)
    assert token not in rendered
    assert "api.telegram.org" not in rendered
    assert error.value.__cause__ is None
    await gateway.aclose()


@pytest.mark.asyncio
async def test_rate_limit_is_sanitized_and_preserves_retry_after() -> None:
    token = "super-secret-bot-token"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"ok": False, "parameters": {"retry_after": 17}},
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = TelegramBotApiClient(token, client=http_client)

    with pytest.raises(TelegramGatewayRateLimited) as error:
        await gateway.send_message(123, OutgoingMessage("hello"))

    assert error.value.retry_after_seconds == 17
    rendered = str(error.value)
    assert token not in rendered
    assert "api.telegram.org" not in rendered
    assert error.value.__cause__ is None
    await gateway.aclose()


@pytest.mark.asyncio
async def test_transport_error_is_sanitized_and_classified_ambiguous() -> None:
    token = "super-secret-bot-token"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("unsafe transport text", request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = TelegramBotApiClient(token, client=http_client)

    with pytest.raises(TelegramGatewayAmbiguous) as error:
        await gateway.send_message(123, OutgoingMessage("hello"))

    rendered = str(error.value)
    assert token not in rendered
    assert "api.telegram.org" not in rendered
    assert error.value.__cause__ is None
    await gateway.aclose()


@pytest.mark.asyncio
async def test_edit_message_uses_edit_message_text_with_inline_keyboard() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = TelegramBotApiClient("test-token", client=http_client)

    await gateway.edit_message(
        123,
        77,
        OutgoingMessage(
            "page two",
            keyboard=((InlineButton("➡️", "scout:page:test:2"),),),
        ),
    )

    assert len(seen) == 1
    assert seen[0].url.path.endswith("/editMessageText")
    payload = seen[0].read().decode("utf-8")
    assert '"message_id":77' in payload
    assert '"callback_data":"scout:page:test:2"' in payload
    await gateway.aclose()
