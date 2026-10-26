import json

import httpx
import pytest

from vimi_social.source.query_planner import (
    FallbackEnglishIntentTranslator,
    MultilingualQueryPlanner,
    OpenAIEnglishIntentTranslator,
    normalize_search_intent,
)


class FakeTranslator:
    def __init__(self, translation: str | None) -> None:
        self.translation = translation
        self.calls: list[str] = []

    async def translate_to_english(self, intent: str) -> str | None:
        self.calls.append(intent)
        return self.translation


class MappingTranslator:
    def __init__(self, translations: dict[str, str | None]) -> None:
        self.translations = translations
        self.calls: list[str] = []

    async def translate_to_english(self, intent: str) -> str | None:
        self.calls.append(intent)
        return self.translations.get(intent)


def test_normalize_search_intent_removes_russian_command_wrapper() -> None:
    assert normalize_search_intent("Найди видео про ночной Бангкок") == "ночной Бангкок"


def test_normalize_search_intent_removes_english_command_wrapper() -> None:
    assert normalize_search_intent("Find videos about Bangkok at night") == "Bangkok at night"


def test_normalize_search_intent_removes_translated_video_of_wrapper() -> None:
    assert (
        normalize_search_intent("Find a video of the night Bangkok")
        == "the night Bangkok"
    )


@pytest.mark.asyncio
async def test_multilingual_planner_keeps_ru_and_adds_en_variant() -> None:
    translator = FakeTranslator("Bangkok night")
    planner = MultilingualQueryPlanner(translator)

    plan = await planner.plan(
        "Найди видео про ночной Бангкок",
        ("ru", "en"),
    )

    assert translator.calls == ["Найди видео про ночной Бангкок"]
    assert plan.query_variants == ("ночной Бангкок", "Bangkok night")
    assert plan.relaxation_queries == ("ночной Бангкок", "ночной")


@pytest.mark.asyncio
async def test_relaxed_queries_strip_unbalanced_search_syntax() -> None:
    planner = MultilingualQueryPlanner()
    plan = await planner.plan('Find videos about "night market" Bangkok', ("en",))

    assert plan.relaxation_queries == (
        '"night market" Bangkok',
        "night market",
        "night",
    )


@pytest.mark.asyncio
async def test_multilingual_planner_normalizes_local_full_intent_translation() -> None:
    translator = FakeTranslator("Find a video of the night Bangkok")
    planner = MultilingualQueryPlanner(translator)

    plan = await planner.plan(
        "Найди видео про ночной Бангкок",
        ("ru", "en"),
    )

    assert plan.query_variants == ("ночной Бангкок", "the night Bangkok")


@pytest.mark.asyncio
async def test_progressive_rounds_try_ru_then_bilingual_before_dropping_last_keyword() -> None:
    intent = "Найди видео про Бангкок ночной рынок красивый"
    translator = MappingTranslator(
        {
            intent: "Bangkok night market beautiful",
            "Найди видео про Бангкок ночной рынок": "Bangkok night market",
            "Найди видео про Бангкок ночной": "Bangkok night",
            "Найди видео про Бангкок": "Bangkok",
        }
    )
    planner = MultilingualQueryPlanner(translator)
    plan = await planner.plan(intent, ("ru", "en"))

    rounds = [
        round_item
        async for round_item in planner.search_rounds(plan, intent, ("ru", "en"))
    ]

    assert [item.query_variants for item in rounds] == [
        ("Бангкок ночной рынок красивый",),
        ("Бангкок ночной рынок красивый", "Bangkok night market beautiful"),
        ("Бангкок ночной рынок",),
        ("Бангкок ночной рынок", "Bangkok night market"),
        ("Бангкок ночной",),
        ("Бангкок ночной", "Bangkok night"),
        ("Бангкок",),
        ("Бангкок", "Bangkok"),
    ]
    assert [item.preferred_languages for item in rounds] == [
        ("ru",),
        ("ru", "en"),
        ("ru",),
        ("ru", "en"),
        ("ru",),
        ("ru", "en"),
        ("ru",),
        ("ru", "en"),
    ]


@pytest.mark.asyncio
async def test_shorter_translations_are_lazy_until_relaxation_is_reached() -> None:
    intent = "Найди видео про Бангкок ночной рынок"
    translator = MappingTranslator(
        {
            intent: "Bangkok night market",
            "Найди видео про Бангкок ночной": "Bangkok night",
            "Найди видео про Бангкок": "Bangkok",
        }
    )
    planner = MultilingualQueryPlanner(translator)
    plan = await planner.plan(intent, ("ru", "en"))
    rounds = planner.search_rounds(plan, intent, ("ru", "en"))

    first = await anext(rounds)
    second = await anext(rounds)
    third = await anext(rounds)

    assert first.query_variants == ("Бангкок ночной рынок",)
    assert second.query_variants == ("Бангкок ночной рынок", "Bangkok night market")
    assert third.query_variants == ("Бангкок ночной",)
    assert translator.calls == [intent]

    fourth = await anext(rounds)
    assert fourth.query_variants == ("Бангкок ночной", "Bangkok night")
    assert translator.calls == [intent, "Найди видео про Бангкок ночной"]


@pytest.mark.asyncio
async def test_relaxed_translation_failure_disables_later_translation_attempts() -> None:
    intent = "Найди видео про Бангкок ночной рынок"
    translator = MappingTranslator(
        {
            intent: "Bangkok night market",
            "Найди видео про Бангкок ночной": None,
            "Найди видео про Бангкок": "Bangkok",
        }
    )
    planner = MultilingualQueryPlanner(translator)
    plan = await planner.plan(intent, ("ru", "en"))

    rounds = [
        round_item
        async for round_item in planner.search_rounds(plan, intent, ("ru", "en"))
    ]

    assert [item.query_variants for item in rounds] == [
        ("Бангкок ночной рынок",),
        ("Бангкок ночной рынок", "Bangkok night market"),
        ("Бангкок ночной",),
        ("Бангкок",),
    ]
    assert translator.calls == [
        intent,
        "Найди видео про Бангкок ночной",
    ]


@pytest.mark.asyncio
async def test_multilingual_planner_falls_back_when_translation_unavailable() -> None:
    translator = FakeTranslator(None)
    planner = MultilingualQueryPlanner(translator)

    plan = await planner.plan("Найди видео про ночной Бангкок", ("ru", "en"))

    assert plan.query_variants == ("ночной Бангкок",)


@pytest.mark.asyncio
async def test_translation_chain_uses_second_provider_only_when_first_fails() -> None:
    local = FakeTranslator(None)
    fallback = FakeTranslator("Bangkok at night")
    translator = FallbackEnglishIntentTranslator((local, fallback))

    result = await translator.translate_to_english("ночной Бангкок")

    assert result == "Bangkok at night"
    assert local.calls == ["ночной Бангкок"]
    assert fallback.calls == ["ночной Бангкок"]


@pytest.mark.asyncio
async def test_translation_chain_stops_after_local_success() -> None:
    local = FakeTranslator("Bangkok at night")
    fallback = FakeTranslator("should not be charged")
    translator = FallbackEnglishIntentTranslator((local, fallback))

    result = await translator.translate_to_english("ночной Бангкок")

    assert result == "Bangkok at night"
    assert fallback.calls == []


@pytest.mark.asyncio
async def test_planner_does_not_translate_already_english_intent() -> None:
    translator = FakeTranslator("should not be used")
    planner = MultilingualQueryPlanner(translator)

    plan = await planner.plan("Find videos about Bangkok at night", ("en",))

    assert translator.calls == []
    assert plan.query_variants == ("Bangkok at night",)


@pytest.mark.asyncio
async def test_openai_translator_uses_responses_api_and_extracts_output_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/responses"
        assert request.headers["Authorization"] == "Bearer translation-secret"
        body = json.loads(request.content)
        assert body["model"] == "gpt-6-luna"
        assert body["store"] is False
        assert body["input"] == "ночной Бангкок"
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "Bangkok night",
                            }
                        ],
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    translator = OpenAIEnglishIntentTranslator(
        "translation-secret",
        client=client,
    )

    result = await translator.translate_to_english("ночной Бангкок")

    assert result == "Bangkok night"
    await client.aclose()


@pytest.mark.asyncio
async def test_openai_translator_fails_open_without_breaking_scout() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(503))
    )
    translator = OpenAIEnglishIntentTranslator(
        "translation-secret",
        client=client,
    )

    assert await translator.translate_to_english("ночной Бангкок") is None
    await client.aclose()
