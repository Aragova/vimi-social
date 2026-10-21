from typing import Protocol

from vimi_social.source.models import SourceTask
from vimi_social.telegram.identity import (
    TelegramIdentityResolver,
    TelegramPrincipal,
    TelegramUpdateClaim,
    TelegramUpdateGuard,
)
from vimi_social.telegram.menus import (
    build_ai_search_prompt,
    build_ai_search_queued,
    build_feed_prompt,
    build_main_menu,
    build_source_menu,
    build_upload_prompt,
)
from vimi_social.telegram.models import TelegramCallbackQuery, TelegramUpdate, TelegramUser
from vimi_social.telegram.outgoing import TelegramMessageRetryAfter, TelegramMessenger


class SourceIntakePort(Protocol):
    def begin_ai_search(self, principal: TelegramPrincipal) -> None: ...

    def consume_ai_search_text(
        self,
        update_id: int,
        principal: TelegramPrincipal,
        query_text: str,
    ) -> SourceTask | None: ...


class TelegramUpdateBusy(RuntimeError):
    pass


class TelegramUpdateRetryAfter(RuntimeError):
    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"retry Telegram update after {retry_after_seconds}s")


class TelegramBotService:
    def __init__(
        self,
        identity_resolver: TelegramIdentityResolver,
        update_guard: TelegramUpdateGuard,
        messenger: TelegramMessenger,
        source_intake: SourceIntakePort | None = None,
    ) -> None:
        self._identity_resolver = identity_resolver
        self._update_guard = update_guard
        self._messenger = messenger
        self._source_intake = source_intake

    async def handle_update(self, update: TelegramUpdate) -> None:
        actor = _extract_actor(update)
        claim = self._update_guard.claim(update.update_id, actor.id if actor is not None else None)
        if claim is TelegramUpdateClaim.PROCESSED:
            return
        if claim is TelegramUpdateClaim.BUSY:
            raise TelegramUpdateBusy(f"telegram update {update.update_id} is already processing")

        try:
            if update.message is not None:
                await self._handle_message(update)
            elif update.callback_query is not None:
                await self._handle_callback(update.update_id, update.callback_query)
        except TelegramMessageRetryAfter as error:
            self._update_guard.defer(update.update_id, error.retry_after_seconds)
            raise TelegramUpdateRetryAfter(error.retry_after_seconds) from None

        self._update_guard.complete(update.update_id)

    async def aclose(self) -> None:
        await self._messenger.aclose()

    async def _handle_message(self, update: TelegramUpdate) -> None:
        message = update.message
        if message is None or message.from_user is None or message.from_user.is_bot:
            return
        if message.chat.type != "private" or message.text is None:
            return

        tokens = message.text.strip().split(maxsplit=1)
        if tokens and tokens[0].split("@", maxsplit=1)[0] == "/start":
            principal = self._identity_resolver.resolve(message.from_user)
            await self._messenger.send_message(
                update.update_id,
                "start-main-menu",
                message.chat.id,
                build_main_menu(principal.locale),
            )
            return

        if self._source_intake is None:
            return
        principal = self._identity_resolver.resolve(message.from_user)
        task = self._source_intake.consume_ai_search_text(
            update.update_id,
            principal,
            message.text,
        )
        if task is None:
            return
        await self._messenger.send_message(
            update.update_id,
            "ai-search-task-queued",
            message.chat.id,
            build_ai_search_queued(principal.locale),
        )

    async def _handle_callback(
        self,
        update_id: int,
        callback: TelegramCallbackQuery,
    ) -> None:
        if callback.from_user.is_bot or callback.message is None or callback.data is None:
            return
        if callback.message.chat.type != "private":
            return

        principal = self._identity_resolver.resolve(callback.from_user)
        await self._messenger.answer_callback_query(callback.id)

        if callback.data == "task:new":
            action = "task-new-source-menu"
            outgoing = build_source_menu(principal.locale)
        elif callback.data == "source:ai_search":
            if self._source_intake is not None:
                self._source_intake.begin_ai_search(principal)
            action = "source-ai-search-prompt"
            outgoing = build_ai_search_prompt(principal.locale)
        elif callback.data == "source:manual_upload":
            action = "source-manual-upload-prompt"
            outgoing = build_upload_prompt(principal.locale)
        elif callback.data == "source:feed":
            action = "source-feed-prompt"
            outgoing = build_feed_prompt(principal.locale)
        else:
            return

        await self._messenger.send_message(
            update_id,
            action,
            callback.message.chat.id,
            outgoing,
        )


def _extract_actor(update: TelegramUpdate) -> TelegramUser | None:
    if update.message is not None:
        return update.message.from_user
    if update.callback_query is not None:
        return update.callback_query.from_user
    return None
