import math
import re
from dataclasses import replace

from vimi_social.domain.source import CandidateContent

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_HASHTAG = re.compile(r"(?<!\w)#[^\s#]+", re.UNICODE)
_REPEATED_PUNCTUATION = re.compile(r"[!?]{4,}")


class CandidateCurator:
    """Deterministic, provider-free ranking for normalized Scout candidates."""

    def rank(
        self,
        candidates: tuple[CandidateContent, ...],
        *,
        query_variants: tuple[str, ...],
        preferred_languages: tuple[str, ...],
        limit: int,
    ) -> tuple[CandidateContent, ...]:
        if limit < 1:
            return ()

        scored: list[tuple[float, float, float, int, CandidateContent]] = []
        for index, candidate in enumerate(candidates):
            relevance = _relevance_score(candidate, query_variants, preferred_languages)
            quality = _quality_score(candidate)
            total = (0.78 * relevance) + (0.22 * quality)
            metadata = dict(candidate.connector_metadata)
            metadata["curator_relevance_score"] = relevance
            metadata["curator_quality_score"] = quality
            metadata["curator_total_score"] = round(total, 6)
            ranked = replace(candidate, connector_metadata=metadata)
            scored.append((total, relevance, quality, -index, ranked))

        scored.sort(key=lambda item: item[:4], reverse=True)
        return tuple(item[4] for item in scored[:limit])


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
        title_bonus = 0.08 if title and any(
            _token_matches(query_token, title_token)
            for query_token in query_tokens
            for title_token in _tokens(title)
        ) else 0.0
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
