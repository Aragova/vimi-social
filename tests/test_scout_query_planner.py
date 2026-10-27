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
async def test_multilingual_planner_keeps_full_ru_and_adds_full_en_variant() -> None:
    translator = FakeTranslator("Bangkok night market beautiful")
    planner = MultilingualQueryPlanner(translator)
    intent = "Найди видео про Бангкок ночной рынок красивый"

    plan = await planner.plan(intent, ("ru", "en"))

    assert translator.calls == [intent]
    assert plan.normalized_intent == "Бангкок ночной рынок красивый"
    assert plan.query_variants == (
        "Бангкок ночной рынок красивый",
        "Bangkok night market beautiful",
    )
    assert plan.retrieval_queries == ("Бангкок ночной рынок красивый",)


@pytest.mark.asyncio
async def test_planner_preserves_quotes_in_ranking_target() -> None:
    planner = MultilingualQueryPlanner()
    plan = await planner.plan('Find videos about "night market" Bangkok', ("en",))

    assert plan.normalized_intent == '"night market" Bangkok'
    assert plan.retrieval_queries == ('"night market" Bangkok',)


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
async def test_ru_en_rounds_use_provider_or_recall_but_keep_full_ranking_target() -> None:
    intent = "Найди видео про Бангкок ночной рынок красивый"
    translator = FakeTranslator("Bangkok night market beautiful")
    planner = MultilingualQueryPlanner(translator)
    plan = await planner.plan(intent, ("ru", "en"))

    rounds = [
        round_item
        async for round_item in planner.search_rounds(plan, intent, ("ru", "en"))
    ]

    assert plan.query_variants == (
        "Бангкок ночной рынок красивый",
        "Bangkok night market beautiful",
    )
    assert [item.query_variants for item in rounds] == [
        ("Бангкок", "ночной", "рынок", "красивый"),
        ("Bangkok", "night", "market", "beautiful"),
        ("Bangkok", "night", "market", "beautiful"),
        ("market",),
    ]
    assert [item.preferred_languages for item in rounds] == [
        ("ru",),
        ("en",),
        (),
        (),
    ]
    assert [item.relaxation_level for item in rounds] == [0, 1, 2, 3]
    assert [item.specificity for item in rounds] == [0.25, 0.25, 0.25, 0.25]
    assert [item.strategy for item in rounds] == [
        "provider_or_primary",
        "provider_or_translated",
        "provider_or_language_broadening",
        "provider_anchor_fallback",
    ]
    assert translator.calls == [intent]


@pytest.mark.asyncio
async def test_sparse_staging_query_becomes_word_level_or_recall() -> None:
    intent = "Гей порно твинк молодые"
    translator = FakeTranslator("Gay porn twink young")
    planner = MultilingualQueryPlanner(translator)
    plan = await planner.plan(intent, ("ru", "en"))

    rounds = [
        round_item
        async for round_item in planner.search_rounds(plan, intent, ("ru", "en"))
    ]

    assert [item.query_variants for item in rounds] == [
        ("Гей", "порно", "твинк", "молодые"),
        ("Gay", "porn", "twink", "young"),
        ("Gay", "porn", "twink", "young"),
        ("twink",),
    ]
    assert [item.preferred_languages for item in rounds] == [
        ("ru",),
        ("en",),
        (),
        (),
    ]


@pytest.mark.asyncio
async def test_english_query_uses_or_then_language_broadening() -> None:
    planner = MultilingualQueryPlanner()
    intent = "Find videos about Bangkok night market beautiful"
    plan = await planner.plan(intent, ("en",))

    rounds = [
        round_item
        async for round_item in planner.search_rounds(plan, intent, ("en",))
    ]

    assert [item.query_variants for item in rounds] == [
        ("Bangkok", "night", "market", "beautiful"),
        ("Bangkok", "night", "market", "beautiful"),
        ("market",),
    ]
    assert [item.preferred_languages for item in rounds] == [("en",), (), ()]
    assert [item.relaxation_level for item in rounds] == [0, 1, 2]
    assert [item.specificity for item in rounds] == [0.25, 0.25, 0.25]


@pytest.mark.asyncio
async def test_cyrillic_en_only_uses_translated_or_terms() -> None:
    intent = "Найди видео про ночной Бангкок"
    translator = FakeTranslator("Bangkok at night")
    planner = MultilingualQueryPlanner(translator)
    plan = await planner.plan(intent, ("en",))

    rounds = [
        round_item
        async for round_item in planner.search_rounds(plan, intent, ("en",))
    ]

    assert [item.query_variants for item in rounds] == [
        ("Bangkok", "night"),
        ("Bangkok", "night"),
    ]
    assert [item.preferred_languages for item in rounds] == [("en",), ()]
    assert [item.relaxation_level for item in rounds] == [0, 1]


@pytest.mark.asyncio
async def test_multilingual_planner_falls_back_to_primary_or_terms_without_translation() -> None:
    translator = FakeTranslator(None)
    planner = MultilingualQueryPlanner(translator)
    intent = "Найди видео про ночной Бангкок"

    plan = await planner.plan(intent, ("ru", "en"))
    rounds = [
        round_item
        async for round_item in planner.search_rounds(plan, intent, ("ru", "en"))
    ]

    assert plan.query_variants == ("ночной Бангкок",)
    assert [item.query_variants for item in rounds] == [
        ("ночной", "Бангкок"),
        ("ночной", "Бангкок"),
    ]
    assert [item.preferred_languages for item in rounds] == [("ru",), ()]


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
    assert plan.retrieval_queries == ("Bangkok at night",)


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
