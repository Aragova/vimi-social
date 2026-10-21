from typing import Protocol
from uuid import UUID

from vimi_social.source.service import SourceTaskService
from vimi_social.telegram.identity import (
    TelegramIdentityResolver,
    TelegramUpdateClaim,
    TelegramUpdateGuard,
)
from vimi_social.telegram.menus import (
    build_ai_search_prompt,
    build_ai_search_started,
    build_candidate_selected,
    build_feed_prompt,
    build_main_menu,
    build_scout_quota_exceeded,
    build_source_menu,
    build_upload_prompt,
)
from vimi_social.telegram.models import TelegramCallbackQuery, TelegramUpdate, TelegramUser
from vimi_social.telegram.outgoing import TelegramMessageRetryAfter, TelegramMessenger
from vimi_social.usage.repository import CapacityExceeded


class ScoutWorkflowStarter(Protocol):
    async def start(self, operation_key: str, execution_token: str) -> None: ...


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
        source_tasks: SourceTaskService,
        scout_starter: ScoutWorkflowStarter,
    ) -> None:
        self._identity_resolver = identity_resolver
        self._update_guard = update_guard
        self._messenger = messenger
        self._source_tasks = source_tasks
        self._scout_starter = scout_starter

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

        text = message.text.strip()
        tokens = text.split(maxsplit=1)
        command = tokens[0].split("@", maxsplit=1)[0] if tokens else ""
        principal = self._identity_resolver.resolve(message.from_user)

        if command == "/start":
            await self._messenger.send_message(
                update.update_id,
                "start-main-menu",
                message.chat.id,
                build_main_menu(principal.locale),
            )
            return

        try:
            task = self._source_tasks.submit_ai_search_intent(
                principal,
                update_id=update.update_id,
                message_id=message.message_id,
                chat_id=message.chat.id,
                intent=text,
            )
        except CapacityExceeded:
            await self._messenger.send_message(
                update.update_id,
                "ai-search-quota-exceeded",
                message.chat.id,
                build_scout_quota_exceeded(principal.locale),
            )
            return

        if task is None:
            return

        await self._scout_starter.start(
            task.operation_key.value,
            str(task.execution_token),
        )
        await self._messenger.send_message(
            update.update_id,
            "ai-search-started",
            message.chat.id,
            build_ai_search_started(principal.locale),
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

        if callback.data in {"task:new", "menu:sources"}:
            action = "task-new-source-menu"
            outgoing = build_source_menu(principal.locale)
        elif callback.data == "source:ai_search":
            self._source_tasks.begin_ai_search(
                principal,
                chat_id=callback.message.chat.id,
            )
            action = "source-ai-search-prompt"
            outgoing = build_ai_search_prompt(principal.locale)
        elif callback.data == "source:manual_upload":
            action = "source-manual-upload-prompt"
            outgoing = build_upload_prompt(principal.locale)
        elif callback.data == "source:feed":
            action = "source-feed-prompt"
            outgoing = build_feed_prompt(principal.locale)
        elif callback.data.startswith("candidate:select:"):
            candidate_id = _parse_candidate_id(callback.data)
            if candidate_id is None:
                return
            selected = self._source_tasks.select_candidate(principal, candidate_id)
            action = f"candidate-selected:{candidate_id}"
            outgoing = build_candidate_selected(principal.locale, selected=selected)
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


def _parse_candidate_id(callback_data: str) -> UUID | None:
    _, _, raw_id = callback_data.partition("candidate:select:")
    if not raw_id:
        return None
    try:
        return UUID(raw_id)
    except ValueError:
        return None
