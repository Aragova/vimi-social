import math
import re
from collections.abc import Mapping
from dataclasses import replace
from typing import cast

from vimi_social.domain.source import CandidateContent

_TOKEN = re.compile(r"[^\W_]+(?:[-'][^\W_]+)*", re.UNICODE)
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_HASHTAG = re.compile(r"(?<!\w)#([\w-]+)", re.UNICODE)
_LINK_FARM = re.compile(
    r"\b(?:best|top)\b.{0,80}\b(?:sites?|websites?|directories|directory)\b",
    re.IGNORECASE,
)
_PROMO = re.compile(
    r"\b(?:click\s+here|visit\s+(?:our|the)|free\s+links?|link\s+in\s+bio)\b",
    re.IGNORECASE,
)

LONG_FORM_MIN_MS = 5 * 60 * 1000
LONG_FORM_MAX_MS = 30 * 60 * 1000
TIMELINE_SEMANTIC_MINIMUM = 0.84
TIMELINE_LONG_FORM_SEMANTIC_MINIMUM = 0.81
TIMELINE_LEXICAL_MIN_MATCHES = 2
E5_FLOOR = 0.70
PERSONAL_AFFINITY_WEIGHT = 0.10
DURATION_WEIGHT = 0.15
QUALITY_WEIGHT = 0.03
SPAM_WEIGHT = 0.35
HASHTAG_STUFFING_WEIGHT = 0.45
_EXACT_RETRIEVAL_STATE_KEYS = (
    "retrieval_query",
    "retrieval_query_variants",
    "retrieval_relaxation_level",
    "retrieval_specificity",
    "retrieval_language_mode",
    "retrieval_strategy",
    "x_search_scope",
    "x_search_query",
    "x_next_token",
    "x_page_start_token",
    "x_continuation_generation",
)


def prepare_timeline_seeds(
    seeds: tuple[CandidateContent, ...],
) -> tuple[CandidateContent, ...]:
    prepared: list[CandidateContent] = []
    for seed in seeds:
        metadata = dict(seed.connector_metadata)
        metadata["x_candidate_origin"] = "home_timeline"
        metadata["x_candidate_origins"] = ["home_timeline"]
        metadata["retrieval_strategy"] = "home_timeline"
        prepared.append(replace(seed, connector_metadata=metadata))
    return tuple(prepared)


def prepare_search_candidate(
    candidate: CandidateContent,
    *,
    query_variants: tuple[str, ...],
    preferred_languages: tuple[str, ...],
    relaxation_level: int,
    specificity: float,
    strategy: str,
    continuation_generation: int,
) -> CandidateContent:
    metadata = dict(candidate.connector_metadata)
    metadata["x_candidate_origin"] = "search"
    metadata["x_candidate_origins"] = ["search"]
    metadata["retrieval_query"] = query_variants[0]
    metadata["retrieval_query_variants"] = list(query_variants)
    metadata["retrieval_relaxation_level"] = relaxation_level
    metadata["retrieval_specificity"] = specificity
    metadata["retrieval_language_mode"] = "+".join(preferred_languages)
    metadata["retrieval_strategy"] = strategy
    metadata["x_continuation_generation"] = continuation_generation
    return replace(candidate, connector_metadata=metadata)


def merge_exact_candidates(
    candidates: tuple[CandidateContent, ...],
) -> tuple[CandidateContent, ...]:
    """Merge only identical provider post IDs; keep text-near-duplicates distinct."""

    result: list[CandidateContent] = []
    positions: dict[tuple[str, str], int] = {}
    for candidate in candidates:
        key = candidate_key(candidate)
        position = positions.get(key)
        if position is None:
            positions[key] = len(result)
            result.append(candidate)
            continue
        result[position] = _merge_exact_pair(result[position], candidate)
    return tuple(result)


def candidate_origins(candidate: CandidateContent) -> tuple[str, ...]:
    raw = candidate.connector_metadata.get("x_candidate_origins")
    if isinstance(raw, list | tuple):
        items = cast(list[object] | tuple[object, ...], raw)
        values = tuple(value for value in items if isinstance(value, str) and value)
        if values:
            return values
    origin = candidate.connector_metadata.get("x_candidate_origin")
    if isinstance(origin, str) and origin:
        return (origin,)
    return ()


def known_short(candidate: CandidateContent) -> bool:
    return (
        candidate.media_type == "video"
        and candidate.duration_ms is not None
        and 0 < candidate.duration_ms < 60_000
    )


def is_preferred_long_form(candidate: CandidateContent) -> bool:
    duration = candidate.duration_ms
    return duration is not None and LONG_FORM_MIN_MS <= duration <= LONG_FORM_MAX_MS


def distinct_query_token_count(query_variants: tuple[str, ...]) -> int:
    return len(
        {
            token.casefold()
            for variant in query_variants
            for token in _TOKEN.findall(variant)
            if token
        }
    )


def passes_query_gate(
    candidate: CandidateContent,
    *,
    semantic_raw: float | None,
    lexical: float,
    lexical_matches: int,
    query_token_count: int,
    minimum_relevance: float,
) -> bool:
    origins = candidate_origins(candidate)
    if semantic_raw is None:
        search_ok = lexical >= minimum_relevance
    else:
        text_gate = (0.35 * lexical) + (0.65 * calibrate_e5(semantic_raw))
        search_ok = text_gate >= minimum_relevance

    # If Search API independently retrieved this post, preserve that eligibility even
    # when the same provider post was also present in Home Timeline. Timeline provenance
    # may still influence personalization/ranking, but it must never make a valid Search
    # result harder to qualify.
    if "search" in origins:
        return search_ok

    if "home_timeline" in origins:
        semantic_minimum = (
            TIMELINE_LONG_FORM_SEMANTIC_MINIMUM
            if is_preferred_long_form(candidate)
            else TIMELINE_SEMANTIC_MINIMUM
        )
        semantic_ok = semantic_raw is not None and semantic_raw >= semantic_minimum

        # lexical_relevance returns the score and match count from the same best query
        # variant. Infer that variant's token count from coverage instead of counting the
        # union of alternative translations (for example, "футбол" + "football").
        # This preserves the two-token precision requirement for multi-word queries while
        # allowing a complete one-token translated variant to pass with one lexical hit.
        lexical_required = 0
        if lexical_matches > 0 and lexical > 0.0:
            inferred_variant_tokens = math.ceil(lexical_matches / lexical)
            available_tokens = max(1, query_token_count)
            lexical_required = min(
                TIMELINE_LEXICAL_MIN_MATCHES,
                available_tokens,
                max(1, inferred_variant_tokens),
            )
        lexical_ok = lexical_required > 0 and lexical_matches >= lexical_required
        return semantic_ok or lexical_ok

    return search_ok


def score_candidate(
    candidate: CandidateContent,
    *,
    semantic_raw: float | None,
    lexical: float,
    visual_relevance: float | None,
    ocr_relevance: float | None,
    visual_weight: float = 0.15,
    ocr_weight: float = 0.10,
) -> tuple[float, CandidateContent]:
    semantic = calibrate_e5(semantic_raw) if semantic_raw is not None else None
    text_relevance = lexical if semantic is None else (0.25 * lexical) + (0.75 * semantic)
    relevance = text_relevance
    if visual_relevance is not None:
        weight = max(0.0, min(0.40, visual_weight))
        relevance = ((1.0 - weight) * relevance) + (weight * visual_relevance)
    if ocr_relevance is not None:
        weight = max(0.0, min(0.25, ocr_weight))
        relevance = ((1.0 - weight) * relevance) + (weight * ocr_relevance)

    metadata = dict(candidate.connector_metadata)
    affinity = metadata_float(metadata, "personal_affinity_score", 0.0)
    duration = duration_preference(candidate)
    quality = quality_score(candidate)
    spam = spam_penalty(candidate)
    hashtag_stuffing = hashtag_stuffing_penalty(candidate)
    final = round(
        relevance
        + (PERSONAL_AFFINITY_WEIGHT * affinity)
        + (DURATION_WEIGHT * duration)
        + (QUALITY_WEIGHT * quality)
        - (SPAM_WEIGHT * spam)
        - (HASHTAG_STUFFING_WEIGHT * hashtag_stuffing),
        6,
    )

    metadata["curator_lexical_relevance_score"] = round(lexical, 6)
    if semantic_raw is not None and semantic is not None:
        metadata["curator_semantic_raw_score"] = round(semantic_raw, 6)
        metadata["curator_semantic_relevance_score"] = round(semantic, 6)
    if visual_relevance is not None:
        metadata["curator_visual_relevance_score"] = round(visual_relevance, 6)
    if ocr_relevance is not None:
        metadata["curator_preview_ocr_relevance_score"] = round(ocr_relevance, 6)
    metadata["curator_relevance_score"] = round(relevance, 6)
    metadata["curator_personalized_score"] = round(
        relevance + (PERSONAL_AFFINITY_WEIGHT * affinity),
        6,
    )
    metadata["curator_duration_preference_score"] = duration
    metadata["curator_quality_score"] = quality
    metadata["curator_spam_penalty_score"] = spam
    metadata["curator_hashtag_stuffing_penalty_score"] = hashtag_stuffing
    metadata["curator_v3_score"] = final
    metadata["curator_ranking_score"] = final
    return final, replace(candidate, connector_metadata=metadata)


def lexical_relevance(
    candidate: CandidateContent,
    query_variants: tuple[str, ...],
) -> tuple[float, int]:
    searchable = " ".join(
        part
        for part in (
            candidate.title or "",
            candidate.caption or "",
            " ".join(candidate.tags),
        )
        if part
    ).casefold()
    candidate_tokens = tuple(token.casefold() for token in _TOKEN.findall(searchable))
    if not candidate_tokens:
        return 0.0, 0

    best_score = 0.0
    best_matches = 0
    for variant in query_variants:
        query_tokens = tuple(
            dict.fromkeys(token.casefold() for token in _TOKEN.findall(variant) if token)
        )
        if not query_tokens:
            continue
        matches = sum(
            1
            for query_token in query_tokens
            if any(
                _token_matches(query_token, candidate_token)
                for candidate_token in candidate_tokens
            )
        )
        coverage = matches / len(query_tokens)
        phrase_bonus = (
            0.10
            if len(query_tokens) > 1 and variant.casefold() in searchable
            else 0.0
        )
        score = min(1.0, coverage + phrase_bonus)
        if (score, matches) > (best_score, best_matches):
            best_score, best_matches = score, matches
    return round(best_score, 6), best_matches


def calibrate_e5(value: float) -> float:
    bounded = max(E5_FLOOR, min(1.0, float(value)))
    return round((bounded - E5_FLOOR) / (1.0 - E5_FLOOR), 6)


def relative_visual_scores(
    candidates: tuple[CandidateContent, ...],
    values: tuple[float | None, ...],
) -> dict[tuple[str, str], float]:
    distinct = sorted({value for value in values if value is not None})
    if len(distinct) < 2:
        return {}
    denominator = len(distinct) - 1
    calibration = {value: index / denominator for index, value in enumerate(distinct)}
    return {
        candidate_key(candidate): round(calibration[value], 6)
        for candidate, value in zip(candidates, values, strict=True)
        if value is not None
    }


def duration_preference(candidate: CandidateContent) -> float:
    duration = candidate.duration_ms
    if duration is None or duration <= 0:
        return 0.50
    if duration < 60_000:
        return 0.0
    if duration < LONG_FORM_MIN_MS:
        return 0.70
    if duration <= LONG_FORM_MAX_MS:
        return 1.0
    return 0.90


def metadata_float(metadata: Mapping[str, object], key: str, default: float) -> float:
    value = metadata.get(key)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return default


def candidate_key(candidate: CandidateContent) -> tuple[str, str]:
    return candidate.source, candidate.source_id


def quality_score(candidate: CandidateContent) -> float:
    total = sum(max(0, int(value)) for value in candidate.engagement.values())
    if total <= 0:
        return 0.0
    return round(min(1.0, math.log1p(total) / math.log1p(100_000)), 6)


def spam_penalty(candidate: CandidateContent) -> float:
    text = " ".join((candidate.caption or candidate.title or "").split())
    if not text:
        return 0.0
    tokens = _TOKEN.findall(text)
    url_count = len(_URL.findall(text))
    penalty = 0.0
    if _LINK_FARM.search(text):
        penalty += 0.65
    if _PROMO.search(text):
        penalty += 0.25
    if url_count >= 2:
        penalty += 0.25
    elif url_count == 1 and len(tokens) <= 12:
        penalty += 0.12
    return round(min(1.0, penalty), 6)


def hashtag_stuffing_penalty(candidate: CandidateContent) -> float:
    """Demote hashtag-dense captions without deleting distinct provider posts."""

    text = " ".join((candidate.caption or candidate.title or "").split())
    if not text:
        return 0.0
    hashtags = _HASHTAG.findall(text)
    hashtag_count = len(hashtags)
    if hashtag_count < 4:
        return 0.0
    token_count = max(1, len(_TOKEN.findall(text)))
    hashtag_ratio = hashtag_count / token_count
    if hashtag_count >= 8 and hashtag_ratio >= 0.50:
        return 1.0
    if hashtag_count >= 6 and hashtag_ratio >= 0.50:
        return 0.80
    if hashtag_count >= 4 and hashtag_ratio >= 0.60:
        return 0.50
    return 0.0


def _merge_exact_pair(left: CandidateContent, right: CandidateContent) -> CandidateContent:
    left_origins = candidate_origins(left)
    right_origins = candidate_origins(right)
    origins = tuple(dict.fromkeys((*left_origins, *right_origins)))

    if _payload_richness(right) > _payload_richness(left):
        winner, other = right, left
    else:
        winner, other = left, right
    metadata = dict(other.connector_metadata)
    metadata.update(winner.connector_metadata)

    search_copy = (
        right
        if "search" in right_origins
        else left
        if "search" in left_origins
        else None
    )
    if search_copy is not None:
        for key in _EXACT_RETRIEVAL_STATE_KEYS:
            metadata.pop(key, None)
        for key in _EXACT_RETRIEVAL_STATE_KEYS:
            if key in search_copy.connector_metadata:
                metadata[key] = search_copy.connector_metadata[key]

    metadata["x_candidate_origins"] = list(origins)
    metadata["x_candidate_origin"] = (
        "home_timeline"
        if "home_timeline" in origins
        else origins[0]
        if origins
        else "search"
    )
    return replace(winner, connector_metadata=metadata)


def _payload_richness(candidate: CandidateContent) -> tuple[int, int, int, int]:
    duration = candidate.duration_ms or 0
    text_length = len(candidate.caption or candidate.title or "")
    engagement = sum(max(0, int(value)) for value in candidate.engagement.values())
    dimensions = int(candidate.width is not None and candidate.height is not None)
    return (int(duration > 0), duration, text_length + dimensions, engagement)


def _token_matches(query: str, candidate: str) -> bool:
    if query == candidate:
        return True
    if len(query) >= 4 and len(candidate) >= 4:
        return query.startswith(candidate) or candidate.startswith(query)
    return False
