import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, cast

import httpx

_RUSSIAN_COMMAND_PREFIX = re.compile(
    r"^(?:найди|поищи|покажи)(?:\s+мне)?(?:\s+(?:видео|ролики?|посты?))?"
    r"(?:\s+(?:про|о|об|на\s+тему))?\s+",  # noqa: RUF001
    re.IGNORECASE,
)
_ENGLISH_COMMAND_PREFIX = re.compile(
    r"^(?:find|search(?:\s+for)?|show(?:\s+me)?)"
    r"(?:\s+(?:(?:a|the)\s+)?(?:videos?|clips?|posts?))?"
    r"(?:\s+(?:about|on|of))?\s+",
    re.IGNORECASE,
)
_CYRILLIC = re.compile(r"[\u0400-\u04FF]")


class EnglishIntentTranslator(Protocol):
    async def translate_to_english(self, intent: str) -> str | None: ...


@dataclass(frozen=True, slots=True)
class ScoutQueryRound:
    query_variants: tuple[str, ...]
    preferred_languages: tuple[str, ...]
    relaxation_level: int
    specificity: float
    strategy: str = "full_intent"


@dataclass(frozen=True, slots=True)
class ScoutQueryPlan:
    normalized_intent: str
    query_variants: tuple[str, ...]
    retrieval_queries: tuple[str, ...]


class MultilingualQueryPlanner:
    """Build conservative retrieval rounds that preserve the complete user intent.

    Retrieval must not silently delete semantic constraints just to broaden recall. The
    planner therefore keeps the normalized full intent intact and broadens only language
    coverage. Translation is a reformulation, not a license to drop terms. More granular
    constraint checks belong in downstream ranking/reranking stages where the original
    intent remains available.
    """

    def __init__(self, translator: EnglishIntentTranslator | None = None) -> None:
        self._translator = translator

    async def plan(
        self,
        intent: str,
        preferred_languages: tuple[str, ...],
    ) -> ScoutQueryPlan:
        primary = normalize_search_intent(intent)
        variants = [primary] if primary else []

        wants_english = "en" in {language.lower() for language in preferred_languages}
        if self._translator is not None and wants_english and _CYRILLIC.search(primary):
            translated = await self._translator.translate_to_english(intent)
            if translated is not None:
                normalized = normalize_search_intent(translated)
                if normalized and normalized.casefold() != primary.casefold():
                    variants.append(normalized)

        return ScoutQueryPlan(
            normalized_intent=primary,
            query_variants=tuple(dict.fromkeys(variants)),
            retrieval_queries=(primary,) if primary else (),
        )

    async def search_rounds(
        self,
        plan: ScoutQueryPlan,
        intent: str,
        preferred_languages: tuple[str, ...],
    ) -> AsyncIterator[ScoutQueryRound]:
        """Yield full-intent rounds, broadening language scope rather than semantics.

        A single-language request first keeps its provider language filter. If downstream
        curation still has too few relevant candidates, the next round removes only that
        language filter while retaining the complete normalized intent. Cyrillic RU+EN
        requests instead broaden into the complete bilingual reformulation.
        """

        del intent
        if not plan.retrieval_queries:
            return

        normalized_languages = tuple(
            dict.fromkeys(
                language.strip().lower()
                for language in preferred_languages
                if language.strip()
            )
        )
        wants_english = "en" in normalized_languages
        wants_russian = "ru" in normalized_languages
        query = plan.retrieval_queries[0]
        is_cyrillic = _CYRILLIC.search(query) is not None
        translation_available = len(plan.query_variants) > 1

        if is_cyrillic:
            if wants_russian:
                yield ScoutQueryRound(
                    query_variants=(query,),
                    preferred_languages=("ru",),
                    relaxation_level=0,
                    specificity=1.0,
                    strategy="full_intent_primary",
                )

            if wants_english and translation_available:
                english_variant = plan.query_variants[-1]
                if wants_russian:
                    yield ScoutQueryRound(
                        query_variants=tuple(dict.fromkeys((query, english_variant))),
                        preferred_languages=("ru", "en"),
                        relaxation_level=0,
                        specificity=1.0,
                        strategy="full_intent_multilingual",
                    )
                else:
                    yield ScoutQueryRound(
                        query_variants=(english_variant,),
                        preferred_languages=("en",),
                        relaxation_level=0,
                        specificity=1.0,
                        strategy="full_intent_translated",
                    )
                    yield ScoutQueryRound(
                        query_variants=(english_variant,),
                        preferred_languages=(),
                        relaxation_level=0,
                        specificity=1.0,
                        strategy="full_intent_language_broadening",
                    )
                return

            if wants_russian:
                yield ScoutQueryRound(
                    query_variants=(query,),
                    preferred_languages=(),
                    relaxation_level=0,
                    specificity=1.0,
                    strategy="full_intent_language_broadening",
                )
                return

            yield ScoutQueryRound(
                query_variants=(query,),
                preferred_languages=normalized_languages,
                relaxation_level=0,
                specificity=1.0,
                strategy="full_intent_primary",
            )
            if len(normalized_languages) == 1:
                yield ScoutQueryRound(
                    query_variants=(query,),
                    preferred_languages=(),
                    relaxation_level=0,
                    specificity=1.0,
                    strategy="full_intent_language_broadening",
                )
            return

        yield ScoutQueryRound(
            query_variants=(query,),
            preferred_languages=normalized_languages,
            relaxation_level=0,
            specificity=1.0,
            strategy="full_intent_primary",
        )
        if len(normalized_languages) == 1:
            yield ScoutQueryRound(
                query_variants=(query,),
                preferred_languages=(),
                relaxation_level=0,
                specificity=1.0,
                strategy="full_intent_language_broadening",
            )


class FallbackEnglishIntentTranslator:
    """Try translators in order; paid providers belong only in an explicit fallback slot."""

    def __init__(self, translators: tuple[EnglishIntentTranslator, ...]) -> None:
        self._translators = translators

    async def translate_to_english(self, intent: str) -> str | None:
        for translator in self._translators:
            translated = await translator.translate_to_english(intent)
            if translated is not None:
                return translated
        return None


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
