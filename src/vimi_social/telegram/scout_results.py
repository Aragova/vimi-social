from vimi_social.domain.international import UiLocale
from vimi_social.domain.source import CandidateContent, ScoutRunResult, SourceTaskState
from vimi_social.i18n.catalog import MessageKey, translate
from vimi_social.telegram.menus import InlineButton, OutgoingMessage


_RESULT_SUMMARY_LIMIT = 80


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
    if result.state is SourceTaskState.UNKNOWN:
        return OutgoingMessage(
            text=translate(MessageKey.SCOUT_UNKNOWN, locale),
            keyboard=(search_more,),
        )
    if not candidates:
        return OutgoingMessage(
            text=translate(MessageKey.SCOUT_EMPTY, locale),
            keyboard=(search_more,),
        )

    # Keep the Telegram result card intentionally compact. The source URL remains
    # available through the View button instead of being duplicated in message text,
    # which also avoids noisy automatic link previews.
    header = translate(MessageKey.SCOUT_RESULTS, locale).format(
        discovered=len(candidates),
        candidates=len(candidates),
    ).splitlines()[0]
    lines = [header]
    keyboard: list[tuple[InlineButton, ...]] = []

    for index, candidate in enumerate(candidates, start=1):
        title = candidate.title or candidate.caption or candidate.source_id
        lines.append(f"{index}. {_truncate(title, _RESULT_SUMMARY_LIMIT)}")

        buttons = [
            InlineButton(
                f"{translate(MessageKey.VIEW, locale)} {index}",
                url=candidate.source_url,
            )
        ]
        if candidate.id is not None:
            buttons.append(
                InlineButton(
                    f"{translate(MessageKey.SELECT, locale)} {index}",
                    f"candidate:select:{candidate.id}",
                )
            )
        keyboard.append(tuple(buttons))

    keyboard.append(search_more)
    return OutgoingMessage(text="\n".join(lines), keyboard=tuple(keyboard))


def _truncate(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"
