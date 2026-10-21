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
