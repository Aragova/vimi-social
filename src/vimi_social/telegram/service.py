from vimi_social.telegram.client import TelegramGateway
from vimi_social.telegram.identity import (
    TelegramIdentityResolver,
    TelegramUpdateClaim,
    TelegramUpdateGuard,
)
from vimi_social.telegram.menus import (
    build_ai_search_prompt,
    build_feed_prompt,
    build_main_menu,
    build_source_menu,
    build_upload_prompt,
)
from vimi_social.telegram.models import TelegramCallbackQuery, TelegramUpdate, TelegramUser


class TelegramUpdateBusy(RuntimeError):
    pass


class TelegramBotService:
    def __init__(
        self,
        identity_resolver: TelegramIdentityResolver,
        update_guard: TelegramUpdateGuard,
        gateway: TelegramGateway,
    ) -> None:
        self._identity_resolver = identity_resolver
        self._update_guard = update_guard
        self._gateway = gateway

    async def handle_update(self, update: TelegramUpdate) -> None:
        actor = _extract_actor(update)
        claim = self._update_guard.claim(update.update_id, actor.id if actor is not None else None)
        if claim is TelegramUpdateClaim.PROCESSED:
            return
        if claim is TelegramUpdateClaim.BUSY:
            raise TelegramUpdateBusy(f"telegram update {update.update_id} is already processing")

        if update.message is not None:
            await self._handle_message(update)
        elif update.callback_query is not None:
            await self._handle_callback(update.callback_query)

        self._update_guard.complete(update.update_id)

    async def aclose(self) -> None:
        await self._gateway.aclose()

    async def _handle_message(self, update: TelegramUpdate) -> None:
        message = update.message
        if message is None or message.from_user is None or message.from_user.is_bot:
            return
        if message.chat.type != "private":
            return
        if message.text is None or not message.text.split(maxsplit=1)[0].startswith("/start"):
            return

        principal = self._identity_resolver.resolve(message.from_user)
        await self._gateway.send_message(message.chat.id, build_main_menu(principal.locale))

    async def _handle_callback(self, callback: TelegramCallbackQuery) -> None:
        if callback.from_user.is_bot or callback.message is None or callback.data is None:
            return
        if callback.message.chat.type != "private":
            return

        principal = self._identity_resolver.resolve(callback.from_user)
        await self._gateway.answer_callback_query(callback.id)

        if callback.data == "task:new":
            outgoing = build_source_menu(principal.locale)
        elif callback.data == "source:ai_search":
            outgoing = build_ai_search_prompt(principal.locale)
        elif callback.data == "source:manual_upload":
            outgoing = build_upload_prompt(principal.locale)
        elif callback.data == "source:feed":
            outgoing = build_feed_prompt(principal.locale)
        else:
            return

        await self._gateway.send_message(callback.message.chat.id, outgoing)


def _extract_actor(update: TelegramUpdate) -> TelegramUser | None:
    if update.message is not None:
        return update.message.from_user
    if update.callback_query is not None:
        return update.callback_query.from_user
    return None
