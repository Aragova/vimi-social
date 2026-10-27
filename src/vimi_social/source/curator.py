import math
import re
from dataclasses import replace

from vimi_social.domain.source import CandidateContent

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_HASHTAG = re.compile(r"(?<!\w)#[^\s#]+", re.UNICODE)
_REPEATED_PUNCTUATION = re.compile(r"[!?]{4,}")
_E5_SIMILARITY_FLOOR = 0.70
_RETRIEVAL_FULL_QUERY_MINIMUM = 0.48
_RETRIEVAL_BROADENING_SPAN = 0.16
_RRF_RANK_CONSTANT = 60.0


class CandidateCurator:
    """Deterministic ranking with optional local semantic, visual and OCR evidence."""

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
        if semantic_scores is not None and len(semantic_scores) != len(candidates):
            raise ValueError("semantic score count must match candidate count")
        if visual_scores is not None and len(visual_scores) != len(candidates):
            raise ValueError("visual score count must match candidate count")
        if preview_ocr_texts is not None and len(preview_ocr_texts) != len(candidates):
            raise ValueError("preview OCR text count must match candidate count")
        if (
            preview_ocr_semantic_scores is not None
            and len(preview_ocr_semantic_scores) != len(candidates)
        ):
            raise ValueError("preview OCR semantic score count must match candidate count")

        visual_relevances = (
            _calibrate_siglip_relevances(visual_scores)
            if visual_scores is not None
            else None
        )
        lexical_relevances = tuple(
            _relevance_score(candidate, query_variants, preferred_languages)
            for candidate in candidates
        )
        semantic_relevances = tuple(
            _calibrate_e5_relevance(score) for score in semantic_scores
        ) if semantic_scores is not None else tuple(None for _ in candidates)
        text_gate_scores = tuple(
            _score_based_text_relevance(lexical, semantic)
            for lexical, semantic in zip(
                lexical_relevances,
                semantic_relevances,
                strict=True,
            )
        )

        eligible_indices: list[int] = []
        candidate_minimums: dict[int, float] = {}
        for index, candidate in enumerate(candidates):
            candidate_minimum = _candidate_minimum_relevance(candidate, minimum_relevance)
            candidate_minimums[index] = candidate_minimum
            semantic_relevance = semantic_relevances[index]
            enforce_precision_gate = (
                semantic_relevance is not None
                or _requires_full_intent_fallback_gate(candidate)
            )
            if enforce_precision_gate and text_gate_scores[index] < candidate_minimum:
                continue
            eligible_indices.append(index)

        if not eligible_indices:
            return ()

        text_fusion_scores = _rrf_text_relevances(
            lexical_relevances,
            semantic_relevances,
            tuple(eligible_indices),
        )

        scored: list[tuple[float, float, float, float, int, CandidateContent]] = []
        for index in eligible_indices:
            candidate = candidates[index]
            lexical_relevance = lexical_relevances[index]
            semantic_raw = semantic_scores[index] if semantic_scores is not None else None
            semantic_relevance = semantic_relevances[index]
            text_relevance = text_fusion_scores[index]

            visual_raw = visual_scores[index] if visual_scores is not None else None
            visual_relevance = (
                visual_relevances[index] if visual_relevances is not None else None
            )
            relevance = _fused_visual_relevance(
                text_relevance,
                visual_relevance,
                visual_weight,
            )

            preview_ocr_text = (
                preview_ocr_texts[index] if preview_ocr_texts is not None else None
            )
            preview_ocr_raw = (
                preview_ocr_semantic_scores[index]
                if preview_ocr_semantic_scores is not None
                else None
            )
            preview_ocr_relevance = (
                _calibrate_e5_relevance(preview_ocr_raw)
                if preview_ocr_raw is not None
                else None
            )
            relevance = _fused_ocr_relevance(
                relevance,
                preview_ocr_relevance,
                preview_ocr_weight,
            )

            quality = _quality_score(candidate)
            metadata = dict(candidate.connector_metadata)
            metadata["curator_lexical_relevance_score"] = lexical_relevance
            if semantic_relevance is not None and semantic_raw is not None:
                metadata["curator_semantic_relevance_score"] = semantic_relevance
                metadata["curator_semantic_raw_score"] = round(semantic_raw, 6)
            metadata["curator_text_gate_score"] = text_gate_scores[index]
            metadata["curator_text_relevance_score"] = text_relevance
            metadata["curator_text_fusion_method"] = "rrf"
            metadata["curator_rrf_rank_constant"] = _RRF_RANK_CONSTANT
            metadata["curator_minimum_text_relevance_score"] = candidate_minimums[index]
            if visual_raw is not None:
                metadata["curator_visual_raw_score"] = round(visual_raw, 6)
            if visual_relevance is not None:
                metadata["curator_visual_relevance_score"] = visual_relevance
            if preview_ocr_text:
                metadata["curator_preview_ocr_text"] = preview_ocr_text
            if preview_ocr_raw is not None:
                metadata["curator_preview_ocr_semantic_raw_score"] = round(
                    preview_ocr_raw,
                    6,
                )
            if preview_ocr_relevance is not None:
                metadata["curator_preview_ocr_relevance_score"] = preview_ocr_relevance
            metadata["curator_relevance_score"] = relevance
            metadata["curator_quality_score"] = quality
            metadata["curator_total_score"] = relevance
            scored_candidate = replace(candidate, connector_metadata=metadata)
            semantic_tiebreak = semantic_relevance if semantic_relevance is not None else -1.0
            scored.append(
                (
                    relevance,
                    semantic_tiebreak,
                    lexical_relevance,
                    quality,
                    -index,
                    scored_candidate,
                )
            )

        scored.sort(key=lambda item: item[:5], reverse=True)

        ranked: list[CandidateContent] = []
        for rank, item in enumerate(scored[:limit], start=1):
            candidate = item[5]
            metadata = dict(candidate.connector_metadata)
            metadata["curator_rank"] = rank
            ranked.append(replace(candidate, connector_metadata=metadata))
        return tuple(ranked)


def restore_curator_order(
    candidates: tuple[CandidateContent, ...],
) -> tuple[CandidateContent, ...]:
    """Restore persisted curator order while keeping unranked legacy rows stable."""

    indexed = tuple(enumerate(candidates))

    def key(item: tuple[int, CandidateContent]) -> tuple[int, int, int]:
        index, candidate = item
        rank = candidate.connector_metadata.get("curator_rank")
        if isinstance(rank, int) and not isinstance(rank, bool) and rank > 0:
            return (0, rank, index)
        return (1, index, index)

    return tuple(candidate for _, candidate in sorted(indexed, key=key))


def _candidate_minimum_relevance(candidate: CandidateContent, configured: float) -> float:
    configured_minimum = max(0.0, min(1.0, configured))
    raw_specificity = candidate.connector_metadata.get("retrieval_specificity")
    if (
        not isinstance(raw_specificity, int | float)
        or isinstance(raw_specificity, bool)
    ):
        return configured_minimum

    specificity = max(0.0, min(1.0, float(raw_specificity)))
    dynamic_minimum = _RETRIEVAL_FULL_QUERY_MINIMUM + (
        _RETRIEVAL_BROADENING_SPAN * (1.0 - specificity)
    )
    return round(max(configured_minimum, min(1.0, dynamic_minimum)), 6)


def _requires_full_intent_fallback_gate(candidate: CandidateContent) -> bool:
    raw_specificity = candidate.connector_metadata.get("retrieval_specificity")
    if (
        not isinstance(raw_specificity, int | float)
        or isinstance(raw_specificity, bool)
    ):
        return False
    return float(raw_specificity) < 1.0


def _score_based_text_relevance(lexical: float, semantic: float | None) -> float:
    """Absolute relevance score used only by the precision gate, never for ordering."""

    if semantic is None:
        return lexical
    return round(min(1.0, (0.35 * lexical) + (0.65 * semantic)), 6)


def _rrf_text_relevances(
    lexical_values: tuple[float, ...],
    semantic_values: tuple[float | None, ...],
    eligible_indices: tuple[int, ...],
) -> dict[int, float]:
    """Fuse lexical and semantic result positions without mixing their score scales."""

    lexical_ranks = _rank_positions(
        {index: lexical_values[index] for index in eligible_indices}
    )
    semantic_inputs = {
        index: semantic_values[index]
        for index in eligible_indices
        if semantic_values[index] is not None
    }
    semantic_ranks = _rank_positions(
        {index: value for index, value in semantic_inputs.items() if value is not None}
    )
    has_semantic = bool(semantic_ranks)
    maximum = (1.0 + (1.0 if has_semantic else 0.0)) / (
        _RRF_RANK_CONSTANT + 1.0
    )

    fused: dict[int, float] = {}
    for index in eligible_indices:
        score = 1.0 / (_RRF_RANK_CONSTANT + lexical_ranks[index])
        semantic_rank = semantic_ranks.get(index)
        if semantic_rank is not None:
            score += 1.0 / (_RRF_RANK_CONSTANT + semantic_rank)
        fused[index] = round(min(1.0, score / maximum), 6)
    return fused


def _rank_positions(values: dict[int, float]) -> dict[int, int]:
    """Return stable competition ranks while giving equal evidence equal rank."""

    ranked: dict[int, int] = {}
    previous_value: float | None = None
    previous_rank = 0
    for position, (index, value) in enumerate(
        sorted(values.items(), key=lambda item: (-item[1], item[0])),
        start=1,
    ):
        if previous_value is None or value != previous_value:
            previous_rank = position
            previous_value = value
        ranked[index] = previous_rank
    return ranked


def _fused_visual_relevance(text: float, visual: float | None, weight: float) -> float:
    if visual is None:
        return text
    bounded_weight = max(0.0, min(0.40, weight))
    return round(((1.0 - bounded_weight) * text) + (bounded_weight * visual), 6)


def _fused_ocr_relevance(base: float, ocr: float | None, weight: float) -> float:
    if ocr is None:
        return base
    bounded_weight = max(0.0, min(0.25, weight))
    return round(((1.0 - bounded_weight) * base) + (bounded_weight * ocr), 6)


def _calibrate_e5_relevance(value: float) -> float:
    """Map multilingual-E5's compressed cosine range into useful relevance space."""

    bounded = max(_E5_SIMILARITY_FLOOR, min(1.0, value))
    calibrated = (bounded - _E5_SIMILARITY_FLOOR) / (1.0 - _E5_SIMILARITY_FLOOR)
    return round(calibrated, 6)


def _calibrate_siglip_relevances(
    values: tuple[float | None, ...],
) -> tuple[float | None, ...]:
    """Convert compressed SigLIP cosine scores into task-relative rerank evidence."""

    bounded_values = tuple(
        None if value is None else max(-1.0, min(1.0, value)) for value in values
    )
    distinct = sorted({value for value in bounded_values if value is not None})
    if len(distinct) < 2:
        return tuple(None for _ in values)

    denominator = len(distinct) - 1
    calibration = {
        value: round(index / denominator, 6)
        for index, value in enumerate(distinct)
    }
    return tuple(
        None if value is None else calibration[value]
        for value in bounded_values
    )


def _relevance_score(
    candidate: CandidateContent,
    query_variants: tuple[str, ...],
    preferred_languages: tuple[str, ...],
) -> float:
    variants = tuple(variant for variant in query_variants if variant.strip())
    if not variants:
        return 0.0

    title = _normalize_text(candidate.title or "")
    caption = _normalize_text(candidate.caption or "")
    tags = _normalize_text(" ".join(candidate.tags))
    searchable = " ".join(part for part in (title, caption, tags) if part)
    candidate_tokens = _tokens(searchable)
    if not candidate_tokens:
        return 0.0

    best = 0.0
    for variant in variants:
        normalized_variant = _normalize_text(variant)
        query_tokens = _tokens(normalized_variant)
        if not query_tokens:
            continue

        matched = sum(
            1
            for query_token in query_tokens
            if any(
                _token_matches(query_token, candidate_token)
                for candidate_token in candidate_tokens
            )
        )
        coverage = matched / len(query_tokens)
        phrase_bonus = 0.12 if len(query_tokens) > 1 and normalized_variant in searchable else 0.0
        title_bonus = (
            0.08
            if title
            and any(
                _token_matches(query_token, title_token)
                for query_token in query_tokens
                for title_token in _tokens(title)
            )
            else 0.0
        )
        best = max(best, min(1.0, coverage + phrase_bonus + title_bonus))

    language = candidate.connector_metadata.get("language")
    accepted_languages = {
        item.strip().lower().split("-", maxsplit=1)[0]
        for item in preferred_languages
        if item.strip()
    }
    if isinstance(language, str) and accepted_languages:
        normalized_language = language.lower().split("-", maxsplit=1)[0]
        if normalized_language in accepted_languages:
            best = min(1.0, best + 0.04)

    return round(best, 6)


def _quality_score(candidate: CandidateContent) -> float:
    score = 0.0

    acquisition_url = candidate.connector_metadata.get("acquisition_url")
    if isinstance(acquisition_url, str) and acquisition_url:
        score += 0.28

    if candidate.width is not None and candidate.height is not None:
        short_side = min(candidate.width, candidate.height)
        if short_side >= 1080:
            score += 0.22
        elif short_side >= 720:
            score += 0.18
        elif short_side >= 480:
            score += 0.12
        elif short_side > 0:
            score += 0.06

    if candidate.duration_ms is not None and candidate.duration_ms > 0:
        seconds = candidate.duration_ms / 1000
        if 5 <= seconds <= 180:
            score += 0.14
        else:
            score += 0.08

    score += 0.21 * _engagement_score(candidate)
    score += 0.15 * _text_hygiene_score(candidate)
    return round(min(1.0, score), 6)


def _engagement_score(candidate: CandidateContent) -> float:
    weights = {
        "like_count": 1.0,
        "reply_count": 1.25,
        "retweet_count": 2.0,
        "quote_count": 1.75,
        "bookmark_count": 1.5,
        "impression_count": 0.02,
    }
    weighted = 0.0
    for key, weight in weights.items():
        value = candidate.engagement.get(key, 0)
        if value > 0:
            weighted += value * weight
    return min(1.0, math.log1p(weighted) / math.log1p(10_000))


def _text_hygiene_score(candidate: CandidateContent) -> float:
    text = " ".join(part for part in (candidate.title, candidate.caption) if part)
    if not text:
        return 0.25

    normalized = " ".join(text.split())
    penalty = 0.0
    url_count = len(_URL.findall(normalized))
    hashtag_count = len(_HASHTAG.findall(normalized))
    if url_count > 2:
        penalty += min(0.4, 0.1 * (url_count - 2))
    if hashtag_count > 8:
        penalty += min(0.4, 0.04 * (hashtag_count - 8))
    if _REPEATED_PUNCTUATION.search(normalized):
        penalty += 0.15
    if len(normalized) > 1200:
        penalty += 0.15
    return round(max(0.0, 1.0 - penalty), 6)


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(token.casefold() for token in _TOKEN.findall(value) if len(token) >= 2)


def _token_matches(query: str, candidate: str) -> bool:
    if query == candidate:
        return True
    shorter, longer = sorted((query, candidate), key=len)
    return len(shorter) >= 4 and longer.startswith(shorter) and len(shorter) / len(longer) >= 0.55