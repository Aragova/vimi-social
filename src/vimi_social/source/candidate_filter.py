import math
import re
from collections.abc import Iterable
from dataclasses import replace
from uuid import UUID

from vimi_social.domain.source import CandidateContent, SourceTask
from vimi_social.source.continuation import ScoutContinuationActivities
from vimi_social.source.curator import CandidateCurator

_MIN_VIDEO_DURATION_MS = 60_000
_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_MENTION = re.compile(r"(?<!\w)@[\w_]+", re.UNICODE)
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_CONTINUATION_STATE_KEYS = (
    "retrieval_query",
    "retrieval_query_variants",
    "retrieval_relaxation_level",
    "retrieval_specificity",
    "retrieval_language_mode",
    "x_search_scope",
    "x_search_query",
    "x_next_token",
    "x_page_start_token",
    "x_continuation_generation",
)


def filter_scout_candidates(
    candidates: Iterable[CandidateContent],
    *,
    existing: Iterable[CandidateContent] = (),
    minimum_video_duration_ms: int = _MIN_VIDEO_DURATION_MS,
) -> tuple[CandidateContent, ...]:
    """Drop short videos and conservative near-duplicates before preview ranking.

    Unknown durations fail open because provider metadata can be incomplete. Known video
    durations below the configured minimum are rejected. Near-duplicate suppression is
    intentionally conservative and compares caption/title text after removing URLs and
    mentions. Existing persisted candidates are treated as immutable representatives so
    continuation pages cannot re-introduce the same promotional template. When one of
    two duplicates survives, the newest retrieval/continuation state is carried onto the
    surviving content so deduplication cannot rewind the paid X search cursor.
    """

    minimum_duration = max(0, minimum_video_duration_ms)
    existing_candidates = tuple(existing)
    seen_ids = {(candidate.source, candidate.source_id) for candidate in existing_candidates}
    protected_texts = tuple(
        text for candidate in existing_candidates if (text := _canonical_text(candidate))[0]
    )

    result: list[CandidateContent] = []
    result_texts: list[tuple[str, tuple[str, ...]]] = []

    for candidate in candidates:
        source_key = (candidate.source, candidate.source_id)
        if source_key in seen_ids:
            continue
        seen_ids.add(source_key)

        if _is_known_short_video(candidate, minimum_duration):
            continue

        canonical = _canonical_text(candidate)
        if canonical[0] and any(_near_duplicate(canonical, known) for known in protected_texts):
            continue

        duplicate_index: int | None = None
        if canonical[0]:
            for index, known in enumerate(result_texts):
                if _near_duplicate(canonical, known):
                    duplicate_index = index
                    break

        if duplicate_index is None:
            result.append(candidate)
            result_texts.append(canonical)
            continue

        current = result[duplicate_index]
        if _representative_key(candidate) > _representative_key(current):
            winner, other = candidate, current
            result_texts[duplicate_index] = canonical
        else:
            winner, other = current, candidate
        result[duplicate_index] = _with_latest_retrieval_state(winner, other)

    return tuple(result)


class FilteringCandidateCurator(CandidateCurator):
    """CandidateCurator with short-form rejection and conservative spam suppression."""

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

        filtered = filter_scout_candidates(candidates)
        if not filtered:
            return ()

        indices = _selected_indices(candidates, filtered)
        ranked = super().rank(
            filtered,
            query_variants=query_variants,
            preferred_languages=preferred_languages,
            limit=len(filtered),
            semantic_scores=_align_optional(semantic_scores, indices),
            visual_scores=_align_optional(visual_scores, indices),
            preview_ocr_texts=_align_optional(preview_ocr_texts, indices),
            preview_ocr_semantic_scores=_align_optional(
                preview_ocr_semantic_scores,
                indices,
            ),
            visual_weight=visual_weight,
            preview_ocr_weight=preview_ocr_weight,
            minimum_relevance=minimum_relevance,
        )

        rescored: list[tuple[float, float, float, float, float, int, CandidateContent]] = []
        for candidate in ranked:
            metadata = dict(candidate.connector_metadata)
            duration_preference = _duration_preference_score(candidate)
            metadata["curator_duration_preference_score"] = duration_preference
            updated = replace(candidate, connector_metadata=metadata)
            rescored.append(
                (
                    _metadata_float(metadata, "curator_relevance_score", 0.0),
                    _metadata_float(metadata, "curator_semantic_relevance_score", -1.0),
                    _metadata_float(metadata, "curator_lexical_relevance_score", 0.0),
                    duration_preference,
                    _metadata_float(metadata, "curator_quality_score", 0.0),
                    -_metadata_int(metadata, "curator_rank", 0),
                    updated,
                )
            )

        rescored.sort(key=lambda item: item[:6], reverse=True)
        result: list[CandidateContent] = []
        for rank, item in enumerate(rescored[:limit], start=1):
            candidate = item[6]
            metadata = dict(candidate.connector_metadata)
            metadata["curator_rank"] = rank
            result.append(replace(candidate, connector_metadata=metadata))
        return tuple(result)


class FilteringScoutContinuationActivities(ScoutContinuationActivities):
    """Persist continuation pages without re-introducing short or duplicate spam."""

    def _persist_owned_continuation(
        self,
        task: SourceTask,
        attempt_token: UUID,
        carrier: CandidateContent,
        accepted: tuple[CandidateContent, ...],
    ) -> None:
        existing = self._load_candidates(task)
        filtered = filter_scout_candidates(accepted, existing=existing)
        filtered = _offset_ranks(filtered, len(existing))
        super()._persist_owned_continuation(
            task,
            attempt_token,
            carrier,
            filtered,
        )


def _selected_indices(
    candidates: tuple[CandidateContent, ...],
    filtered: tuple[CandidateContent, ...],
) -> tuple[int, ...]:
    by_key = {
        (candidate.source, candidate.source_id): index
        for index, candidate in enumerate(candidates)
    }
    return tuple(by_key[(candidate.source, candidate.source_id)] for candidate in filtered)


def _align_optional[T](
    values: tuple[T, ...] | None,
    indices: tuple[int, ...],
) -> tuple[T, ...] | None:
    if values is None:
        return None
    return tuple(values[index] for index in indices)


def _offset_ranks(
    candidates: tuple[CandidateContent, ...],
    offset: int,
) -> tuple[CandidateContent, ...]:
    result: list[CandidateContent] = []
    for rank, candidate in enumerate(candidates, start=offset + 1):
        metadata = dict(candidate.connector_metadata)
        metadata["curator_rank"] = rank
        result.append(replace(candidate, connector_metadata=metadata))
    return tuple(result)


def _with_latest_retrieval_state(
    winner: CandidateContent,
    other: CandidateContent,
) -> CandidateContent:
    if _retrieval_state_key(other) < _retrieval_state_key(winner):
        return winner

    metadata = dict(winner.connector_metadata)
    for key in _CONTINUATION_STATE_KEYS:
        metadata.pop(key, None)
    for key in _CONTINUATION_STATE_KEYS:
        if key in other.connector_metadata:
            metadata[key] = other.connector_metadata[key]
    return replace(winner, connector_metadata=metadata)


def _retrieval_state_key(candidate: CandidateContent) -> tuple[int, int, int]:
    metadata = candidate.connector_metadata
    level = _metadata_int(metadata, "retrieval_relaxation_level", -1)
    language_mode = metadata.get("retrieval_language_mode")
    language_rank = (
        len(tuple(part for part in language_mode.split("+") if part))
        if isinstance(language_mode, str)
        else 0
    )
    generation = _metadata_int(metadata, "x_continuation_generation", 0)
    return (level, language_rank, generation)


def _duration_preference_score(candidate: CandidateContent) -> float:
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


def _metadata_int(metadata: dict[str, object], key: str, default: int) -> int:
    value = metadata.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


def _is_known_short_video(candidate: CandidateContent, minimum_duration_ms: int) -> bool:
    if candidate.media_type != "video":
        return False
    duration_ms = candidate.duration_ms
    return duration_ms is not None and 0 < duration_ms < minimum_duration_ms


def _canonical_text(candidate: CandidateContent) -> tuple[str, tuple[str, ...]]:
    raw = candidate.caption or candidate.title or ""
    if candidate.tags:
        raw = f"{raw} {' '.join(candidate.tags)}"
    normalized = _MENTION.sub(" ", _URL.sub(" ", raw)).casefold()
    tokens = tuple(token for token in _TOKEN.findall(normalized) if token)
    return (" ".join(tokens), tokens)


def _near_duplicate(
    left: tuple[str, tuple[str, ...]],
    right: tuple[str, tuple[str, ...]],
) -> bool:
    left_text, left_tokens = left
    right_text, right_tokens = right
    if not left_text or not right_text:
        return False
    if left_text == right_text:
        return True

    left_set = set(left_tokens)
    right_set = set(right_tokens)
    smaller = min(len(left_set), len(right_set))
    if smaller < 6:
        return False

    shared = len(left_set & right_set)
    required_shared = max(6, math.ceil(smaller * 0.88))
    if shared < required_shared:
        return False

    union = len(left_set | right_set)
    jaccard = shared / union if union else 0.0
    containment = shared / smaller
    return containment >= 0.88 and jaccard >= 0.70


def _representative_key(candidate: CandidateContent) -> tuple[int, int, int]:
    duration = candidate.duration_ms if candidate.duration_ms is not None else 0
    engagement = sum(max(0, value) for value in candidate.engagement.values())
    acquisition = candidate.connector_metadata.get("acquisition_url")
    has_acquisition = int(isinstance(acquisition, str) and bool(acquisition))
    return (duration, engagement, has_acquisition)
