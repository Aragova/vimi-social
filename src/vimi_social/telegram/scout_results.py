from math import ceil
from uuid import UUID

from vimi_social.domain.international import UiLocale
from vimi_social.domain.source import CandidateContent, ScoutRunResult, SourceTaskState
from vimi_social.i18n.catalog import MessageKey, translate
from vimi_social.telegram.menus import InlineButton, OutgoingMessage

_RESULT_SUMMARY_LIMIT = 80
_RESULT_PAGE_SIZE = 10


def build_scout_results(
    locale: UiLocale,
    result: ScoutRunResult,
    candidates: tuple[CandidateContent, ...],
    *,
    task_id: UUID | None = None,
    page: int = 0,
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
    if task_id is None:
        task_id = UUID(int=0)

    return build_scout_result_page(
        locale,
        candidates,
        task_id=task_id,
        page=page,
    )


def build_scout_result_page(
    locale: UiLocale,
    candidates: tuple[CandidateContent, ...],
    *,
    task_id: UUID,
    page: int,
) -> OutgoingMessage:
    if not candidates:
        return OutgoingMessage(
            text=translate(MessageKey.SCOUT_EMPTY, locale),
            keyboard=(
                (InlineButton(translate(MessageKey.SEARCH_MORE, locale), "source:ai_search"),),
            ),
        )

    total = len(candidates)
    page_count = max(1, ceil(total / _RESULT_PAGE_SIZE))
    current_page = max(0, min(page, page_count - 1))
    start = current_page * _RESULT_PAGE_SIZE
    end = min(total, start + _RESULT_PAGE_SIZE)

    header = translate(MessageKey.SCOUT_RESULTS, locale).format(
        discovered=total,
        candidates=total,
    ).splitlines()[0]
    page_label = (
        f"Страница {current_page + 1}/{page_count}"
        if locale is UiLocale.RU
        else f"Page {current_page + 1}/{page_count}"
    )
    lines = [header, page_label] if page_count > 1 else [header]
    keyboard: list[tuple[InlineButton, ...]] = []

    for index in range(start, end):
        candidate = candidates[index]
        display_index = index + 1
        title = candidate.title or candidate.caption or candidate.source_id
        lines.append(f"{display_index}. {_truncate(title, _RESULT_SUMMARY_LIMIT)}")

        buttons = [
            InlineButton(
                f"{translate(MessageKey.VIEW, locale)} {display_index}",
                url=candidate.source_url,
            )
        ]
        if candidate.id is not None:
            buttons.append(
                InlineButton(
                    f"{translate(MessageKey.SELECT, locale)} {display_index}",
                    f"candidate:select:{candidate.id}",
                )
            )
        keyboard.append(tuple(buttons))

    navigation: list[InlineButton] = []
    if current_page > 0:
        navigation.append(
            InlineButton("⬅️", f"scout:page:{task_id}:{current_page - 1}")
        )
    if current_page + 1 < page_count:
        navigation.append(
            InlineButton("➡️", f"scout:page:{task_id}:{current_page + 1}")
        )
    if navigation:
        keyboard.append(tuple(navigation))

    keyboard.append(
        (InlineButton(translate(MessageKey.SEARCH_MORE, locale), "source:ai_search"),)
    )
    return OutgoingMessage(text="\n".join(lines), keyboard=tuple(keyboard))


def _truncate(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"
