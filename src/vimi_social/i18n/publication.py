from enum import StrEnum

from vimi_social.domain.international import UiLocale


class PublicationMessageKey(StrEnum):
    PREVIEW_READY = "preview_ready"
    PREVIEW_TOO_LARGE = "preview_too_large"
    PUBLISH_X = "publish_x"
    REVIEW_REQUIRED = "review_required"
    BLOCKED = "blocked"
    NO_DESTINATION = "no_destination"
    ACCOUNT_SELECTION_REQUIRED = "account_selection_required"
    RENDER_FAILED = "render_failed"
    STARTED = "started"
    QUOTA_EXCEEDED = "quota_exceeded"
    NOT_AVAILABLE = "not_available"
    CONFIRMED = "confirmed"
    UNKNOWN = "unknown"
    FAILED = "failed"


_CATALOG: dict[UiLocale, dict[PublicationMessageKey, str]] = {
    UiLocale.RU: {
        PublicationMessageKey.PREVIEW_READY: (
            "🎞 Вариант для X готов. Проверьте видео и подтвердите публикацию."
        ),
        PublicationMessageKey.PREVIEW_TOO_LARGE: (
            "📦 Видео больше безопасного лимита Telegram для preview, поэтому файл здесь "
            "не прикреплён. Кнопка подтверждения публикации остаётся доступной."
        ),
        PublicationMessageKey.PUBLISH_X: "🚀 Опубликовать в X",
        PublicationMessageKey.REVIEW_REQUIRED: (
            "🛡 Публикация не запущена: контент требует ручной проверки политики/18+."
        ),
        PublicationMessageKey.BLOCKED: (
            "🚫 Для X этот вариант заблокирован политикой и публиковаться не будет."
        ),
        PublicationMessageKey.NO_DESTINATION: (
            "⚠️ Нет подключённого активного аккаунта X. Сначала подключите площадку."
        ),
        PublicationMessageKey.ACCOUNT_SELECTION_REQUIRED: (
            "⚠️ Подключено несколько аккаунтов X. Перед публикацией нужно выбрать аккаунт."
        ),
        PublicationMessageKey.RENDER_FAILED: (
            "⚠️ Вариант видео не удалось подготовить безопасным образом."
        ),
        PublicationMessageKey.STARTED: (
            "🚀 Публикация подтверждена. ViMi отправляет видео в X."
        ),
        PublicationMessageKey.QUOTA_EXCEEDED: (
            "⚠️ Лимит публикаций для этого workspace исчерпан."
        ),
        PublicationMessageKey.NOT_AVAILABLE: (
            "⚠️ Эта публикация недоступна, уже изменена или не разрешена политикой."
        ),
        PublicationMessageKey.CONFIRMED: "✅ Видео опубликовано в X.",
        PublicationMessageKey.UNKNOWN: (
            "⚠️ Результат публикации неоднозначен. ViMi не будет отправлять пост повторно "
            "вслепую и оставляет операцию на сверке."
        ),
        PublicationMessageKey.FAILED: "⚠️ Публикация в X безопасно остановлена.",
    },
    UiLocale.EN: {
        PublicationMessageKey.PREVIEW_READY: (
            "🎞 The X variant is ready. Review the video and approve publication."
        ),
        PublicationMessageKey.PREVIEW_TOO_LARGE: (
            "📦 The video is above the safe Telegram preview limit, so the file is not "
            "attached here. The publication approval button remains available."
        ),
        PublicationMessageKey.PUBLISH_X: "🚀 Publish to X",
        PublicationMessageKey.REVIEW_REQUIRED: (
            "🛡 Publication was not started: the content requires manual policy/adult review."
        ),
        PublicationMessageKey.BLOCKED: (
            "🚫 This X variant is policy-blocked and will not be published."
        ),
        PublicationMessageKey.NO_DESTINATION: (
            "⚠️ No active X account is connected. Connect a destination first."
        ),
        PublicationMessageKey.ACCOUNT_SELECTION_REQUIRED: (
            "⚠️ Multiple X accounts are connected. Select an account before publishing."
        ),
        PublicationMessageKey.RENDER_FAILED: (
            "⚠️ ViMi could not prepare the video variant safely."
        ),
        PublicationMessageKey.STARTED: (
            "🚀 Publication approved. ViMi is sending the video to X."
        ),
        PublicationMessageKey.QUOTA_EXCEEDED: (
            "⚠️ The publication limit for this workspace is exhausted."
        ),
        PublicationMessageKey.NOT_AVAILABLE: (
            "⚠️ This publication is unavailable, changed, or not policy-eligible."
        ),
        PublicationMessageKey.CONFIRMED: "✅ Video published to X.",
        PublicationMessageKey.UNKNOWN: (
            "⚠️ The publication outcome is ambiguous. ViMi will not blindly send the post "
            "again and keeps the operation in reconciliation."
        ),
        PublicationMessageKey.FAILED: "⚠️ Publication to X stopped safely.",
    },
}


def translate_publication(key: PublicationMessageKey, locale: UiLocale) -> str:
    return _CATALOG[locale][key]
