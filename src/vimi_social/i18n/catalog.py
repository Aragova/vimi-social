from enum import StrEnum

from vimi_social.domain.international import UiLocale


class MessageKey(StrEnum):
    WELCOME = "welcome"
    NEW_TASK = "new_task"
    SOURCES = "sources"
    DESTINATIONS = "destinations"
    AUTOMATIONS = "automations"
    PUBLICATIONS = "publications"
    ANALYTICS = "analytics"
    PLAN = "plan"
    SETTINGS = "settings"
    CHOOSE_SOURCE = "choose_source"
    SOURCE_AI = "source_ai"
    SOURCE_UPLOAD = "source_upload"
    SOURCE_FEED = "source_feed"
    AI_SEARCH_PROMPT = "ai_search_prompt"
    AI_SEARCH_STARTED = "ai_search_started"
    SCOUT_RESULTS = "scout_results"
    SCOUT_EMPTY = "scout_empty"
    SCOUT_FAILED = "scout_failed"
    SCOUT_QUOTA_EXCEEDED = "scout_quota_exceeded"
    VIEW = "view"
    SELECT = "select"
    SEARCH_MORE = "search_more"
    CANDIDATE_SELECTED = "candidate_selected"
    CANDIDATE_NOT_AVAILABLE = "candidate_not_available"
    UPLOAD_PROMPT = "upload_prompt"
    FEED_PROMPT = "feed_prompt"


_CATALOG: dict[UiLocale, dict[MessageKey, str]] = {
    UiLocale.RU: {
        MessageKey.WELCOME: (
            "👋 Добро пожаловать в ViMi Social\n\n"
            "Задайте цель — ViMi поможет найти, подготовить и распределить контент."
        ),
        MessageKey.NEW_TASK: "🚀 Новая задача",
        MessageKey.SOURCES: "📚 Источники",
        MessageKey.DESTINATIONS: "🌐 Площадки",
        MessageKey.AUTOMATIONS: "📅 Автоматизации",
        MessageKey.PUBLICATIONS: "🗂 Публикации",
        MessageKey.ANALYTICS: "📊 Аналитика",
        MessageKey.PLAN: "💎 Тариф",
        MessageKey.SETTINGS: "⚙️ Настройки",
        MessageKey.CHOOSE_SOURCE: "Выберите источник контента:",
        MessageKey.SOURCE_AI: "🤖 AI-поиск",
        MessageKey.SOURCE_UPLOAD: "📤 Добавить видео",
        MessageKey.SOURCE_FEED: "📚 Канал / группа / тема",
        MessageKey.AI_SEARCH_PROMPT: (
            "🤖 AI-поиск выбран.\n\n"
            "Опишите, какой контент нужно найти, тему и при желании источник."
        ),
        MessageKey.AI_SEARCH_STARTED: (
            "🔎 Задача сохранена. Scout начал поиск по подключённым источникам."
        ),
        MessageKey.SCOUT_RESULTS: (  # noqa: RUF001 - intentional Russian localization
            "🔎 Найдено: {discovered}\nПосле нормализации: {candidates}"
        ),
        MessageKey.SCOUT_EMPTY: (
            "🔎 По этому запросу подходящих видео пока не найдено. "
            "Можно уточнить запрос и поискать ещё."
        ),
        MessageKey.SCOUT_FAILED: (
            "⚠️ Scout не смог завершить поиск безопасно. "
            "Задача остановлена без повторной отправки внешних операций."
        ),
        MessageKey.SCOUT_QUOTA_EXCEEDED: (
            "⚠️ Лимит AI-поиска для этого workspace исчерпан или ещё не настроен."
        ),
        MessageKey.VIEW: "👀 Посмотреть",
        MessageKey.SELECT: "✅ Выбрать",
        MessageKey.SEARCH_MORE: "🔄 Искать ещё",
        MessageKey.CANDIDATE_SELECTED: (
            "✅ Кандидат выбран. Следующий этап — безопасное получение и MediaProbe."
        ),
        MessageKey.CANDIDATE_NOT_AVAILABLE: (
            "⚠️ Этот кандидат недоступен в текущем workspace или уже изменён."
        ),
        MessageKey.UPLOAD_PROMPT: (
            "📤 Ручной источник выбран.\n\n"
            "Отправьте или перешлите материал в этот чат."
        ),
        MessageKey.FEED_PROMPT: (
            "📚 Source Feed выбран.\n\n"
            "Дальше здесь будет подключение канала, группы или конкретной темы как очереди."
        ),
    },
    UiLocale.EN: {
        MessageKey.WELCOME: (
            "👋 Welcome to ViMi Social\n\n"
            "Set the goal — ViMi helps discover, prepare, and distribute content."
        ),
        MessageKey.NEW_TASK: "🚀 New task",
        MessageKey.SOURCES: "📚 Sources",
        MessageKey.DESTINATIONS: "🌐 Destinations",
        MessageKey.AUTOMATIONS: "📅 Automations",
        MessageKey.PUBLICATIONS: "🗂 Publications",
        MessageKey.ANALYTICS: "📊 Analytics",
        MessageKey.PLAN: "💎 Plan",
        MessageKey.SETTINGS: "⚙️ Settings",
        MessageKey.CHOOSE_SOURCE: "Choose a content source:",
        MessageKey.SOURCE_AI: "🤖 AI Search",
        MessageKey.SOURCE_UPLOAD: "📤 Add video",
        MessageKey.SOURCE_FEED: "📚 Channel / group / topic",
        MessageKey.AI_SEARCH_PROMPT: (
            "🤖 AI Search selected.\n\n"
            "Describe what content to find, the topic, and an optional source."
        ),
        MessageKey.AI_SEARCH_STARTED: (
            "🔎 Task saved. Scout started searching the connected sources."
        ),
        MessageKey.SCOUT_RESULTS: "🔎 Found: {discovered}\nNormalized: {candidates}",
        MessageKey.SCOUT_EMPTY: (
            "🔎 No suitable videos were found for this query yet. "
            "Refine the request and search again."
        ),
        MessageKey.SCOUT_FAILED: (
            "⚠️ Scout could not complete the search safely. "
            "The task stopped without blindly repeating external operations."
        ),
        MessageKey.SCOUT_QUOTA_EXCEEDED: (
            "⚠️ The AI Search limit for this workspace is exhausted or not configured yet."
        ),
        MessageKey.VIEW: "👀 View",
        MessageKey.SELECT: "✅ Select",
        MessageKey.SEARCH_MORE: "🔄 Search more",
        MessageKey.CANDIDATE_SELECTED: (
            "✅ Candidate selected. The next slice will acquire it safely and run MediaProbe."
        ),
        MessageKey.CANDIDATE_NOT_AVAILABLE: (
            "⚠️ This candidate is not available in the current workspace or has changed."
        ),
        MessageKey.UPLOAD_PROMPT: (
            "📤 Manual source selected.\n\n"
            "Send or forward the material to this chat."
        ),
        MessageKey.FEED_PROMPT: (
            "📚 Source Feed selected.\n\n"
            "This flow will connect a channel, group, or topic as a persistent queue."
        ),
    },
}


def translate(key: MessageKey, locale: UiLocale) -> str:
    return _CATALOG[locale][key]
