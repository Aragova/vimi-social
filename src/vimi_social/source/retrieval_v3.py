import re
from collections.abc import AsyncIterator
from dataclasses import replace

from vimi_social.domain.source import CandidateContent
from vimi_social.source.personalization import (
    PersonalizedFilteringCandidateCurator,
    PersonalizedScoutActivities,
)
from vimi_social.source.query_planner import (
    MultilingualQueryPlanner,
    ScoutQueryPlan,
    ScoutQueryRound,
)

_TOKEN = re.compile(r"[^\W_]+(?:[-'][^\W_]+)*", re.UNICODE)
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_LINK_FARM = re.compile(
    r"\b(?:best|top)\b.{0,80}\b(?:sites?|websites?|directories|directory)\b",
    re.IGNORECASE,
)
_PROMO = re.compile(
    r"\b(?:click\s+here|visit\s+(?:our|the)|free\s+links?|link\s+in\s+bio)\b",
    re.IGNORECASE,
)
_CONCEPT_STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "about",
    "for",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
    "\u0432",
    "\u0434\u043b\u044f",
    "\u0438",
    "\u0438\u0437",
    "\u0438\u043b\u0438",
    "\u043a",
    "\u043d\u0430",
    "\u043e",
    "\u043e\u0431",
    "\u043f\u043e",
    "\u043f\u0440\u043e",
    "\u0441",
    "\u0441\u043e",
}
_CONCEPT_VARIANT_LIMIT = 3
_RELEVANT_TARGET = 10
_LONG_FORM_TARGET = 3
_LONG_FORM_MIN_MS = 5 * 60 * 1000
_LONG_FORM_MAX_MS = 30 * 60 * 1000
_DURATION_RANK_WEIGHT = 0.06
_SPAM_PENALTY_WEIGHT = 0.35
_TIMELINE_SEMANTIC_RAW_MINIMUM = 0.84
_TIMELINE_LEXICAL_MIN_MATCHES = 2


class ConceptQueryPlanner(MultilingualQueryPlanner):
    """Add bounded multi-concept recall before the existing broad OR fallback."""

    def __init__(self, delegate: MultilingualQueryPlanner) -> None:
        self._delegate = delegate

    async def plan(
        self,
        intent: str,
        preferred_languages: tuple[str, ...],
    ) -> ScoutQueryPlan:
        return await self._delegate.plan(intent, preferred_languages)

    async def search_rounds(
        self,
        plan: ScoutQueryPlan,
        intent: str,
        preferred_languages: tuple[str, ...],
    ) -> AsyncIterator[ScoutQueryRound]:
        normalized_languages = {
            language.strip().lower()
            for language in preferred_languages
            if language.strip()
        }
        emitted: set[tuple[str, ...]] = set()
        # PersonalizedQueryPlanner, when present, owns level 0. Every round emitted by
        # this V3 delegate gets a unique, monotonically increasing level so continuation
        # state can never confuse an earlier concept cursor with a later broad round.
        next_round_level = 1

        for variant in plan.query_variants:
            concepts = _concept_variants(variant)
            if not concepts or concepts in emitted:
                continue
            emitted.add(concepts)
            tokens = _content_tokens(variant)
            specificity = min(1.0, 2 / max(1, len(tokens)))
            if all(concept.isascii() for concept in concepts) and "en" in normalized_languages:
                round_languages = ("en",)
            elif (
                any(not concept.isascii() for concept in concepts)
                and "ru" in normalized_languages
            ):
                round_languages = ("ru",)
            else:
                round_languages = ()
            yield ScoutQueryRound(
                query_variants=concepts,
                preferred_languages=round_languages,
                relaxation_level=next_round_level,
                specificity=specificity,
                strategy="provider_concept_recall",
                max_pages=1,
            )
            next_round_level += 1

        async for search_round in self._delegate.search_rounds(
            plan,
            intent,
            preferred_languages,
        ):
            yield replace(search_round, relaxation_level=next_round_level)
            next_round_level += 1


class RetrievalV3ScoutActivities(PersonalizedScoutActivities):
    """Keep retrieval open while X only returns short-but-eligible video results."""

    async def _rank_relevant_pool(
        self,
        query_variants: tuple[str, ...],
        preferred_languages: tuple[str, ...],
        discovered: list[CandidateContent],
    ) -> tuple[CandidateContent, ...]:
        relevant = await super()._rank_relevant_pool(
            query_variants,
            preferred_languages,
            discovered,
        )
        return retrieval_target_view(relevant)


class RetrievalV3CandidateCurator(PersonalizedFilteringCandidateCurator):
    """Apply bounded duration preference and generic SEO/link-farm suppression."""

    def rank(
        self,
        candidates: tuple[CandidateContent, ...],
        *,
        query_variants: tuple[str, ...],
        preferred_languages: tuple[str, ...],
        limit: int,
        semantic_scores: tuple[float, ...] | None = None,
        visual_scores: tuple[float | None, ...] | None = None,
        preview_ocr_texts: tuple[str | None, ...] | None = None,
        preview_ocr_semantic_scores: tuple[float | None, ...] | None = None,
        visual_weight: float = 0.15,
        preview_ocr_weight: float = 0.10,
        minimum_relevance: float = 0.0,
    ) -> tuple[CandidateContent, ...]:
        if limit < 1:
            return ()

        gated, indices = _apply_home_timeline_precision_gate(
            candidates,
            query_variants=query_variants,
            semantic_scores=semantic_scores,
        )
        if not gated:
            return ()

        ranked = super().rank(
            gated,
            query_variants=query_variants,
            preferred_languages=preferred_languages,
            limit=max(1, len(gated)),
            semantic_scores=(
                tuple(semantic_scores[index] for index in indices)
                if semantic_scores is not None
                else None
            ),
            visual_scores=(
                tuple(visual_scores[index] for index in indices)
                if visual_scores is not None
                else None
            ),
            preview_ocr_texts=(
                tuple(preview_ocr_texts[index] for index in indices)
                if preview_ocr_texts is not None
                else None
            ),
            preview_ocr_semantic_scores=(
                tuple(preview_ocr_semantic_scores[index] for index in indices)
                if preview_ocr_semantic_scores is not None
                else None
            ),
            visual_weight=visual_weight,
            preview_ocr_weight=preview_ocr_weight,
            minimum_relevance=minimum_relevance,
        )
        if not ranked:
            return ()

        rescored: list[
            tuple[float, float, float, float, float, float, float, int, CandidateContent]
        ] = []
        for index, candidate in enumerate(ranked):
            metadata = dict(candidate.connector_metadata)
            personalized = _metadata_float(
                metadata,
                "curator_personalized_score",
                _metadata_float(metadata, "curator_relevance_score", 0.0),
            )
            relevance = _metadata_float(metadata, "curator_relevance_score", 0.0)
            duration = _metadata_float(
                metadata,
                "curator_duration_preference_score",
                _duration_preference(candidate),
            )
            spam_penalty = _link_farm_penalty(candidate)
            v3_score = round(
                personalized
                + (_DURATION_RANK_WEIGHT * duration)
                - (_SPAM_PENALTY_WEIGHT * spam_penalty),
                6,
            )
            metadata["curator_spam_penalty_score"] = spam_penalty
            metadata["curator_v3_score"] = v3_score
            metadata["curator_ranking_score"] = v3_score
            updated = replace(candidate, connector_metadata=metadata)
            rescored.append(
                (
                    v3_score,
                    personalized,
                    relevance,
                    _metadata_float(
                        metadata,
                        "curator_semantic_relevance_score",
                        -1.0,
                    ),
                    _metadata_float(metadata, "curator_lexical_relevance_score", 0.0),
                    duration,
                    _metadata_float(metadata, "curator_quality_score", 0.0),
                    -index,
                    updated,
                )
            )

        rescored.sort(key=lambda item: item[:8], reverse=True)
        result: list[CandidateContent] = []
        for rank, item in enumerate(rescored[:limit], start=1):
            candidate = item[8]
            metadata = dict(candidate.connector_metadata)
            metadata["curator_rank"] = rank
            result.append(replace(candidate, connector_metadata=metadata))
        return tuple(result)


def _apply_home_timeline_precision_gate(
    candidates: tuple[CandidateContent, ...],
    *,
    query_variants: tuple[str, ...],
    semantic_scores: tuple[float, ...] | None,
) -> tuple[tuple[CandidateContent, ...], tuple[int, ...]]:
    """Keep timeline recall query-safe without requiring literal caption wording.

    Home Timeline is personalized but not query-constrained. A strong local E5 match
    therefore acts as the primary absolute gate. When E5 is unavailable, require at
    least two distinct lexical intent tokens. Candidates that pass this source-specific
    gate are handed to the normal Curator for the same filtering/ranking as Search API
    results; their broad retrieval specificity is preserved separately for diagnostics.
    """

    query_tokens = _normalized_content_tokens(" ".join(query_variants))
    lexical_required = min(_TIMELINE_LEXICAL_MIN_MATCHES, len(query_tokens))
    kept: list[CandidateContent] = []
    indices: list[int] = []

    for index, candidate in enumerate(candidates):
        if candidate.connector_metadata.get("x_candidate_origin") != "home_timeline":
            kept.append(candidate)
            indices.append(index)
            continue

        text = " ".join(
            part
            for part in (candidate.title, candidate.caption, " ".join(candidate.tags))
            if part
        )
        candidate_tokens = set(_normalized_content_tokens(text))
        lexical_matches = len(set(query_tokens) & candidate_tokens)
        semantic_raw = semantic_scores[index] if semantic_scores is not None else None
        semantic_ok = (
            semantic_raw is not None
            and float(semantic_raw) >= _TIMELINE_SEMANTIC_RAW_MINIMUM
        )
        lexical_ok = lexical_required > 0 and lexical_matches >= lexical_required
        if not semantic_ok and not lexical_ok:
            continue

        metadata = dict(candidate.connector_metadata)
        metadata["curator_timeline_gate_method"] = (
            "semantic" if semantic_ok else "lexical_fallback"
        )
        metadata["curator_timeline_lexical_match_count"] = lexical_matches
        metadata["curator_timeline_semantic_raw_score"] = (
            round(float(semantic_raw), 6) if semantic_raw is not None else None
        )
        if "retrieval_specificity" in metadata:
            metadata["retrieval_source_specificity"] = metadata["retrieval_specificity"]
            # The timeline-specific gate above already enforces absolute query
            # relevance. Removing this field prevents the generic broad-search gate
            # from applying a second lexical-heavy threshold to the same candidate.
            metadata.pop("retrieval_specificity", None)
        kept.append(replace(candidate, connector_metadata=metadata))
        indices.append(index)

    return tuple(kept), tuple(indices)


def _normalized_content_tokens(value: str) -> tuple[str, ...]:
    return tuple(token.casefold() for token in _content_tokens(value))


def _concept_variants(value: str) -> tuple[str, ...]:
    tokens = _content_tokens(value)
    if len(tokens) < 3:
        return ()
    midpoint = (len(tokens) - 1) / 2
    pivot_index = min(
        range(len(tokens)),
        key=lambda index: (
            abs(index - midpoint),
            -len(tokens[index]),
            index,
        ),
    )
    pivot = tokens[pivot_index]
    ordered_indices = sorted(
        (index for index in range(len(tokens)) if index != pivot_index),
        key=lambda index: (abs(index - pivot_index), index),
    )
    result: list[str] = []
    for index in ordered_indices:
        left, right = sorted((pivot, tokens[index]), key=lambda item: tokens.index(item))
        concept = f"{left} {right}"
        if concept not in result:
            result.append(concept)
        if len(result) >= _CONCEPT_VARIANT_LIMIT:
            break
    return tuple(result)


def _content_tokens(value: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            token
            for token in _TOKEN.findall(value)
            if token.casefold() not in _CONCEPT_STOPWORDS
        )
    )


def retrieval_target_view(
    relevant: tuple[CandidateContent, ...],
) -> tuple[CandidateContent, ...]:
    """Return the stop-decision view while preserving the full discovered pool."""

    if len(relevant) < _RELEVANT_TARGET:
        return relevant

    known_durations = tuple(
        candidate.duration_ms
        for candidate in relevant
        if candidate.duration_ms is not None and candidate.duration_ms > 0
    )
    if len(known_durations) < _LONG_FORM_TARGET:
        return relevant

    preferred_long_form = sum(
        _LONG_FORM_MIN_MS <= duration <= _LONG_FORM_MAX_MS
        for duration in known_durations
    )
    if preferred_long_form >= _LONG_FORM_TARGET:
        return relevant

    # ScoutActivities only checks len(pool) >= 10 to decide whether recall can stop.
    # Return a bounded target-view here without discarding the actual discovered pool,
    # so the next concept/fallback round may continue inside the same read budget.
    return relevant[: _RELEVANT_TARGET - 1]


def _link_farm_penalty(candidate: CandidateContent) -> float:
    text = candidate.caption or candidate.title or ""
    if not text:
        return 0.0
    normalized = " ".join(text.split())
    tokens = _TOKEN.findall(normalized)
    url_count = len(_URL.findall(normalized))
    penalty = 0.0
    if _LINK_FARM.search(normalized):
        penalty += 0.65
    if _PROMO.search(normalized):
        penalty += 0.25
    if url_count >= 2:
        penalty += 0.25
    elif url_count == 1 and len(tokens) <= 12:
        penalty += 0.12
    return round(min(1.0, penalty), 6)


def _duration_preference(candidate: CandidateContent) -> float:
    duration_ms = candidate.duration_ms
    if duration_ms is None or duration_ms <= 0:
        return 0.50
    seconds = duration_ms / 1000
    if seconds < 60:
        return 0.0
    if seconds < 300:
        return 0.70
    if seconds <= 1800:
        return 1.0
    return 0.90


def _metadata_float(metadata: dict[str, object], key: str, default: float) -> float:
    value = metadata.get(key)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return default
