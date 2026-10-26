import json
from pathlib import Path
from typing import Protocol, cast

import httpx

from vimi_social.telegram.menus import InlineButton, OutgoingMessage


class TelegramGatewayError(RuntimeError):
    pass


class TelegramGatewayRejected(TelegramGatewayError):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"Telegram Bot API rejected request with HTTP {status_code}")


class TelegramGatewayRateLimited(TelegramGatewayError):
    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"Telegram Bot API rate limited request; retry after {retry_after_seconds}s"
        )


class TelegramGatewayAmbiguous(TelegramGatewayError):
    pass


class TelegramGateway(Protocol):
    async def send_message(self, chat_id: int, message: OutgoingMessage) -> None: ...

    async def edit_message(
        self,
        chat_id: int,
        message_id: int,
        message: OutgoingMessage,
    ) -> None: ...

    async def send_video(
        self,
        chat_id: int,
        video_path: Path,
        message: OutgoingMessage,
    ) -> None: ...

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
                    [_button_payload(button) for button in row] for row in message.keyboard
                ]
            }
        await self._post_json("sendMessage", payload)

    async def edit_message(
        self,
        chat_id: int,
        message_id: int,
        message: OutgoingMessage,
    ) -> None:
        payload: dict[str, object] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": message.text,
        }
        if message.keyboard:
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [_button_payload(button) for button in row] for row in message.keyboard
                ]
            }
        try:
            response = await self._client.post(
                f"{self._base_url}/editMessageText",
                json=payload,
            )
        except httpx.HTTPError:
            raise TelegramGatewayAmbiguous(
                "Telegram Bot API edit outcome is unknown"
            ) from None
        if response.status_code == 400 and "message is not modified" in response.text.casefold():
            return
        self._raise_for_response(response)

    async def send_video(
        self,
        chat_id: int,
        video_path: Path,
        message: OutgoingMessage,
    ) -> None:
        if not video_path.is_file():
            raise TelegramGatewayRejected(400)
        data: dict[str, str] = {
            "chat_id": str(chat_id),
            "caption": message.text,
            "supports_streaming": "true",
        }
        if message.keyboard:
            data["reply_markup"] = json.dumps(
                {
                    "inline_keyboard": [
                        [_button_payload(button) for button in row] for row in message.keyboard
                    ]
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        try:
            with video_path.open("rb") as handle:
                response = await self._client.post(
                    f"{self._base_url}/sendVideo",
                    data=data,
                    files={"video": (video_path.name, handle, "video/mp4")},
                )
        except (httpx.HTTPError, OSError):
            raise TelegramGatewayAmbiguous(
                "Telegram Bot API video outcome is unknown"
            ) from None
        self._raise_for_response(response)

    async def answer_callback_query(self, callback_query_id: str) -> None:
        await self._post_json(
            "answerCallbackQuery",
            {"callback_query_id": callback_query_id},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _post_json(self, method: str, payload: dict[str, object]) -> None:
        try:
            response = await self._client.post(f"{self._base_url}/{method}", json=payload)
        except httpx.HTTPError:
            raise TelegramGatewayAmbiguous(
                "Telegram Bot API transport outcome is unknown"
            ) from None
        self._raise_for_response(response)

    def _raise_for_response(self, response: httpx.Response) -> None:
        status_code = response.status_code
        if status_code == 429:
            raise TelegramGatewayRateLimited(_retry_after_seconds(response)) from None
        if 400 <= status_code < 500:
            raise TelegramGatewayRejected(status_code) from None
        if status_code >= 300:
            raise TelegramGatewayAmbiguous(
                f"Telegram Bot API outcome is unknown after HTTP {status_code}"
            ) from None


def _button_payload(button: InlineButton) -> dict[str, str]:
    if button.callback_data is not None:
        return {"text": button.text, "callback_data": button.callback_data}
    if button.url is not None:
        return {"text": button.text, "url": button.url}
    raise ValueError("inline button has no action")


def _retry_after_seconds(response: httpx.Response) -> int:
    try:
        decoded: object = json.loads(response.text)
    except json.JSONDecodeError:
        return 1
    if type(decoded) is not dict:
        return 1

    root = cast(dict[str, object], decoded)
    parameters_raw: object = root.get("parameters")
    if type(parameters_raw) is not dict:
        return 1

    parameters = cast(dict[str, object], parameters_raw)
    raw_retry_after: object = parameters.get("retry_after")
    if isinstance(raw_retry_after, bool) or not isinstance(raw_retry_after, int):
        return 1
    return max(1, min(raw_retry_after, 86_400))
