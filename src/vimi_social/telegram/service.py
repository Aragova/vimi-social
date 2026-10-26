from typing import Protocol
from uuid import UUID

from vimi_social.domain.media import MediaPreparationWorkflowInput
from vimi_social.domain.publication import PublicationWorkflowInput
from vimi_social.domain.source import ScoutContinuationWorkflowInput
from vimi_social.media.service import MediaPreparationService
from vimi_social.publication.service import PublicationService
from vimi_social.source.service import SourceTaskIntentTooLong, SourceTaskService
from vimi_social.telegram.identity import (
    TelegramIdentityResolver,
    TelegramUpdateClaim,
    TelegramUpdateGuard,
)
from vimi_social.telegram.menus import (
    build_ai_search_intent_too_long,
    build_ai_search_prompt,
    build_ai_search_started,
    build_feed_prompt,
    build_main_menu,
    build_media_preparation_quota_exceeded,
    build_media_preparation_started,
    build_media_rights_declined,
    build_media_rights_prompt,
    build_publication_not_available,
    build_publication_quota_exceeded,
    build_publication_started,
    build_scout_quota_exceeded,
    build_source_menu,
    build_upload_prompt,
)
from vimi_social.telegram.models import TelegramCallbackQuery, TelegramUpdate, TelegramUser
from vimi_social.telegram.outgoing import TelegramMessageRetryAfter, TelegramMessenger
from vimi_social.telegram.scout_results import build_scout_result_page
from vimi_social.usage.repository import CapacityExceeded


class ScoutWorkflowStarter(Protocol):
    async def start(self, operation_key: str, execution_token: str) -> None: ...

    async def start_continuation(
        self,
        workflow_input: ScoutContinuationWorkflowInput,
    ) -> None: ...


class MediaWorkflowStarter(Protocol):
    async def start(self, workflow_input: MediaPreparationWorkflowInput) -> None: ...


class PublicationWorkflowStarter(Protocol):
    async def start(self, workflow_input: PublicationWorkflowInput) -> None: ...


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
        media_preparations: MediaPreparationService,
        media_starter: MediaWorkflowStarter,
        publications: PublicationService | None = None,
        publication_starter: PublicationWorkflowStarter | None = None,
    ) -> None:
        self._identity_resolver = identity_resolver
        self._update_guard = update_guard
        self._messenger = messenger
        self._source_tasks = source_tasks
        self._scout_starter = scout_starter
        self._media_preparations = media_preparations
        self._media_starter = media_starter
        self._publications = publications
        self._publication_starter = publication_starter

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
        except SourceTaskIntentTooLong:
            await self._messenger.send_message(
                update.update_id,
                "ai-search-intent-too-long",
                message.chat.id,
                build_ai_search_intent_too_long(principal.locale),
            )
            return
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
        elif callback.data.startswith("scout:page:"):
            parsed_page = _parse_scout_page_callback(callback.data)
            if parsed_page is None:
                return
            task_id, page = parsed_page
            candidates = self._source_tasks.get_ai_search_candidates(principal, task_id)
            if candidates is None:
                return
            outgoing = build_scout_result_page(
                principal.locale,
                candidates,
                task_id=task_id,
                page=page,
            )
            await self._messenger.edit_message(
                update_id,
                f"scout-page:{task_id}:{page}",
                callback.message.chat.id,
                callback.message.message_id,
                outgoing,
            )
            return
        elif callback.data.startswith("scout:more:"):
            task_id = _parse_uuid_suffix(callback.data, "scout:more:")
            if task_id is None:
                return
            try:
                continuation_input = self._source_tasks.prepare_ai_search_continuation(
                    principal,
                    task_id=task_id,
                    update_id=update_id,
                    message_id=callback.message.message_id,
                    chat_id=callback.message.chat.id,
                )
            except CapacityExceeded:
                action = f"scout-more-quota:{task_id}"
                outgoing = build_scout_quota_exceeded(principal.locale)
            else:
                if continuation_input is None:
                    return
                await self._scout_starter.start_continuation(continuation_input)
                return
        elif callback.data.startswith("candidate:select:"):
            candidate_id = _parse_uuid_suffix(callback.data, "candidate:select:")
            if candidate_id is None:
                return
            preparation = self._media_preparations.select_candidate(principal, candidate_id)
            if preparation is None:
                action = f"candidate-not-available:{candidate_id}"
                from vimi_social.telegram.menus import build_candidate_selected

                outgoing = build_candidate_selected(principal.locale, selected=False)
            else:
                action = f"media-rights:{preparation.id}"
                outgoing = build_media_rights_prompt(principal.locale, preparation.id)
        elif callback.data.startswith("media:rights:yes:"):
            preparation_id = _parse_uuid_suffix(callback.data, "media:rights:yes:")
            if preparation_id is None:
                return
            try:
                workflow_input = self._media_preparations.confirm_rights(
                    principal,
                    preparation_id,
                )
            except CapacityExceeded:
                action = f"media-quota:{preparation_id}"
                outgoing = build_media_preparation_quota_exceeded(principal.locale)
            else:
                if workflow_input is None:
                    return
                await self._media_starter.start(workflow_input)
                action = f"media-started:{preparation_id}"
                outgoing = build_media_preparation_started(principal.locale)
        elif callback.data.startswith("media:rights:no:"):
            preparation_id = _parse_uuid_suffix(callback.data, "media:rights:no:")
            if preparation_id is None:
                return
            declined = self._media_preparations.decline_rights(principal, preparation_id)
            if not declined:
                return
            action = f"media-rights-declined:{preparation_id}"
            outgoing = build_media_rights_declined(principal.locale)
        elif callback.data.startswith("publication:approve:"):
            publication_id = _parse_uuid_suffix(callback.data, "publication:approve:")
            if publication_id is None:
                return
            if self._publications is None or self._publication_starter is None:
                action = f"publication-not-configured:{publication_id}"
                outgoing = build_publication_not_available(principal.locale)
            else:
                try:
                    publication_input = self._publications.approve(
                        principal,
                        publication_id,
                    )
                except CapacityExceeded:
                    action = f"publication-quota:{publication_id}"
                    outgoing = build_publication_quota_exceeded(principal.locale)
                else:
                    if publication_input is None:
                        action = f"publication-not-available:{publication_id}"
                        outgoing = build_publication_not_available(principal.locale)
                    else:
                        await self._publication_starter.start(publication_input)
                        action = f"publication-started:{publication_id}"
                        outgoing = build_publication_started(principal.locale)
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


def _parse_uuid_suffix(callback_data: str, prefix: str) -> UUID | None:
    if not callback_data.startswith(prefix):
        return None
    raw_id = callback_data[len(prefix) :]
    if not raw_id:
        return None
    try:
        return UUID(raw_id)
    except ValueError:
        return None


def _parse_scout_page_callback(callback_data: str) -> tuple[UUID, int] | None:
    prefix = "scout:page:"
    if not callback_data.startswith(prefix):
        return None
    raw = callback_data[len(prefix) :]
    raw_id, separator, raw_page = raw.rpartition(":")
    if not separator or not raw_id or not raw_page:
        return None
    try:
        task_id = UUID(raw_id)
        page = int(raw_page)
    except ValueError:
        return None
    if page < 0:
        return None
    return task_id, page
