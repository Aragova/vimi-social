import json
from typing import Protocol

import httpx

from vimi_social.telegram.menus import OutgoingMessage


class TelegramGatewayError(RuntimeError):
    pass


class TelegramGatewayRejected(TelegramGatewayError):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"Telegram Bot API rejected request with HTTP {status_code}")


class TelegramGatewayRateLimited(TelegramGatewayError):
    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Telegram Bot API rate limited request; retry after {retry_after_seconds}s")


class TelegramGatewayAmbiguous(TelegramGatewayError):
    pass


class TelegramGateway(Protocol):
    async def send_message(self, chat_id: int, message: OutgoingMessage) -> None: ...

    async def answer_callback_query(self, callback_query_id: str) -> None: ...

    async def aclose(self) -> None: ...


class TelegramBotApiClient:
    def __init__(
        self,
        bot_token: str,
        *,
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        token = bot_token.strip()
        if not token:
            raise ValueError("telegram bot token must not be empty")
        self._base_url = f"https://api.telegram.org/bot{token}"
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)

    async def send_message(self, chat_id: int, message: OutgoingMessage) -> None:
        payload: dict[str, object] = {
            "chat_id": chat_id,
            "text": message.text,
        }
        if message.keyboard:
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [
                        {"text": button.text, "callback_data": button.callback_data}
                        for button in row
                    ]
                    for row in message.keyboard
                ]
            }
        await self._post("sendMessage", payload)

    async def answer_callback_query(self, callback_query_id: str) -> None:
        await self._post(
            "answerCallbackQuery",
            {"callback_query_id": callback_query_id},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _post(self, method: str, payload: dict[str, object]) -> None:
        try:
            response = await self._client.post(f"{self._base_url}/{method}", json=payload)
        except httpx.HTTPError:
            raise TelegramGatewayAmbiguous(
                "Telegram Bot API transport outcome is unknown"
            ) from None

        status_code = response.status_code
        if status_code == 429:
            raise TelegramGatewayRateLimited(_retry_after_seconds(response)) from None
        if 400 <= status_code < 500:
            raise TelegramGatewayRejected(status_code) from None
        if status_code >= 300:
            raise TelegramGatewayAmbiguous(
                f"Telegram Bot API outcome is unknown after HTTP {status_code}"
            ) from None


def _retry_after_seconds(response: httpx.Response) -> int:
    try:
        payload: object = json.loads(response.text)
    except json.JSONDecodeError:
        return 1
    if not isinstance(payload, dict):
        return 1
    parameters = payload.get("parameters")
    if not isinstance(parameters, dict):
        return 1
    raw_retry_after = parameters.get("retry_after")
    if not isinstance(raw_retry_after, int):
        return 1
    return max(1, min(raw_retry_after, 86_400))
