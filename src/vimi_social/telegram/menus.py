from dataclasses import dataclass

from vimi_social.domain.international import UiLocale
from vimi_social.domain.source import CandidateContent, ScoutRunResult, SourceTaskState
from vimi_social.i18n.catalog import MessageKey, translate


@dataclass(frozen=True, slots=True)
class InlineButton:
    text: str
    callback_data: str | None = None
    url: str | None = None

    def __post_init__(self) -> None:
        if (self.callback_data is None) == (self.url is None):
            raise ValueError("inline button must define exactly one action")


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


def build_ai_search_started(locale: UiLocale) -> OutgoingMessage:
    return OutgoingMessage(text=translate(MessageKey.AI_SEARCH_STARTED, locale))


def build_scout_quota_exceeded(locale: UiLocale) -> OutgoingMessage:
    return OutgoingMessage(text=translate(MessageKey.SCOUT_QUOTA_EXCEEDED, locale))


def build_candidate_selected(locale: UiLocale, *, selected: bool) -> OutgoingMessage:
    key = MessageKey.CANDIDATE_SELECTED if selected else MessageKey.CANDIDATE_NOT_AVAILABLE
    return OutgoingMessage(text=translate(key, locale))


def build_scout_results(
    locale: UiLocale,
    result: ScoutRunResult,
    candidates: tuple[CandidateContent, ...],
) -> OutgoingMessage:
    search_more = (
        InlineButton(translate(MessageKey.SEARCH_MORE, locale), "source:ai_search"),
    )

    if result.state is SourceTaskState.FAILED_SAFE:
        return OutgoingMessage(
            text=translate(MessageKey.SCOUT_FAILED, locale),
            keyboard=(search_more,),
        )
    if not candidates:
        return OutgoingMessage(
            text=translate(MessageKey.SCOUT_EMPTY, locale),
            keyboard=(search_more,),
        )

    header = translate(MessageKey.SCOUT_RESULTS, locale).format(
        discovered=result.discovered_count,
        candidates=result.candidate_count,
    )
    lines = [header]
    keyboard: list[tuple[InlineButton, ...]] = []
    for index, candidate in enumerate(candidates, start=1):
        title = candidate.title or candidate.caption or candidate.source_id
        lines.extend(
            (
                "",
                f"{index}. {_truncate(title, 180)}",
                candidate.source_url,
                _engagement_line(candidate),
            )
        )
        buttons = [
            InlineButton(translate(MessageKey.VIEW, locale), url=candidate.source_url)
        ]
        if candidate.id is not None:
            buttons.append(
                InlineButton(
                    translate(MessageKey.SELECT, locale),
                    f"candidate:select:{candidate.id}",
                )
            )
        keyboard.append(tuple(buttons))

    keyboard.append(search_more)
    return OutgoingMessage(text="\n".join(lines), keyboard=tuple(keyboard))


def build_upload_prompt(locale: UiLocale) -> OutgoingMessage:
    return OutgoingMessage(text=translate(MessageKey.UPLOAD_PROMPT, locale))


def build_feed_prompt(locale: UiLocale) -> OutgoingMessage:
    return OutgoingMessage(text=translate(MessageKey.FEED_PROMPT, locale))


def _engagement_line(candidate: CandidateContent) -> str:
    likes = candidate.engagement.get("like_count", 0)
    reposts = candidate.engagement.get("retweet_count", 0)
    replies = candidate.engagement.get("reply_count", 0)
    return f"❤️ {likes} · 🔁 {reposts} · 💬 {replies}"


def _truncate(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"
