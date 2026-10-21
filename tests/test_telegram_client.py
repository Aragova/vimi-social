import httpx
import pytest

from vimi_social.telegram.client import (
    TelegramBotApiClient,
    TelegramGatewayAmbiguous,
    TelegramGatewayRateLimited,
    TelegramGatewayRejected,
)
from vimi_social.telegram.menus import OutgoingMessage


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
