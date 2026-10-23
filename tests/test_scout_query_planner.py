import json

import httpx
import pytest

from vimi_social.source.query_planner import (
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


@pytest.mark.asyncio
async def test_multilingual_planner_keeps_ru_and_adds_en_variant() -> None:
    translator = FakeTranslator("Bangkok night")
    planner = MultilingualQueryPlanner(translator)

    plan = await planner.plan(
        "Найди видео про ночной Бангкок",
        ("ru", "en"),
    )

    assert translator.calls == ["ночной Бангкок"]
    assert plan.query_variants == ("ночной Бангкок", "Bangkok night")


@pytest.mark.asyncio
async def test_multilingual_planner_falls_back_to_original_when_translation_is_unavailable() -> None:
    translator = FakeTranslator(None)
    planner = MultilingualQueryPlanner(translator)

    plan = await planner.plan("Найди видео про ночной Бангкок", ("ru", "en"))

    assert plan.query_variants == ("ночной Бангкок",)


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
