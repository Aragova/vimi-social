from dataclasses import dataclass
from typing import cast

from vimi_social.domain.source import CandidateContent


@dataclass(frozen=True, slots=True)
class ScoutContinuationState:
    carrier: CandidateContent
    query_variants: tuple[str, ...]
    preferred_languages: tuple[str, ...]
    relaxation_level: int
    specificity: float
    search_scope: str
    next_token: str
    generation: int


def find_scout_continuation_state(
    candidates: tuple[CandidateContent, ...],
) -> ScoutContinuationState | None:
    """Return the next page for the latest paid X search round, if one exists."""

    latest_key: tuple[int, int] | None = None
    latest_candidates: list[CandidateContent] = []

    for candidate in candidates:
        metadata = candidate.connector_metadata
        raw_level = metadata.get("retrieval_relaxation_level")
        if not isinstance(raw_level, int) or isinstance(raw_level, bool) or raw_level < 0:
            continue
        language_mode = metadata.get("retrieval_language_mode")
        language_rank = (
            len(tuple(part for part in language_mode.split("+") if part))
            if isinstance(language_mode, str)
            else 0
        )
        key = (raw_level, language_rank)
        if latest_key is None or key > latest_key:
            latest_key = key
            latest_candidates = [candidate]
        elif key == latest_key:
            latest_candidates.append(candidate)

    if latest_key is None:
        return None

    latest_generation = max(
        (_continuation_generation(candidate) for candidate in latest_candidates),
        default=0,
    )
    generation_candidates = tuple(
        candidate
        for candidate in latest_candidates
        if _continuation_generation(candidate) == latest_generation
    )

    for candidate in generation_candidates:
        metadata = candidate.connector_metadata
        next_token = metadata.get("x_next_token")
        if not isinstance(next_token, str) or not next_token:
            continue

        raw_variants = metadata.get("retrieval_query_variants")
        if not isinstance(raw_variants, list):
            continue
        variant_values = cast(list[object], raw_variants)
        query_variants = tuple(
            value
            for value in variant_values
            if isinstance(value, str) and value.strip()
        )
        if not query_variants:
            continue

        language_mode = metadata.get("retrieval_language_mode")
        preferred_languages = (
            tuple(part for part in language_mode.split("+") if part)
            if isinstance(language_mode, str)
            else ()
        )
        raw_specificity = metadata.get("retrieval_specificity")
        if not isinstance(raw_specificity, int | float) or isinstance(raw_specificity, bool):
            continue
        search_scope = metadata.get("x_search_scope")
        if not isinstance(search_scope, str) or search_scope not in {"recent", "all"}:
            continue

        return ScoutContinuationState(
            carrier=candidate,
            query_variants=query_variants,
            preferred_languages=preferred_languages,
            relaxation_level=latest_key[0],
            specificity=max(0.0, min(1.0, float(raw_specificity))),
            search_scope=search_scope,
            next_token=next_token,
            generation=latest_generation,
        )

    return None


def _continuation_generation(candidate: CandidateContent) -> int:
    raw = candidate.connector_metadata.get("x_continuation_generation")
    if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
        return raw
    return 0