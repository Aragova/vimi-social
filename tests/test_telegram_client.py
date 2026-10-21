import httpx
import pytest

from vimi_social.telegram.client import (
    TelegramBotApiClient,
    TelegramGatewayAmbiguous,
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
