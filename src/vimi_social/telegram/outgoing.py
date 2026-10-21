import hashlib
import json
from collections.abc import Callable
from enum import StrEnum
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.orm import Session

from vimi_social.telegram.client import (
    TelegramGateway,
    TelegramGatewayAmbiguous,
    TelegramGatewayError,
    TelegramGatewayRejected,
)
from vimi_social.telegram.menus import OutgoingMessage


class TelegramOutgoingState(StrEnum):
    READY = "READY"
    DISPATCHING = "DISPATCHING"
    CONFIRMED = "CONFIRMED"
    UNKNOWN = "UNKNOWN"
    FAILED_SAFE = "FAILED_SAFE"


class TelegramDispatchDecision(StrEnum):
    DISPATCH = "DISPATCH"
    CONFIRMED = "CONFIRMED"
    UNKNOWN = "UNKNOWN"
    FAILED_SAFE = "FAILED_SAFE"


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
        operation_key = f"telegram:update:{update_id}:{action}"
        payload_sha256 = _message_fingerprint(chat_id, message)
        self._store.prepare(operation_key, update_id, chat_id, action, payload_sha256)
        decision = self._store.begin(operation_key)

        if decision is TelegramDispatchDecision.CONFIRMED:
            return TelegramOutgoingState.CONFIRMED
        if decision is TelegramDispatchDecision.UNKNOWN:
            return TelegramOutgoingState.UNKNOWN
        if decision is TelegramDispatchDecision.FAILED_SAFE:
            return TelegramOutgoingState.FAILED_SAFE

        try:
            await self._gateway.send_message(chat_id, message)
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
    payload = {
        "chat_id": chat_id,
        "text": message.text,
        "keyboard": [
            [
                {"text": button.text, "callback_data": button.callback_data}
                for button in row
            ]
            for row in message.keyboard
        ],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
