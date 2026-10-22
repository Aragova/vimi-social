from dataclasses import dataclass
from uuid import UUID

from vimi_social.domain.analysis import (
    MediaAnalysisResult,
    PolicyDecision,
    RenderStrategy,
    SceneAnalysisState,
)
from vimi_social.domain.international import UiLocale
from vimi_social.domain.media import (
    BaseAdultClassification,
    MediaPreparationResult,
    MediaPreparationState,
)
from vimi_social.domain.publication import (
    PublicationPreviewResult,
    PublicationPreviewState,
    PublicationResult,
    PublicationState,
    RenderResult,
    VariantArtifactState,
)
from vimi_social.domain.source import CandidateContent, ScoutRunResult, SourceTaskState
from vimi_social.i18n.catalog import MessageKey, translate
from vimi_social.i18n.publication import PublicationMessageKey, translate_publication


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


def build_ai_search_intent_too_long(locale: UiLocale) -> OutgoingMessage:
    return OutgoingMessage(text=translate(MessageKey.AI_SEARCH_INTENT_TOO_LONG, locale))


def build_scout_quota_exceeded(locale: UiLocale) -> OutgoingMessage:
    return OutgoingMessage(text=translate(MessageKey.SCOUT_QUOTA_EXCEEDED, locale))


def build_candidate_selected(locale: UiLocale, *, selected: bool) -> OutgoingMessage:
    key = MessageKey.CANDIDATE_SELECTED if selected else MessageKey.CANDIDATE_NOT_AVAILABLE
    return OutgoingMessage(text=translate(key, locale))


def build_media_rights_prompt(locale: UiLocale, preparation_id: UUID) -> OutgoingMessage:
    return OutgoingMessage(
        text=translate(MessageKey.MEDIA_RIGHTS_PROMPT, locale),
        keyboard=(
            (
                InlineButton(
                    translate(MessageKey.MEDIA_RIGHTS_CONFIRM, locale),
                    f"media:rights:yes:{preparation_id}",
                ),
            ),
            (
                InlineButton(
                    translate(MessageKey.MEDIA_RIGHTS_DECLINE, locale),
                    f"media:rights:no:{preparation_id}",
                ),
            ),
        ),
    )


def build_media_rights_declined(locale: UiLocale) -> OutgoingMessage:
    return OutgoingMessage(text=translate(MessageKey.MEDIA_RIGHTS_DECLINED, locale))


def build_media_preparation_started(locale: UiLocale) -> OutgoingMessage:
    return OutgoingMessage(text=translate(MessageKey.MEDIA_PREPARATION_STARTED, locale))


def build_media_preparation_quota_exceeded(locale: UiLocale) -> OutgoingMessage:
    return OutgoingMessage(text=translate(MessageKey.MEDIA_PREPARATION_QUOTA_EXCEEDED, locale))


def build_media_preparation_result(
    locale: UiLocale,
    result: MediaPreparationResult,
    analysis: MediaAnalysisResult | None = None,
    render: RenderResult | None = None,
    preview: PublicationPreviewResult | None = None,
) -> OutgoingMessage:
    if result.state is MediaPreparationState.BLOCKED:
        return OutgoingMessage(text=translate(MessageKey.MEDIA_PREPARATION_BLOCKED, locale))
    if result.state is not MediaPreparationState.READY:
        return OutgoingMessage(text=translate(MessageKey.MEDIA_PREPARATION_FAILED, locale))

    lines = [translate(MessageKey.MEDIA_PREPARATION_READY, locale)]
    if result.duration_ms is not None:
        lines.append(f"⏱ {_duration_label(result.duration_ms)}")
    if result.width is not None and result.height is not None:
        lines.append(f"📐 {result.width}x{result.height}")
    if result.size_bytes is not None:
        lines.append(f"💾 {_size_label(result.size_bytes)}")
    lines.append(f"🔞 {_adult_label(locale, result.adult_classification)}")
    if result.sha256 is not None:
        lines.append(f"🔐 SHA-256: {result.sha256[:12]}…")

    if analysis is not None:
        if analysis.state is SceneAnalysisState.FAILED_SAFE:
            lines.append(translate(MessageKey.MEDIA_ANALYSIS_FAILED, locale))
        elif analysis.state is SceneAnalysisState.READY:
            lines.append(
                translate(MessageKey.MEDIA_SCENES_FOUND, locale).format(
                    count=analysis.scene_count
                )
            )
            if analysis.top_scene_start_ms is not None and analysis.top_scene_end_ms is not None:
                lines.append(
                    translate(MessageKey.MEDIA_TOP_SCENE, locale).format(
                        start=_duration_label(analysis.top_scene_start_ms),
                        end=_duration_label(analysis.top_scene_end_ms),
                    )
                )
            if analysis.destination is not None and analysis.policy_decision is not None:
                lines.append(
                    translate(MessageKey.MEDIA_POLICY_SUMMARY, locale).format(
                        destination=analysis.destination.upper(),
                        decision=_policy_label(locale, analysis.policy_decision),
                    )
                )
            if analysis.render_strategy is not None and analysis.planned_duration_ms is not None:
                lines.append(
                    translate(MessageKey.MEDIA_RENDER_SUMMARY, locale).format(
                        strategy=_render_label(locale, analysis.render_strategy),
                        duration=_duration_label(analysis.planned_duration_ms),
                    )
                )

    keyboard: tuple[tuple[InlineButton, ...], ...] = ()
    if render is not None and render.state is VariantArtifactState.FAILED_SAFE:
        lines.append(
            translate_publication(PublicationMessageKey.RENDER_FAILED, locale)
        )
    if preview is not None:
        preview_line = _publication_preview_line(locale, preview)
        if preview_line is not None:
            lines.append(preview_line)
        if (
            preview.state is PublicationPreviewState.AWAITING_APPROVAL
            and preview.publication_id is not None
        ):
            keyboard = (
                (
                    InlineButton(
                        translate_publication(PublicationMessageKey.PUBLISH_X, locale),
                        f"publication:approve:{preview.publication_id}",
                    ),
                ),
            )
    return OutgoingMessage(text="\n".join(lines), keyboard=keyboard)


def build_publication_started(locale: UiLocale) -> OutgoingMessage:
    return OutgoingMessage(
        text=translate_publication(PublicationMessageKey.STARTED, locale)
    )


def build_publication_quota_exceeded(locale: UiLocale) -> OutgoingMessage:
    return OutgoingMessage(
        text=translate_publication(PublicationMessageKey.QUOTA_EXCEEDED, locale)
    )


def build_publication_not_available(locale: UiLocale) -> OutgoingMessage:
    return OutgoingMessage(
        text=translate_publication(PublicationMessageKey.NOT_AVAILABLE, locale)
    )


def build_publication_result(locale: UiLocale, result: PublicationResult) -> OutgoingMessage:
    if result.state is PublicationState.CONFIRMED:
        key = PublicationMessageKey.CONFIRMED
    elif result.state is PublicationState.UNKNOWN:
        key = PublicationMessageKey.UNKNOWN
    else:
        key = PublicationMessageKey.FAILED
    return OutgoingMessage(text=translate_publication(key, locale))


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


def _publication_preview_line(
    locale: UiLocale,
    preview: PublicationPreviewResult,
) -> str | None:
    keys = {
        PublicationPreviewState.AWAITING_APPROVAL: PublicationMessageKey.PREVIEW_READY,
        PublicationPreviewState.REVIEW_REQUIRED: PublicationMessageKey.REVIEW_REQUIRED,
        PublicationPreviewState.BLOCKED: PublicationMessageKey.BLOCKED,
        PublicationPreviewState.NO_DESTINATION: PublicationMessageKey.NO_DESTINATION,
        PublicationPreviewState.ACCOUNT_SELECTION_REQUIRED: (
            PublicationMessageKey.ACCOUNT_SELECTION_REQUIRED
        ),
        PublicationPreviewState.RENDER_FAILED: PublicationMessageKey.RENDER_FAILED,
    }
    key = keys.get(preview.state)
    return translate_publication(key, locale) if key is not None else None


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


def _duration_label(duration_ms: int) -> str:
    total_seconds = max(0, round(duration_ms / 1000))
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}" if minutes else f"{seconds}s"


def _size_label(size_bytes: int) -> str:
    mebibytes = size_bytes / (1024 * 1024)
    return f"{mebibytes:.1f} MiB"


def _adult_label(locale: UiLocale, classification: BaseAdultClassification) -> str:
    keys = {
        BaseAdultClassification.UNKNOWN: MessageKey.MEDIA_ADULT_UNKNOWN,
        BaseAdultClassification.NO_ADULT_SIGNAL_DETECTED: MessageKey.MEDIA_ADULT_NO_SIGNAL,
        BaseAdultClassification.POSSIBLY_SENSITIVE: MessageKey.MEDIA_ADULT_POSSIBLY_SENSITIVE,
        BaseAdultClassification.ADULT_EXPLICIT: MessageKey.MEDIA_ADULT_EXPLICIT,
    }
    return translate(keys[classification], locale)


def _policy_label(locale: UiLocale, decision: PolicyDecision) -> str:
    keys = {
        PolicyDecision.DIRECT_ALLOWED: MessageKey.POLICY_DIRECT_ALLOWED,
        PolicyDecision.ADAPTATION_REQUIRED: MessageKey.POLICY_ADAPTATION_REQUIRED,
        PolicyDecision.MANUAL_REVIEW_REQUIRED: MessageKey.POLICY_MANUAL_REVIEW_REQUIRED,
        PolicyDecision.BLOCKED: MessageKey.POLICY_BLOCKED,
    }
    return translate(keys[decision], locale)


def _render_label(locale: UiLocale, strategy: RenderStrategy) -> str:
    keys = {
        RenderStrategy.PASSTHROUGH: MessageKey.RENDER_PASSTHROUGH,
        RenderStrategy.CLIP_SEQUENCE: MessageKey.RENDER_CLIP_SEQUENCE,
    }
    return translate(keys[strategy], locale)
