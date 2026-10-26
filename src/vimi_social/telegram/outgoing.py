import hashlib
import json
from collections.abc import Awaitable, Callable
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.orm import Session

from vimi_social.telegram.client import (
    TelegramGateway,
    TelegramGatewayAmbiguous,
    TelegramGatewayError,
    TelegramGatewayRateLimited,
    TelegramGatewayRejected,
)
from vimi_social.telegram.menus import InlineButton, OutgoingMessage


class TelegramOutgoingState(StrEnum):
    READY = "READY"
    DISPATCHING = "DISPATCHING"
    RETRY_WAIT = "RETRY_WAIT"
    CONFIRMED = "CONFIRMED"
    UNKNOWN = "UNKNOWN"
    FAILED_SAFE = "FAILED_SAFE"


class TelegramDispatchDecision(StrEnum):
    DISPATCH = "DISPATCH"
    RETRY_WAIT = "RETRY_WAIT"
    CONFIRMED = "CONFIRMED"
    UNKNOWN = "UNKNOWN"
    FAILED_SAFE = "FAILED_SAFE"


class TelegramMessageRetryAfter(RuntimeError):
    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"retry Telegram delivery after {retry_after_seconds}s")


class TelegramOutgoingStorePort(Protocol):
    def prepare(
        self,
        operation_key: str,
        update_id: int,
        chat_id: int,
        action: str,
        payload_sha256: str,
    ) -> TelegramOutgoingState: ...

    def begin(self, operation_key: str) -> TelegramDispatchDecision: ...

    def finish(self, operation_key: str, state: TelegramOutgoingState) -> None: ...

    def defer(self, operation_key: str, retry_after_seconds: int) -> None: ...


class TelegramOutgoingStore:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def prepare(
        self,
        operation_key: str,
        update_id: int,
        chat_id: int,
        action: str,
        payload_sha256: str,
    ) -> TelegramOutgoingState:
        with self._session_factory() as session, session.begin():
            raw = session.execute(
                text(
                    """
                    SELECT prepare_telegram_outgoing(
                        :operation_key,
                        :update_id,
                        :chat_id,
                        :action,
                        :payload_sha256
                    )
                    """
                ),
                {
                    "operation_key": operation_key,
                    "update_id": update_id,
                    "chat_id": chat_id,
                    "action": action,
                    "payload_sha256": payload_sha256,
                },
            ).scalar_one()
        if not isinstance(raw, str):
            raise RuntimeError("prepare_telegram_outgoing returned a non-text result")
        return TelegramOutgoingState(raw)

    def begin(self, operation_key: str) -> TelegramDispatchDecision:
        with self._session_factory() as session, session.begin():
            raw = session.execute(
                text("SELECT begin_telegram_outgoing(:operation_key)"),
                {"operation_key": operation_key},
            ).scalar_one()
        if not isinstance(raw, str):
            raise RuntimeError("begin_telegram_outgoing returned a non-text result")
        return TelegramDispatchDecision(raw)

    def finish(self, operation_key: str, state: TelegramOutgoingState) -> None:
        if state not in {
            TelegramOutgoingState.CONFIRMED,
            TelegramOutgoingState.UNKNOWN,
            TelegramOutgoingState.FAILED_SAFE,
        }:
            raise ValueError("telegram outgoing finish state must be terminal")
        with self._session_factory() as session, session.begin():
            session.execute(
                text("SELECT finish_telegram_outgoing(:operation_key, :state)"),
                {"operation_key": operation_key, "state": state.value},
            )

    def defer(self, operation_key: str, retry_after_seconds: int) -> None:
        with self._session_factory() as session, session.begin():
            session.execute(
                text(
                    "SELECT defer_telegram_outgoing(:operation_key, :retry_after_seconds)"
                ),
                {
                    "operation_key": operation_key,
                    "retry_after_seconds": retry_after_seconds,
                },
            )


class TelegramMessenger:
    def __init__(self, store: TelegramOutgoingStorePort, gateway: TelegramGateway) -> None:
        self._store = store
        self._gateway = gateway

    async def send_message(
        self,
        update_id: int,
        action: str,
        chat_id: int,
        message: OutgoingMessage,
    ) -> TelegramOutgoingState:
        return await self._dispatch(
            update_id=update_id,
            action=action,
            chat_id=chat_id,
            payload_sha256=_message_fingerprint(chat_id, message),
            dispatch=lambda: self._gateway.send_message(chat_id, message),
        )

    async def edit_message(
        self,
        update_id: int,
        action: str,
        chat_id: int,
        message_id: int,
        message: OutgoingMessage,
    ) -> TelegramOutgoingState:
        return await self._dispatch(
            update_id=update_id,
            action=action,
            chat_id=chat_id,
            payload_sha256=_edit_message_fingerprint(chat_id, message_id, message),
            dispatch=lambda: self._gateway.edit_message(chat_id, message_id, message),
        )

    async def send_video(
        self,
        update_id: int,
        action: str,
        chat_id: int,
        video_path: Path,
        video_sha256: str,
        message: OutgoingMessage,
    ) -> TelegramOutgoingState:
        return await self._dispatch(
            update_id=update_id,
            action=action,
            chat_id=chat_id,
            payload_sha256=_video_fingerprint(chat_id, video_sha256, message),
            dispatch=lambda: self._gateway.send_video(chat_id, video_path, message),
        )

    async def _dispatch(
        self,
        *,
        update_id: int,
        action: str,
        chat_id: int,
        payload_sha256: str,
        dispatch: Callable[[], Awaitable[None]],
    ) -> TelegramOutgoingState:
        operation_key = f"telegram:update:{update_id}:{action}"
        self._store.prepare(operation_key, update_id, chat_id, action, payload_sha256)
        decision = self._store.begin(operation_key)

        if decision is TelegramDispatchDecision.RETRY_WAIT:
            raise TelegramMessageRetryAfter(1)
        if decision is TelegramDispatchDecision.CONFIRMED:
            return TelegramOutgoingState.CONFIRMED
        if decision is TelegramDispatchDecision.UNKNOWN:
            return TelegramOutgoingState.UNKNOWN
        if decision is TelegramDispatchDecision.FAILED_SAFE:
            return TelegramOutgoingState.FAILED_SAFE

        try:
            await dispatch()
        except TelegramGatewayRateLimited as error:
            self._store.defer(operation_key, error.retry_after_seconds)
            raise TelegramMessageRetryAfter(error.retry_after_seconds) from None
        except TelegramGatewayRejected:
            self._store.finish(operation_key, TelegramOutgoingState.FAILED_SAFE)
            return TelegramOutgoingState.FAILED_SAFE
        except TelegramGatewayAmbiguous:
            self._store.finish(operation_key, TelegramOutgoingState.UNKNOWN)
            return TelegramOutgoingState.UNKNOWN

        self._store.finish(operation_key, TelegramOutgoingState.CONFIRMED)
        return TelegramOutgoingState.CONFIRMED

    async def answer_callback_query(self, callback_query_id: str) -> None:
        try:
            await self._gateway.answer_callback_query(callback_query_id)
        except TelegramGatewayError:
            return

    async def aclose(self) -> None:
        await self._gateway.aclose()


def _message_fingerprint(chat_id: int, message: OutgoingMessage) -> str:
    payload = _message_payload(chat_id, message)
    return _fingerprint(payload)


def _edit_message_fingerprint(
    chat_id: int,
    message_id: int,
    message: OutgoingMessage,
) -> str:
    payload = _message_payload(chat_id, message)
    payload["message_id"] = message_id
    return _fingerprint(payload)


def _video_fingerprint(
    chat_id: int,
    video_sha256: str,
    message: OutgoingMessage,
) -> str:
    payload = _message_payload(chat_id, message)
    payload["video_sha256"] = video_sha256
    return _fingerprint(payload)


def _message_payload(chat_id: int, message: OutgoingMessage) -> dict[str, object]:
    return {
        "chat_id": chat_id,
        "text": message.text,
        "keyboard": [
            [_button_fingerprint(button) for button in row] for row in message.keyboard
        ],
    }


def _fingerprint(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _button_fingerprint(button: InlineButton) -> dict[str, str]:
    if button.callback_data is not None:
        return {"text": button.text, "callback_data": button.callback_data}
    if button.url is not None:
        return {"text": button.text, "url": button.url}
    raise ValueError("inline button has no action")
