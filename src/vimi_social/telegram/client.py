from typing import Protocol

import httpx

from vimi_social.telegram.menus import OutgoingMessage


class TelegramGateway(Protocol):
    async def send_message(self, chat_id: int, message: OutgoingMessage) -> None: ...

    async def answer_callback_query(self, callback_query_id: str) -> None: ...

    async def aclose(self) -> None: ...


class TelegramBotApiClient:
    def __init__(self, bot_token: str, *, timeout_seconds: float = 10.0) -> None:
        token = bot_token.strip()
        if not token:
            raise ValueError("telegram bot token must not be empty")
        self._base_url = f"https://api.telegram.org/bot{token}"
        self._client = httpx.AsyncClient(timeout=timeout_seconds)

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
        response = await self._client.post(f"{self._base_url}/sendMessage", json=payload)
        response.raise_for_status()

    async def answer_callback_query(self, callback_query_id: str) -> None:
        response = await self._client.post(
            f"{self._base_url}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id},
        )
        response.raise_for_status()

    async def aclose(self) -> None:
        await self._client.aclose()
