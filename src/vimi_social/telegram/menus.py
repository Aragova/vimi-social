from dataclasses import dataclass

from vimi_social.domain.international import UiLocale
from vimi_social.i18n.catalog import MessageKey, translate


@dataclass(frozen=True, slots=True)
class InlineButton:
    text: str
    callback_data: str


@dataclass(frozen=True, slots=True)
class OutgoingMessage:
    text: str
    keyboard: tuple[tuple[InlineButton, ...], ...] = ()


def build_main_menu(locale: UiLocale) -> OutgoingMessage:
    return OutgoingMessage(
        text=translate(MessageKey.WELCOME, locale),
        keyboard=(
            (InlineButton(translate(MessageKey.NEW_TASK, locale), "task:new"),),
            (
                InlineButton(translate(MessageKey.SOURCES, locale), "menu:sources"),
                InlineButton(translate(MessageKey.DESTINATIONS, locale), "menu:destinations"),
            ),
            (
                InlineButton(translate(MessageKey.AUTOMATIONS, locale), "menu:automations"),
                InlineButton(translate(MessageKey.PUBLICATIONS, locale), "menu:publications"),
            ),
            (
                InlineButton(translate(MessageKey.ANALYTICS, locale), "menu:analytics"),
                InlineButton(translate(MessageKey.PLAN, locale), "menu:plan"),
            ),
            (InlineButton(translate(MessageKey.SETTINGS, locale), "menu:settings"),),
        ),
    )


def build_source_menu(locale: UiLocale) -> OutgoingMessage:
    return OutgoingMessage(
        text=translate(MessageKey.CHOOSE_SOURCE, locale),
        keyboard=(
            (InlineButton(translate(MessageKey.SOURCE_AI, locale), "source:ai_search"),),
            (InlineButton(translate(MessageKey.SOURCE_UPLOAD, locale), "source:manual_upload"),),
            (InlineButton(translate(MessageKey.SOURCE_FEED, locale), "source:feed"),),
        ),
    )


def build_ai_search_prompt(locale: UiLocale) -> OutgoingMessage:
    return OutgoingMessage(text=translate(MessageKey.AI_SEARCH_PROMPT, locale))


def build_ai_search_queued(locale: UiLocale) -> OutgoingMessage:
    return OutgoingMessage(text=translate(MessageKey.AI_SEARCH_QUEUED, locale))


def build_upload_prompt(locale: UiLocale) -> OutgoingMessage:
    return OutgoingMessage(text=translate(MessageKey.UPLOAD_PROMPT, locale))


def build_feed_prompt(locale: UiLocale) -> OutgoingMessage:
    return OutgoingMessage(text=translate(MessageKey.FEED_PROMPT, locale))
