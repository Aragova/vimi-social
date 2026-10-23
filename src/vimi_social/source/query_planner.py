import re
from dataclasses import dataclass
from typing import Protocol, cast

import httpx

_RUSSIAN_COMMAND_PREFIX = re.compile(
    r"^(?:найди|поищи|покажи)(?:\s+мне)?(?:\s+(?:видео|ролики?|посты?))?"  # noqa: RUF001
    r"(?:\s+(?:про|о|об|на\s+тему))?\s+",  # noqa: RUF001
    re.IGNORECASE,
)
_ENGLISH_COMMAND_PREFIX = re.compile(
    r"^(?:find|search(?:\s+for)?|show(?:\s+me)?)(?:\s+(?:videos?|clips?|posts?))?"
    r"(?:\s+(?:about|on))?\s+",
    re.IGNORECASE,
)
_CYRILLIC = re.compile(r"[\u0400-\u04FF]")


class EnglishIntentTranslator(Protocol):
    async def translate_to_english(self, intent: str) -> str | None: ...


@dataclass(frozen=True, slots=True)
class ScoutQueryPlan:
    query_variants: tuple[str, ...]


class MultilingualQueryPlanner:
    def __init__(self, translator: EnglishIntentTranslator | None = None) -> None:
        self._translator = translator

    async def plan(
        self,
        intent: str,
        preferred_languages: tuple[str, ...],
    ) -> ScoutQueryPlan:
        primary = normalize_search_intent(intent)
        variants = [primary]

        wants_english = "en" in {language.lower() for language in preferred_languages}
        if self._translator is not None and wants_english and _CYRILLIC.search(primary):
            translated = await self._translator.translate_to_english(primary)
            if translated is not None:
                normalized = normalize_search_intent(translated)
                if normalized and normalized.casefold() != primary.casefold():
                    variants.append(normalized)

        return ScoutQueryPlan(query_variants=tuple(dict.fromkeys(variants)))


class OpenAIEnglishIntentTranslator:
    def __init__(
        self,
        api_key: str,
        *,
        model: str = "gpt-6-luna",
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        key = api_key.strip()
        if not key:
            raise ValueError("Search translation API key must not be empty")
        self._api_key = key
        self._model = model.strip() or "gpt-6-luna"
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)
        self._owns_client = client is None

    async def translate_to_english(self, intent: str) -> str | None:
        prompt = normalize_search_intent(intent)
        if not prompt:
            return None

        try:
            response = await self._client.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "store": False,
                    "max_output_tokens": 64,
                    "instructions": (
                        "Convert the user's social-media source-search intent into concise "
                        "English search keywords. Preserve names and meaning, remove command "
                        "words such as find/show/video about, do not add facts, and return only "
                        "the English search query without quotes or commentary."
                    ),
                    "input": prompt,
                },
            )
        except httpx.HTTPError:
            return None
        if response.status_code >= 400:
            return None

        try:
            payload_obj: object = response.json()
        except ValueError:
            return None
        if not isinstance(payload_obj, dict):
            return None
        payload = cast(dict[str, object], payload_obj)
        return _response_output_text(payload)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def normalize_search_intent(intent: str) -> str:
    normalized = " ".join(intent.split()).strip()
    if not normalized:
        return ""

    for pattern in (_RUSSIAN_COMMAND_PREFIX, _ENGLISH_COMMAND_PREFIX):
        stripped = pattern.sub("", normalized, count=1).strip()
        if stripped != normalized and stripped:
            normalized = stripped
            break
    return normalized


def _response_output_text(payload: dict[str, object]) -> str | None:
    output_obj = payload.get("output")
    if not isinstance(output_obj, list):
        return None

    for raw_item in cast(list[object], output_obj):
        if not isinstance(raw_item, dict):
            continue
        item = cast(dict[str, object], raw_item)
        content_obj = item.get("content")
        if not isinstance(content_obj, list):
            continue
        for raw_content in cast(list[object], content_obj):
            if not isinstance(raw_content, dict):
                continue
            content = cast(dict[str, object], raw_content)
            if content.get("type") != "output_text":
                continue
            text = content.get("text")
            if isinstance(text, str):
                normalized = " ".join(text.split()).strip().strip('"').strip("'")
                return normalized or None
    return None
