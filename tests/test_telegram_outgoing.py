import pytest

from vimi_social.telegram.client import (
    TelegramGatewayAmbiguous,
    TelegramGatewayRateLimited,
    TelegramGatewayRejected,
)
from vimi_social.telegram.menus import OutgoingMessage
from vimi_social.telegram.outgoing import (
    TelegramDispatchDecision,
    TelegramMessageRetryAfter,
    TelegramMessenger,
    TelegramOutgoingState,
)


class FakeStore:
    def __init__(self, decision: TelegramDispatchDecision) -> None:
        self.decision = decision
        self.finished: list[TelegramOutgoingState] = []
        self.deferred: list[int] = []

    def prepare(
        self,
        operation_key: str,
        update_id: int,
        chat_id: int,
        action: str,
        payload_sha256: str,
    ) -> TelegramOutgoingState:
        assert operation_key
        assert update_id >= 0
        assert chat_id
        assert action
        assert len(payload_sha256) == 64
        return TelegramOutgoingState.READY

    def begin(self, operation_key: str) -> TelegramDispatchDecision:
        assert operation_key
        return self.decision

    def finish(self, operation_key: str, state: TelegramOutgoingState) -> None:
        assert operation_key
        self.finished.append(state)

    def defer(self, operation_key: str, retry_after_seconds: int) -> None:
        assert operation_key
        self.deferred.append(retry_after_seconds)


class FakeGateway:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.send_count = 0

    async def send_message(self, chat_id: int, message: OutgoingMessage) -> None:
        self.send_count += 1
        assert chat_id
        assert message.text
        if self.failure is not None:
            raise self.failure

    async def answer_callback_query(self, callback_query_id: str) -> None:
        assert callback_query_id

    async def aclose(self) -> None:
        return None


async def test_unknown_existing_operation_is_never_sent_again() -> None:
    store = FakeStore(TelegramDispatchDecision.UNKNOWN)
    gateway = FakeGateway()
    messenger = TelegramMessenger(store, gateway)

    state = await messenger.send_message(1, "main", 10, OutgoingMessage("hello"))

    assert state is TelegramOutgoingState.UNKNOWN
    assert gateway.send_count == 0
    assert store.finished == []


async def test_retry_wait_existing_operation_is_not_sent_early() -> None:
    store = FakeStore(TelegramDispatchDecision.RETRY_WAIT)
    gateway = FakeGateway()
    messenger = TelegramMessenger(store, gateway)

    with pytest.raises(TelegramMessageRetryAfter) as error:
        await messenger.send_message(4, "main", 10, OutgoingMessage("hello"))

    assert error.value.retry_after_seconds == 1
    assert gateway.send_count == 0
    assert store.finished == []


async def test_rate_limited_gateway_outcome_is_deferred_not_failed() -> None:
    store = FakeStore(TelegramDispatchDecision.DISPATCH)
    gateway = FakeGateway(TelegramGatewayRateLimited(23))
    messenger = TelegramMessenger(store, gateway)

    with pytest.raises(TelegramMessageRetryAfter) as error:
        await messenger.send_message(5, "main", 10, OutgoingMessage("hello"))

    assert error.value.retry_after_seconds == 23
    assert gateway.send_count == 1
    assert store.deferred == [23]
    assert store.finished == []


async def test_ambiguous_gateway_outcome_is_persisted_as_unknown() -> None:
    store = FakeStore(TelegramDispatchDecision.DISPATCH)
    gateway = FakeGateway(TelegramGatewayAmbiguous("safe error"))
    messenger = TelegramMessenger(store, gateway)

    state = await messenger.send_message(2, "main", 10, OutgoingMessage("hello"))

    assert state is TelegramOutgoingState.UNKNOWN
    assert gateway.send_count == 1
    assert store.finished == [TelegramOutgoingState.UNKNOWN]


async def test_rejected_gateway_outcome_is_persisted_as_failed_safe() -> None:
    store = FakeStore(TelegramDispatchDecision.DISPATCH)
    gateway = FakeGateway(TelegramGatewayRejected(403))
    messenger = TelegramMessenger(store, gateway)

    state = await messenger.send_message(3, "main", 10, OutgoingMessage("hello"))

    assert state is TelegramOutgoingState.FAILED_SAFE
    assert gateway.send_count == 1
    assert store.finished == [TelegramOutgoingState.FAILED_SAFE]
